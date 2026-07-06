"""Step 1: PDF Splice + content extraction.

Given a PDF and a 1-based inclusive page range, pull out:
  * text blocks   (chunk / text-figure candidates) with layout hints
  * visual figures (raster images + vector-diagram clusters) with captions

Purely mechanical — no semantics. The classifier assigns categories. Tables,
code, and callout boxes are left as text blocks here because in textbooks they
are text; the classifier recognises them from the text itself.
"""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

try:  # PyMuPDF exposes both names depending on version
    import pymupdf
except ImportError:  # pragma: no cover
    import fitz as pymupdf

from .models import BBox, FigureCandidate, SplicedDocument, TextBlock

# PyMuPDF span flag bits.
_FLAG_MONO = 1 << 3
_FLAG_BOLD = 1 << 4

# Font-name fragments that imply a monospace face (the mono flag bit is often
# absent even when the embedded font is monospaced, e.g. NimbusMon in OSTEP).
_MONO_NAMES = ("mono", "courier", "consol", "menlo", "nimbusmon", "cmtt", "txtt")

# Vector-diagram clustering: merge paths within this many points of each other,
# and treat text whose bbox is mostly inside a (padded) diagram region as part of
# the figure rather than the reading flow.
_DIAGRAM_GAP = 30.0
_DIAGRAM_PAD = 12.0

# A figure/table caption like "Figure 4.2" or "Table 1.1".
_CAPTION_RE = re.compile(r"\b(figure|fig\.?|table)\s+(\d+(?:\.\d+)*)", re.IGNORECASE)

# Callout / aside boxes are kept whole rather than split into paragraphs.
_CALLOUT_RE = re.compile(r"^\s*(TIP:|ASIDE:|NOTE:|WARNING:|THE CRUX|CRUX)", re.IGNORECASE)


def _area(b: BBox) -> float:
    return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])


def _center(b: BBox) -> tuple[float, float]:
    return ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)


def _h_overlap(a: BBox, b: BBox) -> float:
    """Fraction of the narrower box's width that overlaps horizontally."""
    overlap = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    narrower = min(a[2] - a[0], b[2] - b[0]) or 1.0
    return overlap / narrower


def _union(boxes: list[BBox]) -> BBox:
    return (
        min(b[0] for b in boxes),
        min(b[1] for b in boxes),
        max(b[2] for b in boxes),
        max(b[3] for b in boxes),
    )


def _pad(b: BBox, p: float) -> BBox:
    return (b[0] - p, b[1] - p, b[2] + p, b[3] + p)


def _contains_frac(inner: BBox, outer: BBox) -> float:
    """Fraction of `inner`'s area that lies within `outer`."""
    ix = max(0.0, min(inner[2], outer[2]) - max(inner[0], outer[0]))
    iy = max(0.0, min(inner[3], outer[3]) - max(inner[1], outer[1]))
    return (ix * iy) / (_area(inner) or 1.0)


def _lines_font(lines: list[dict]) -> tuple[str, float, bool, bool]:
    """Assemble text + dominant font size, bold-ness and mono-ness from lines."""
    parts: list[str] = []
    sizes: dict[float, int] = {}
    bold_chars = mono_chars = total_chars = 0
    for line in lines:
        line_parts = []
        for span in line.get("spans", []):
            txt = span.get("text", "")
            line_parts.append(txt)
            n = len(txt)
            total_chars += n
            size = round(span.get("size", 0.0), 1)
            sizes[size] = sizes.get(size, 0) + n
            flags = span.get("flags", 0)
            if flags & _FLAG_BOLD:
                bold_chars += n
            name = span.get("font", "").lower()
            if flags & _FLAG_MONO or any(m in name for m in _MONO_NAMES):
                mono_chars += n
        parts.append("".join(line_parts))
    text = "\n".join(parts).strip()
    dominant_size = max(sizes, key=sizes.get) if sizes else 0.0
    bold = total_chars > 0 and bold_chars / total_chars > 0.5
    mono = total_chars > 0 and mono_chars / total_chars > 0.5
    return text, dominant_size, bold, mono


def _paragraphs_of(block: dict) -> list[tuple[str, BBox, float, bool, bool]]:
    """Split a text block into paragraphs, returning (text, bbox, size, bold, mono)
    per paragraph.

    A paragraph boundary is a line whose left edge departs from the block's
    dominant (continuation) margin -- i.e. a first-line indent in prose, or the
    hanging bullet of a list item. Monospace code listings and callout/aside
    boxes are kept whole so they aren't shredded.
    """
    lines = [ln for ln in block.get("lines", []) if ln.get("spans")]
    if not lines:
        return []
    text, size, bold, mono = _lines_font(lines)
    bbox: BBox = tuple(block["bbox"])  # type: ignore[assignment]
    if mono or block.get("_code") or len(lines) == 1 or _CALLOUT_RE.match(text):
        return [(text, bbox, size, bold, mono or bool(block.get("_code")))]

    x0s = [round(ln["spans"][0]["bbox"][0]) for ln in lines]
    dominant, dom_count = Counter(x0s).most_common(1)[0]  # the continuation margin
    # If few lines share that margin the block isn't a left-aligned text column
    # (e.g. a centered header/footer) -- keep it whole rather than over-split.
    if dom_count <= 0.5 * len(lines):
        return [(text, bbox, size, bold, mono)]
    groups: list[list[dict]] = []
    for ln, x0 in zip(lines, x0s):
        if not groups or abs(x0 - dominant) > 2:
            groups.append([ln])
        else:
            groups[-1].append(ln)

    paras: list[tuple[str, BBox, float, bool, bool]] = []
    for g in groups:
        t, s, b, m = _lines_font(g)
        if t:
            paras.append((t, _union([tuple(ln["bbox"]) for ln in g]), s, b, m))
    return paras or [(text, bbox, size, bold, mono)]


