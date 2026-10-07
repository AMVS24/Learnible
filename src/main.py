"""Run the v2 pipeline and report results.

    python -m src.main            # page range from src/config.py
    python -m src.main 46-82      # 1-based inclusive range
    python -m src.main 50         # a single page
    python -m src.main 46-82 --no-llm   # skip the qwen3 prose step (CPU only)
    python -m src.main 166-174 --out output/ostep/ch16   # see src/chapters.py

Pipeline: DocLayout-YOLO layout detection -> assemble chunks & figures
(code merge, caption->label, callout/title/code typing) -> qwen3 prose
sub-categorisation -> regex chunk->figure mapping. Writes
output/reading_sequence.json and prints a summary. See docs/ARCHITECTURE_v2.md.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import ollama

from . import config
from .assemble import assemble, merge_cross_page
from .layout import LayoutDetector
from .models import Chunk, Figure, ReadingUnit
from .page_export import export_page_images
from .reference import build_reading_sequence, map_references
from .subcategorize import Subcategorizer


def _parse_pages(spec: str | None) -> tuple[int, int]:
    """Parse a '46-54' or '46' page-range argument; fall back to config."""
    if not spec:
        return config.PAGE_START, config.PAGE_END
    try:
        nums = [int(p) for p in spec.replace(" ", "").split("-") if p]
    except ValueError:
        raise SystemExit(f"invalid page range: {spec!r} (use e.g. 46-54)")
    if not nums:
        return config.PAGE_START, config.PAGE_END
    return (nums[0], nums[0]) if len(nums) == 1 else (nums[0], nums[1])


def _output_dict(pdf: str, start: int, end: int, units: list[ReadingUnit],
                 figures: list[Figure], orphans: list[Figure],
                 pages: dict[int, dict]) -> dict:
    return {
        "source": {"pdf": pdf, "page_start": start, "page_end": end},
        "pages": pages,
        "reading_sequence": [
            {
                "index": u.chunk.block.index,
                "page": u.chunk.block.page,
                "category": u.chunk.category.value,
                "text": u.chunk.block.text,
                "bbox": [round(v, 1) for v in u.chunk.block.bbox],
                "figure_refs": [f.label for f in u.figures],
            }
            for u in units
        ],
        # No pre-cropped figure PNG: the frontend crops the figure+caption
        # region straight out of the full page image at render time, keyed
        # off bbox/caption_bbox (matches the recovered original app -- one
        # fewer export step, and captions stay attached to their figure).
        "figures": [
            {
                "index": f.candidate.index,
                "page": f.candidate.page,
                "label": f.label,
                "category": f.category.value,
                "source": f.source,
                "confidence": round(f.confidence, 2),
                "bbox": [round(v, 1) for v in f.candidate.bbox],
                "caption_bbox": [round(v, 1) for v in f.candidate.caption_bbox]
                                if f.candidate.caption_bbox else None,
                "caption": " ".join(f.candidate.nearby_text.split())[:160],
            }
            for f in figures
        ],
        "orphan_figures": [f.label or f"#{f.candidate.index}" for f in orphans],
    }


def _print_summary(chunks: list[Chunk], figures: list[Figure],
                   units: list[ReadingUnit], orphans: list[Figure]) -> None:
    print("\n=== Chunks ===")
    for cat, n in Counter(c.category.value for c in chunks).most_common():
        print(f"    {cat:22} {n}")
    print("=== Figures ===")
    for cat, n in Counter(f.category.value for f in figures).most_common():
        print(f"    {cat:22} {n}")

    linked = [u for u in units if u.figures]
    print(f"\n=== Mapping ===\n  chunks referencing a figure : {len(linked)} / {len(units)}")
    print(f"  orphan figures              : {len(orphans)} / {len(figures)}")
    for u in linked:
        labels = ", ".join(f.label or f"#{f.candidate.index}" for f in u.figures)
        preview = " ".join(u.chunk.block.text.split())[:52]
        print(f"    p{u.chunk.block.page} #{u.chunk.block.index:<3} -> [{labels}]  {preview}")
    if orphans:
        print("  orphans: " + ", ".join(f.label or f"#{f.candidate.index}" for f in orphans))


def main(argv: list[str] | None = None) -> int:
    # Textbook glyphs (e.g. combining-circle in "©") can exceed the Windows
    # console codepage; print lossily rather than crash.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    parser = argparse.ArgumentParser(
        prog="python -m src.main",
        description="Layout-detect + assemble + sub-categorise + map a page range.",
    )
    parser.add_argument("pages", nargs="?", default=None,
                        help="1-based inclusive range, e.g. 46-82 or 50")
    parser.add_argument("--no-llm", action="store_true",
                        help="skip qwen3 prose sub-categorisation (CPU only)")
    parser.add_argument("--pdf", default=None,
                        help="source PDF (default: config.PDF_PATH); src/chapters.py passes the active book's")
    parser.add_argument("--out", default=None,
                        help="output directory (default: output/); per-chapter runs "
                             "from src/chapters.py use output/<book>/<chapter>/")
    args = parser.parse_args(argv)
    pdf_path = Path(args.pdf) if args.pdf else config.PDF_PATH
    page_start, page_end = _parse_pages(args.pages)
    out_dir = Path(args.out) if args.out else config.OUTPUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Detecting layout in {pdf_path.name} pages {page_start}-{page_end} "
          f"with DocLayout-YOLO ...")
    regions = LayoutDetector().detect(str(pdf_path), page_start, page_end)
    chunks, figures = assemble(regions)
    chunks = merge_cross_page(chunks)  # stitch paragraphs split across pages
    print(f"  {len(regions)} regions -> {len(chunks)} chunks, {len(figures)} figures")

    # Prose sub-categorisation is the only GPU step; make it optional / graceful.
    use_llm = not args.no_llm
    if use_llm:
        try:
            ollama.Client(host=config.OLLAMA_HOST).list()
        except Exception:
            print("\nOllama not reachable — skipping prose sub-categorisation "
                  f"(prose stays 'info'). Start it + `ollama pull {config.MODEL}` "
                  "to enable.", file=sys.stderr)
            use_llm = False
    if use_llm:
        print(f"Sub-categorising prose with {config.MODEL} ...")
        Subcategorizer().run(chunks)
    else:
        print("Skipping LLM sub-categorisation (--no-llm).")

    refs, orphans = map_references(chunks, figures)
    units = build_reading_sequence(chunks, figures, refs)

    pages_dir = out_dir / "pages"
    pages = export_page_images(str(pdf_path), page_start, page_end, pages_dir)
    print(f"  wrote {len(pages)} page image(s) -> {pages_dir}")

    out = out_dir / "reading_sequence.json"
    out.write_text(
        json.dumps(_output_dict(str(pdf_path), page_start, page_end,
                                units, figures, orphans, pages), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _print_summary(chunks, figures, units, orphans)
    print(f"\n  wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
