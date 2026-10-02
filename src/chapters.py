"""Chapter catalog + per-chapter rendering for a textbook PDF.

    python -m src.chapters scan              # print the chapter table, write output/<book>/catalog.json
    python -m src.chapters render 16 18      # pipeline + TTS for chapters 16 and 18
    python -m src.chapters render 16 --no-tts   # pipeline only (no audio)
    python -m src.chapters queue             # every unit in src/ostep_units.json, in order

Chapter boundaries come from the *page text*, not the book's printed index:
OSTEP is a concatenation of per-chapter PDFs, so every chapter restarts its
in-book numbering at 1 and the Contents page numbers are meaningless as PDF
page numbers. A chapter-opening page is recognised by its first two lines --
the chapter number/letter alone, then a mixed-case title ("16" /
"Segmentation") -- whereas every other page starts with a running header
whose title is ALL CAPS ("2" / "SEGMENTATION"). "Part I/II/III" divider pages
also end the previous chapter. The PDF outline is only a cross-check (it's off
by one for ch25/ch35, pointing at the blank page before each) and a fallback
for any opener with no extractable text -- those are flagged `verified: false`.

Only the chapter body is narrated: `body_end` stops before the page whose
heading is "References" (bibliographies read terribly via TTS -- see
docs/ARCHITECTURE_v2.md); References/Homework pages are still part of the
chapter's `pdf_end`.

Each chapter renders into its own fresh directory, output/<book>/ch<NN>/, so
nothing here overwrites the older ad-hoc output/ files.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import fitz  # PyMuPDF

from . import config

BOOK_ID = "ostep"
BOOK_TITLE = "Operating Systems: Three Easy Pieces"
BOOK_DIR = config.OUTPUT_DIR / BOOK_ID
_ORIGINAL_ENV = dict(os.environ)  # snapshot before YOLO mutates CUDA_VISIBLE_DEVICES (see render)

_CHAPTER_NUM = re.compile(r"^(\d{1,2}|[A-I])$")
_PART = re.compile(r"^Part [IVX]+$")
_OUTLINE_CH = re.compile(r"^(\d{1,2}|[A-I])\.?\s+(.*)$")


def _lines(page: fitz.Page, n: int = 4) -> list[str]:
    return [l.strip() for l in page.get_text().splitlines() if l.strip()][:n]


def _is_opener(lines: list[str]) -> tuple[str, str] | None:
    if len(lines) < 2 or not _CHAPTER_NUM.match(lines[0]):
        return None
    title = lines[1]
    if title.upper() == title:  # running header ("SEGMENTATION"), not a title page
        return None
    return lines[0], title


def scan_chapters(pdf_path: str) -> list[dict]:
    doc = fitz.open(pdf_path)
    try:
        n_pages = len(doc)
        starts: dict[str, dict] = {}   # chapter id -> {num, title, pdf_start, verified}
        parts: dict[int, str] = {}   # divider page -> "Part I: Virtualization"
        for i in range(n_pages):
            lines = _lines(doc[i])
            if lines and _PART.match(lines[0]):
                parts[i + 1] = f"{lines[0]}: {lines[1]}" if len(lines) > 1 else lines[0]
                continue
            hit = _is_opener(lines)
            if hit and hit[0] not in starts:
                starts[hit[0]] = {"num": hit[0], "title": hit[1], "pdf_start": i + 1, "verified": True}

        # Cross-check / fill gaps from the outline.
        for level, text, page in doc.get_toc():
            m = _OUTLINE_CH.match(text)
            if level != 2 or not m:
                continue
            num, title = m.group(1).lstrip("0"), m.group(2).replace(" - ", ": ")
            if num not in starts:
                starts[num] = {"num": num, "title": title, "pdf_start": page, "verified": False}
                continue
            c = starts[num]
            # A title that wraps onto a second line on the opener page
            # ("Scheduling:" / "The Multi-Level Feedback Queue") is cut short
            # by _is_opener; the outline carries the whole thing.
            if len(title) > len(c["title"]) and title.startswith(c["title"]):
                c["title"] = title
            if c["pdf_start"] != page:
                print(f"  note: ch{num} opener found on PDF p{c['pdf_start']}, "
                      f"outline says p{page} -- using the page text", file=sys.stderr)

        ordered = sorted(starts.values(), key=lambda c: c["pdf_start"])
        boundaries = sorted({c["pdf_start"] for c in ordered} | set(parts) | {n_pages + 1})
        chapters = []
        for c in ordered:
            end = next(b for b in boundaries if b > c["pdf_start"]) - 1
            body_end = end
            for p in range(c["pdf_start"] + 1, end + 1):
                if "References" in _lines(doc[p - 1]):
                    body_end = p - 1
                    break
            # Sidebar grouping: the last Part divider before this chapter
            # (ch1-2 precede Part I; lettered chapters are the appendix).
            part = next((t for pg, t in sorted(parts.items(), reverse=True)
                         if pg < c["pdf_start"]), "Introduction")
            if not c["num"].isdigit():
                part = "Appendix"
            chapters.append({
                "id": f"ch{int(c['num']):02d}" if c["num"].isdigit() else f"app{c['num']}",
                "num": c["num"],
                "title": c["title"],
                "part": part,
                "pdf_start": c["pdf_start"],
                "pdf_end": end,
                "body_end": body_end,
                "verified": c["verified"],
            })
        return chapters
    finally:
        doc.close()


def _chapter_dir(ch: dict) -> Path:
    return BOOK_DIR / ch["id"]


UNITS_PATH = config.PROJECT_ROOT / "src" / f"{BOOK_ID}_units.json"


def load_units() -> list[dict]:
    if not UNITS_PATH.exists():
        return []
    return json.loads(UNITS_PATH.read_text(encoding="utf-8"))["units"]


def _is_rendered(d: Path) -> bool:
    return (d / "manifest.json").exists() and (d / "narration.mp3").exists()


def write_catalog(chapters: list[dict]) -> Path:
    """catalog.json drives the web app's sidebar; `rendered` marks entries
    whose manifest.json + narration.mp3 exist. Partial-chapter units from
    ostep_units.json are listed right after their parent chapter
    (`partial: true`, `parent: "chNN"`)."""
    BOOK_DIR.mkdir(parents=True, exist_ok=True)
    out = BOOK_DIR / "catalog.json"
    partials: dict[str, list[dict]] = {}
    for u in load_units():
        if u.get("id"):
            partials.setdefault(u["chapter"].lstrip("0"), []).append(u)
    entries = []
    for ch in chapters:
        ch["rendered"] = _is_rendered(_chapter_dir(ch))
        entries.append(ch)
        for u in partials.get(ch["num"], []):
            d = BOOK_DIR / u["id"]
            src = {}
            if (d / "reading_sequence.json").exists():
                src = json.loads((d / "reading_sequence.json").read_text(encoding="utf-8"))["source"]
            entries.append({
                **{k: ch[k] for k in ("num", "part", "verified")},
                "id": u["id"], "title": u["title"], "partial": True, "parent": ch["id"],
                "start_heading": u.get("start"), "stop_heading": u.get("stop"),
                "pdf_start": src.get("page_start", ch["pdf_start"]),
                "pdf_end": src.get("page_end", ch["body_end"]),
                "body_end": src.get("page_end", ch["body_end"]),
                "rendered": _is_rendered(d),
            })
    out.write_text(json.dumps({"id": BOOK_ID, "title": BOOK_TITLE, "chapters": entries},
                              ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def _find(chapters: list[dict], key: str) -> dict:
    for ch in chapters:
        if ch["num"].lower() == key.lower().lstrip("0") or ch["id"] == key:
            return ch
    raise SystemExit(f"no chapter {key!r} -- run `python -m src.chapters scan` to list them")


def _norm(s: str) -> str:
    s = s.replace("ﬁ", "fi").replace("ﬂ", "fl").replace("’", "'")
    return re.sub(r"\s+", " ", s).strip().casefold()


def heading_page(pdf_path: str, heading: str, lo: int, hi: int) -> int:
    """PDF page (in lo..hi) whose text has `heading` as its own line -- or
    split over two lines ("28.3" / "Building A Lock"). Exactly one match is
    required, so a heading that also shows up in running text can't
    silently pick the wrong page."""
    want = _norm(heading)
    hits = set()
    doc = fitz.open(pdf_path)
    try:
        for p in range(lo, hi + 1):
            lines = [_norm(l) for l in doc[p - 1].get_text().splitlines() if l.strip()]
            for i, l in enumerate(lines):
                if l == want or (i + 1 < len(lines) and f"{l} {lines[i + 1]}" == want):
                    hits.add(p)
    finally:
        doc.close()
    if len(hits) != 1:
        raise RuntimeError(f"heading {heading!r} found on pages {sorted(hits)} in {lo}-{hi}; need exactly one")
    return hits.pop()


def _chunk_matches(unit: dict, heading: str) -> bool:
    text, want = _norm(unit["text"]), _norm(heading)
    bare = re.sub(r"^[\d.]+\s+", "", want)  # "28.3 building a lock" -> "building a lock"
    return text.startswith(want) or (unit["category"] == "title" and text.startswith(bare))


def trim_sequence(path: Path, start: str | None, stop: str | None) -> tuple[int, int]:
    """Cut reading_sequence.json down to [start heading, stop heading). The
    pipeline runs over whole pages, so this drops the bleed from the
    neighbouring sections that share the first/last page."""
    data = json.loads(path.read_text(encoding="utf-8"))
    seq = data["reading_sequence"]
    i0 = 0
    if start:
        i0 = next((i for i, u in enumerate(seq) if _chunk_matches(u, start)), None)
        if i0 is None:
            raise RuntimeError(f"start heading {start!r} not found among extracted chunks")
    i1 = len(seq)
    if stop:
        i1 = next((i for i, u in enumerate(seq) if i > i0 and _chunk_matches(u, stop)), None)
        if i1 is None:
            raise RuntimeError(f"stop heading {stop!r} not found among extracted chunks")
    data["reading_sequence"] = seq[i0:i1]
    data["source"]["trim"] = {"start": start, "stop": stop}
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return i1 - i0, len(seq) - (i1 - i0)


def _prepared(seq_path: Path, trimmed: bool) -> bool:
    """Text prep (pipeline + any trim) finished: `chapter_start` is the last
    thing render_unit writes, and a partial unit must also carry `trim`."""
    if not seq_path.exists():
        return False
    src = json.loads(seq_path.read_text(encoding="utf-8"))["source"]
    return "chapter_start" in src and (not trimmed or "trim" in src)


def render_unit(chapters: list[dict], unit: dict, tts: bool = True, llm: bool = True) -> str:
    """Render one unit (a whole chapter body, or a heading-trimmed part of
    one) into its own directory. Never overwrites: an existing output dir is
    skipped (complete) or reported (incomplete) and left untouched."""
    from . import main as pipeline
    ch = _find(chapters, unit["chapter"])
    uid = unit.get("id") or ch["id"]
    out_dir = BOOK_DIR / uid
    start, stop = unit.get("start"), unit.get("stop")
    seq_path = out_dir / "reading_sequence.json"
    if _is_rendered(out_dir):
        return "skipped (already rendered)"
    if out_dir.exists() and not _prepared(seq_path, trimmed=bool(start or stop)):
        # Empty dir = claimed by the other machine in a split queue; anything
        # else half-made is left for a human to look at, never overwritten.
        raise RuntimeError(f"{out_dir} exists but isn't a resumable unit -- leaving it alone")

    if out_dir.exists():
        # Text prep finished in an earlier, interrupted run; only the audio is
        # missing, so just add it (new files only).
        src = json.loads(seq_path.read_text(encoding="utf-8"))["source"]
        p0, p1 = src["page_start"], src["page_end"]
        print(f"\n##### {uid}: resuming at TTS (text prep already done) -> {out_dir}")
        note = ", resumed at TTS"
    else:
        pdf = str(config.PDF_PATH)
        p0 = heading_page(pdf, start, ch["pdf_start"], ch["body_end"]) if start else ch["pdf_start"]
        p1 = heading_page(pdf, stop, p0, ch["body_end"]) if stop else ch["body_end"]
        print(f"\n##### {uid} ({ch['title']}): PDF pages {p0}-{p1}"
              f"{f', from {start!r}' if start else ''}{f', stop before {stop!r}' if stop else ''} -> {out_dir}")

        pipeline.main([f"{p0}-{p1}", "--out", str(out_dir)] + ([] if llm else ["--no-llm"]))
        note = ""
        if start or stop:
            kept, dropped = trim_sequence(seq_path, start, stop)
            note = f", trimmed to {kept} chunks ({dropped} bleed chunks dropped)"
        data = json.loads(seq_path.read_text(encoding="utf-8"))
        # Chapter-relative page numbers in the web header count from the
        # chapter opener, not from wherever a partial unit starts. Written
        # last: its presence marks the text prep as complete (see _prepared).
        data["source"]["chapter_start"] = ch["pdf_start"]
        seq_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    if tts:
        # Separate process with the *original* environment: the layout
        # stage's YOLO device selection ("cpu") sets
        # os.environ["CUDA_VISIBLE_DEVICES"] = "-1" (doclayout_yolo
        # torch_utils.select_device), which would otherwise silently push
        # Chatterbox onto the CPU -- in-process or inherited by a child.
        subprocess.run([sys.executable, "-m", "tts.synth_local",
                        "--input", str(seq_path), "--output", str(out_dir / "narration.wav")],
                       cwd=config.PROJECT_ROOT, env=_ORIGINAL_ENV, check=True)
    return f"rendered PDF {p0}-{p1}{note}"


def print_status(log: Path | None) -> None:
    """Per-unit state of the render queue (read-only): done (with narration
    length), in progress / claimed, or pending -- plus the latest passage
    counter from a queue log, if given."""
    done = 0
    units = load_units()
    for u in units:
        uid = u.get("id") or f"ch{int(u['chapter']):02d}"
        d = BOOK_DIR / uid
        if _is_rendered(d):
            chunks = json.loads((d / "manifest.json").read_text(encoding="utf-8"))["chunks"]
            state, done = f"done      {chunks[-1]['t1'] / 60:5.1f} min", done + 1
        elif (d / "reading_sequence.json").exists():
            state = "in progress (TTS)" if _prepared(d / "reading_sequence.json", bool(u.get("start") or u.get("stop"))) \
                else "in progress (text)"
        elif d.exists():
            state = "in progress (text)"
        else:
            state = "pending"
        print(f"  {uid:16} {state}")
    print(f"\n  {done}/{len(units)} units done")
    if log and log.exists():
        text = log.read_text(encoding="utf-8", errors="replace").replace("\r", "\n")
        heads = re.findall(r"^##### (\S+)", text, re.M)
        counts = re.findall(r"^\s+(\d+)/(\d+)\s+\(([\d.]+) min so far\)", text, re.M)
        if heads:
            cur = f"  current: {heads[-1]}"
            if counts and text.rfind("##### ") < text.rfind(f"{counts[-1][0]}/{counts[-1][1]}"):
                cur += f"  passage {counts[-1][0]}/{counts[-1][1]} ({counts[-1][2]} min of audio so far)"
            print(cur)


def run_units(chapters: list[dict], units: list[dict], tts: bool, llm: bool) -> None:
    """Render units in order; one failure doesn't stop the rest."""
    results = []
    for u in units:
        uid = u.get("id") or _find(chapters, u["chapter"])["id"]
        try:
            results.append((uid, "ok", render_unit(chapters, u, tts, llm)))
        except Exception as e:  # noqa: BLE001 -- report it and carry on with the queue
            results.append((uid, "FAILED", f"{type(e).__name__}: {e}"))
            print(f"\n!!!!! {uid} FAILED: {e}", file=sys.stderr)
        write_catalog(chapters)  # keep the catalog current as units land
    print("\n===== queue summary")
    for uid, status, msg in results:
        print(f"  {uid:14} {status:6} {msg}")


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    parser = argparse.ArgumentParser(prog="python -m src.chapters")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("scan", help="detect chapters and write catalog.json")
    r = sub.add_parser("render", help="run pipeline (+TTS) for chapters, e.g. 16 18")
    r.add_argument("chapters", nargs="+")
    r.add_argument("--no-tts", action="store_true", help="skip Chatterbox narration")
    r.add_argument("--no-llm", action="store_true", help="skip qwen3 prose sub-categorisation")
    q = sub.add_parser("queue", help=f"render every unit in src/{UNITS_PATH.name}, in order, skipping done ones")
    q.add_argument("--no-tts", action="store_true")
    q.add_argument("--no-llm", action="store_true")
    q.add_argument("--reverse", action="store_true",
                   help="work from the back of the list (a second machine splitting the queue; "
                        "a unit whose output dir already exists is left alone either way)")
    s = sub.add_parser("status", help="show render-queue progress (read-only)")
    s.add_argument("--log", default=None, help="queue log to read the current passage counter from")
    args = parser.parse_args(argv)

    if args.cmd == "status":
        print_status(Path(args.log) if args.log else None)
        return 0
    chapters = scan_chapters(str(config.PDF_PATH))
    if args.cmd == "scan":
        for ch in chapters:
            flag = "" if ch["verified"] else "  (outline fallback)"
            print(f"  {ch['id']:6} PDF {ch['pdf_start']:>3}-{ch['pdf_end']:<3} body..{ch['body_end']:<3} "
                  f"{ch['title']}{flag}")
    elif args.cmd == "queue":
        units = load_units()
        run_units(chapters, units[::-1] if args.reverse else units,
                  tts=not args.no_tts, llm=not args.no_llm)
    else:
        run_units(chapters, [{"chapter": k} for k in args.chapters],
                  tts=not args.no_tts, llm=not args.no_llm)
    print(f"\n  wrote {write_catalog(chapters)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