_LINENO_RE = re.compile(r"^\s*\d+\s")


def _has_mono_span(block: dict) -> bool:
    for ln in block.get("lines", []):
        for sp in ln.get("spans", []):
            name = sp.get("font", "").lower()
            if sp.get("flags", 0) & _FLAG_MONO or any(m in name for m in _MONO_NAMES):
                return True
    return False


def _is_code_line(block: dict) -> bool:
    """Looks like one line of a numbered code listing: starts with a line number
    and contains monospace text. Font alone is unreliable here -- line numbers and
    roman-font comments dilute the mono ratio -- so key off the number prefix.
    (Section headings like '4.1 X' have a dot after the number; excluded.)"""
    return bool(_LINENO_RE.match(block.get("_text", ""))) and _has_mono_span(block)


def _merge_code_runs(blocks: list[dict]) -> list[dict]:
    """PyMuPDF emits each numbered code line as its own block, so a listing would
    otherwise become dozens of figures. Fuse a run of consecutive numbered code
    lines (plus tiny interspersed braces) that are left-aligned and vertically
    packed into one block.
    """
    blocks = sorted(blocks, key=lambda b: (round(b["bbox"][1]), round(b["bbox"][0])))
    out: list[dict] = []
    i, n = 0, len(blocks)
    while i < n:
        if not _is_code_line(blocks[i]):
            out.append(blocks[i])
            i += 1
            continue
        group = [blocks[i]]
        j = i + 1
        while j < n:
            nxt = blocks[j]
            gap = nxt["bbox"][1] - group[-1]["bbox"][3]
            aligned = abs(nxt["bbox"][0] - group[0]["bbox"][0]) < 40
            tiny = len(nxt["_text"].strip()) <= 3
            if (_is_code_line(nxt) or tiny) and -2 <= gap < 14 and aligned:
                group.append(nxt)
                j += 1
            else:
                break
        out.append(group[0] if len(group) == 1 else _fuse_blocks(group))
        i = j
    return out


def _fuse_blocks(group: list[dict]) -> dict:
    """Combine a run of raw text blocks into one (lines, bbox and text unioned)."""
    fused = dict(group[0])
    fused["lines"] = [ln for g in group for ln in g.get("lines", [])]
    fused["bbox"] = list(_union([tuple(g["bbox"]) for g in group]))
    fused["_text"] = "\n".join(g["_text"] for g in group)
    fused["_mono"] = True
    fused["_code"] = True
    return fused


def _parse_label(text: str) -> str | None:
    """Pull a 'Figure 4.2' / 'Table 1.1' style label out of caption text."""
    m = _CAPTION_RE.search(text)
    if not m:
        return None
    kind = "Table" if m.group(1).lower().startswith("tab") else "Figure"
    return f"{kind} {m.group(2)}"


def _caption_for(target: BBox, text_blocks: list[dict]) -> tuple[str, str | None]:
    """Caption for a visual element: the nearest horizontally-aligned block below
    it (else above). Prefers a real 'Figure/Table N' caption within reach and
    returns its parsed label when one is found."""
    below: list[tuple[float, str]] = []
    above: list[tuple[float, str]] = []
    for tb in text_blocks:
        b = tb["bbox"]
        if _h_overlap(target, b) < 0.3 or not tb["_text"]:
            continue
        if b[1] >= target[3]:
            below.append((b[1] - target[3], tb["_text"]))
        elif b[3] <= target[1]:
            above.append((target[1] - b[3], tb["_text"]))
    # Prefer the nearest block (either side, within reach) that reads like a caption.
    for dist, txt in sorted(below + above):
        if dist < 60 and _parse_label(txt):
            return txt, _parse_label(txt)
    if below:
        return min(below)[1], None
    if above:
        return min(above)[1], None
    return "", None


def splice(
    pdf_path: str | Path,
    page_start: int,
    page_end: int,
    spliced_pdf_out: str | Path | None = None,
) -> SplicedDocument:
    """Extract content for the inclusive 1-based page range [page_start, page_end]."""
    pdf_path = Path(pdf_path)
    doc = pymupdf.open(pdf_path)

    last = len(doc)
    if not (1 <= page_start <= page_end <= last):
        raise ValueError(
            f"page range {page_start}-{page_end} out of bounds for "
            f"{pdf_path.name} ({last} pages)"
        )

    out = SplicedDocument(str(pdf_path), page_start, page_end)
    idx = 0  # one shared index space across text blocks AND visual figures

    for pno in range(page_start - 1, page_end):
        page = doc[pno]
        human_page = pno + 1
        page_w, page_h = page.rect.width, page.rect.height
        page_area = page_w * page_h

        raw = page.get_text("dict").get("blocks", [])
        text_blocks_raw: list[dict] = []
        image_blocks_raw: list[dict] = []
        for blk in raw:
            if blk.get("type") == 0:
                t, *_ = _lines_font(blk.get("lines", []))  # whole-block text for captions
                if not t:
                    continue
                blk["_text"] = t
                text_blocks_raw.append(blk)
            elif blk.get("type") == 1:
                image_blocks_raw.append(blk)

        # Numbered code listings arrive as one block per line; fuse them so a
        # listing becomes a single figure candidate rather than dozens.
        text_blocks_raw = _merge_code_runs(text_blocks_raw)

        # Vector-diagram regions on this page (possibly several).
        diagrams = _detect_diagrams(page, page_w, page_area)

        def _inside_diagram(b: BBox) -> bool:
            # Text mostly within a (padded) diagram region is a figure label, not
            # part of the reading flow. Captions sit just outside and survive.
            return any(
                _contains_frac(b, _pad(region, _DIAGRAM_PAD)) > 0.6
                for region in diagrams
            )

        # --- text blocks, split paragraph-by-paragraph ----------------------
        for blk in text_blocks_raw:
            for ptext, pbbox, psize, pbold, pmono in _paragraphs_of(blk):
                if _inside_diagram(pbbox):
                    continue
                out.text_blocks.append(
                    TextBlock(
                        page=human_page,
                        index=idx,
                        bbox=pbbox,
                        text=ptext,
                        font_size=psize,
                        bold=pbold,
                        mono=pmono,
                    )
                )
                idx += 1

        # --- raster images --------------------------------------------------
        for blk in image_blocks_raw:
            bbox = tuple(blk["bbox"])  # type: ignore[assignment]
            caption, label = _caption_for(bbox, text_blocks_raw)
            out.visual_figures.append(
                FigureCandidate(human_page, idx, bbox, "image", caption, label)
            )
            idx += 1

        # --- vector-diagram clusters ---------------------------------------
        for region in diagrams:
            caption, label = _caption_for(region, text_blocks_raw)
            out.visual_figures.append(
                FigureCandidate(human_page, idx, region, "diagram", caption, label)
            )
            idx += 1

    if spliced_pdf_out is not None:
        spliced = pymupdf.open()
        spliced.insert_pdf(doc, from_page=page_start - 1, to_page=page_end - 1)
        spliced.save(str(spliced_pdf_out))
        spliced.close()

    doc.close()
    return out


def _close(a: BBox, b: BBox, gap: float) -> bool:
    """Do boxes a and b lie within `gap` points of each other (or overlap)?"""
    return not (
        a[2] + gap < b[0] or b[2] + gap < a[0]
        or a[3] + gap < b[1] or b[3] + gap < a[1]
    )


def _cluster_rects(rects: list[BBox], gap: float) -> list[tuple[BBox, int]]:
    """Greedily merge nearby rects into clusters; return (bbox, member_count)."""
    boxes = list(rects)
    counts = [1] * len(boxes)
    changed = True
    while changed:
        changed = False
        i = 0
        while i < len(boxes):
            j = i + 1
            while j < len(boxes):
                if _close(boxes[i], boxes[j], gap):
                    boxes[i] = _union([boxes[i], boxes[j]])
                    counts[i] += counts[j]
                    del boxes[j]
                    del counts[j]
                    changed = True
                else:
                    j += 1
            i += 1
    return list(zip(boxes, counts))


def _detect_diagrams(page, page_w: float, page_area: float) -> list[BBox]:
    """Vector-diagram regions on a page, clustered so multiple diagrams (or a
    diagram and an unrelated ruled table) don't get merged into one box.

    Filters full-width header/footer rules first. A diagram needs several paths;
    a lone ruled table (one or two rules) falls below the threshold and stays
    text, to be recognised by the classifier.
    """
    try:
        drawings = page.get_drawings()
    except Exception:
        return []

    rects: list[BBox] = []
    for d in drawings:
        r = d.get("rect")
        if r is None:
            continue
        b: BBox = (r.x0, r.y0, r.x1, r.y1)
        w, h = b[2] - b[0], b[3] - b[1]
        if h < 3 and w > 0.6 * page_w:  # running-head / footer rule
            continue
        rects.append(b)

    regions: list[BBox] = []
    for box, count in _cluster_rects(rects, _DIAGRAM_GAP):
        if count < 4:
            continue
        if not (0.02 * page_area < _area(box) < 0.85 * page_area):
            continue
        regions.append(box)
    return regions
