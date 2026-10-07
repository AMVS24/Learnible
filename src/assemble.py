"""Stages 3-4 (v2): turn DocLayout-YOLO `Region`s into `Chunk`s and `Figure`s.

This is the deterministic heart of the v2 pipeline. Given the regions from
`layout.py` (in reading order) it:

  1. tie-breaks overlapping figure/table detections on the same diagram,
  2. merges adjacent monospace regions into whole code listings,
  3. associates each figure/table/code listing with its caption region and
     parses the `Figure N` / `Table N` label from it (the join key for mapping),
  4. types every remaining region into a Chunk or a Figure:
       * title            -> Chunk(title)
       * callout box      -> Chunk(isolated_textbox)      (TIP/ASIDE/CRUX prefix)
       * captioned code   -> Figure(code_listing)
       * un-captioned code-> Chunk(code_listing) with a spoken placeholder body
       * figure / table    -> Figure(referable / table)
       * other prose      -> Chunk (category left provisional for the LLM sub-
                             categoriser in stage 3b)

Prose chunks come out tagged `PENDING_SUBCAT` so the qwen3 pass knows which to
refine; everything else is already final and deterministic.
"""
from __future__ import annotations

import re

from .models import (
    BBox, Chunk, ChunkCategory, Figure, FigureCandidate, FigureCategory,
    Region, TextBlock,
)

# --- region-class groupings --------------------------------------------------
CAPTION_CLASSES = {"figure_caption", "table_caption"}
FIGURE_CLASSES = {"figure", "table"}
# page furniture / not-yet-handled classes are dropped from the reading flow
DROP_CLASSES = {"abandon", "table_footnote", "isolate_formula", "formula_caption"}

# --- text probes -------------------------------------------------------------
# "Figure 4.5" (OSTEP) or "Figure 2-1" (Lewis & Papadimitriou). The "-"
# form is canonicalised to "." so a caption and a mention always agree.
_LABEL_RE = re.compile(r"\b(figure|fig\.?|table)\s+(\d+(?:[.-]\d+)*)", re.I)

# spoken body for an un-captioned inline code sample (kept in reading order)
CODE_PLACEHOLDER = "Refer to the code segment here."
# reason marker: this chunk is prose awaiting LLM sub-categorisation
PENDING_SUBCAT = "pending-subcat"

# code-merge geometry: vertical gap (pt) under which two mono regions are "one"
_CODE_MERGE_GAP = 28.0
# callout-merge geometry: gap under which two shaded regions are the same box
_CALLOUT_MERGE_GAP = 30.0


def _canonical(match: "re.Match") -> str:
    kind = "Table" if match.group(1).lower().startswith("tab") else "Figure"
    return f"{kind} {match.group(2).replace('-', '.')}"


def parse_label(text: str) -> str | None:
    """Pull a canonical figure/table label out of a caption, e.g.
    'Figure 4.1: Loading...' -> 'Figure 4.1'."""
    m = _LABEL_RE.search(text)
    return _canonical(m) if m else None


def find_labels(text: str) -> list[str]:
    """All distinct figure/table names *mentioned* in a passage, canonicalised
    (e.g. 'Fig. 4.5' -> 'Figure 4.5'). Used by the mapper to find explicit
    references."""
    out: list[str] = []
    for m in _LABEL_RE.finditer(text):
        lab = _canonical(m)
        if lab not in out:
            out.append(lab)
    return out


def assemble(regions: list[Region]) -> tuple[list[Chunk], list[Figure]]:
    """Reading-ordered `Region`s -> (chunks, figures)."""
    regions = _tie_break_fig_table(regions)
    regions = _suppress_fig_over_code(regions)
    regions = _merge_shaded(regions)   # group shaded panels into callout boxes
    regions = _merge_code(regions)
    captions = [r for r in regions if r.cls in CAPTION_CLASSES]
    used: set[int] = set()

    chunks: list[Chunk] = []
    figures: list[Figure] = []
    for r in regions:
        if r.cls in DROP_CLASSES or r.cls in CAPTION_CLASSES:
            continue  # furniture, or a caption consumed as a label

        if r.cls == "isolated_textbox":                   # a shaded callout box
            chunks.append(Chunk(_tb(r), ChunkCategory.isolated_textbox,
                                r.confidence, "shaded box"))

        elif r.cls == "title":
            chunks.append(Chunk(_tb(r), ChunkCategory.title, r.confidence, "yolo:title"))

        elif r.cls in FIGURE_CLASSES:
            cap = _find_caption(r, captions, used)
            label = parse_label(cap.text) if cap else None
            cat = FigureCategory.table if r.cls == "table" else FigureCategory.referable
            figures.append(_fig(r, cap, label, cat, "yolo:" + r.cls, kind=r.cls))

        elif r.cls == "plain text" and r.mono:            # a code listing
            cap = _find_caption(r, captions, used)
            if cap:                                        # captioned -> Figure
                label = parse_label(cap.text)
                figures.append(_fig(r, cap, label, FigureCategory.code_listing,
                                    "captioned code", kind="code"))
            else:                                          # inline -> Chunk
                chunks.append(Chunk(
                    _tb(r, text=CODE_PLACEHOLDER),
                    ChunkCategory.code_listing, r.confidence, "un-captioned code",
                ))

        elif r.cls == "plain text":                        # ordinary prose -> LLM
            chunks.append(Chunk(_tb(r), ChunkCategory.info, 0.0, PENDING_SUBCAT))
        # any other class: dropped
    return chunks, figures


# ------------------------------------------------------------------ tie-break
def _tie_break_fig_table(regions: list[Region]) -> list[Region]:
    """If a `figure` and a `table` (or two of a kind) overlap heavily on a page,
    they are the same object detected twice -- keep the higher-confidence one."""
    figs = [r for r in regions if r.cls in FIGURE_CLASSES]
    drop: set[int] = set()
    for i, a in enumerate(figs):
        for b in figs[i + 1:]:
            if a.page == b.page and _iou(a.bbox, b.bbox) >= 0.5:
                drop.add(id(a if a.confidence < b.confidence else b))
    return [r for r in regions if id(r) not in drop]


# --------------------------------------------------- figure-over-code dup fix
def _suppress_fig_over_code(regions: list[Region]) -> list[Region]:
    """Drop a `figure`/`table` box that coincides with a monospace region: the
    detector sometimes reports a code listing as both `plain text` (mono) and a
    `figure`. The code listing is the real entity (it owns the caption), so the
    duplicate figure box -- which would end up an orphan -- is removed."""
    mono = [r for r in regions if r.cls == "plain text" and r.mono]
    drop: set[int] = set()
    for r in regions:
        if r.cls in FIGURE_CLASSES and any(
            r.page == m.page and _iou(r.bbox, m.bbox) >= 0.5 for m in mono
        ):
            drop.add(id(r))
    return [r for r in regions if id(r) not in drop]


# ---------------------------------------------- cross-page paragraph stitching
# text categories that can legitimately continue across a page break
_STITCH_CATS = {ChunkCategory.info, ChunkCategory.isolated_textbox}
_SENTENCE_ENDERS = tuple(".?!:)]\"'")


def merge_cross_page(chunks: list[Chunk]) -> list[Chunk]:
    """Stitch a paragraph split across a page break back into one chunk.

    A split is detected when a prose chunk ends mid-sentence (no terminal
    punctuation -- typically a hyphen) and the next prose chunk, on a later
    page, begins lower-case. A trailing hyphen is dissolved ('read-' + 'ing' ->
    'reading'); otherwise the halves are space-joined. Runs before the LLM step
    so the model sees the whole paragraph.

    The page check is `>`, not `== +1`: a figure/table/callout can occupy one
    or more whole pages between the two halves with no prose chunk of its own
    (figures/tables/captions never appear in `chunks`, only in the separate
    `figures` list -- see `assemble()`), so the two paragraph-half chunks are
    still adjacent in this list however many intervening pages there were.
    The linguistic signals (no terminal punctuation + lower-case continuation)
    are what actually gate the merge, not page adjacency."""
    out: list[Chunk] = []
    for c in chunks:
        if out:
            a = out[-1]
            at, ct = a.block.text.rstrip(), c.block.text.lstrip()
            if (a.category in _STITCH_CATS and c.category in _STITCH_CATS
                    and a.reason == PENDING_SUBCAT and c.reason == PENDING_SUBCAT
                    and c.block.page > a.block.page
                    and at and ct and not at.endswith(_SENTENCE_ENDERS)
                    and ct[:1].islower()):
                a.block.text = (at[:-1] + ct) if at.endswith("-") else (at + " " + ct)
                continue
        out.append(c)
    return out


# -------------------------------------------------------------- callout merge
def _merge_shaded(regions: list[Region]) -> list[Region]:
    """Reconstruct a callout/sidebar box from its pieces. DocLayout-YOLO splits a
    shaded box into `title` + `plain text` regions; here consecutive shaded
    text/title regions are fused into one `isolated_textbox` region so the box
    stays intact and never reaches the prose LLM."""
    out: list[Region] = []
    i, n = 0, len(regions)
    while i < n:
        r = regions[i]
        if r.shaded and r.cls in ("plain text", "title"):
            group = [r]
            j = i + 1
            while (j < n and regions[j].shaded
                   and regions[j].cls in ("plain text", "title")
                   and regions[j].page == r.page
                   and regions[j].bbox[1] - group[-1].bbox[3] < _CALLOUT_MERGE_GAP):
                group.append(regions[j])
                j += 1
            out.append(_fuse_shaded(group))
            i = j
        else:
            out.append(r)
            i += 1
    return out


def _fuse_shaded(group: list[Region]) -> Region:
    x0 = min(g.bbox[0] for g in group)
    y0 = min(g.bbox[1] for g in group)
    x1 = max(g.bbox[2] for g in group)
    y1 = max(g.bbox[3] for g in group)
    # A header is sometimes detected as both `title` and `plain text` at the same
    # spot; drop exact-duplicate fragments so the box text isn't doubled.
    seen: set[str] = set()
    parts: list[str] = []
    for g in group:
        t = g.text.strip()
        if t and t not in seen:
            seen.add(t)
            parts.append(t)
    return Region(
        page=group[0].page, index=group[0].index, bbox=(x0, y0, x1, y1),
        cls="isolated_textbox", confidence=max(g.confidence for g in group),
        text=" ".join(parts), mono=False, shaded=True,
    )


# ------------------------------------------------------------------ code merge
def _merge_code(regions: list[Region]) -> list[Region]:
    """Fuse runs of consecutive, vertically-adjacent monospace regions into one
    code-listing region (PyMuPDF/YOLO can split a listing into several boxes)."""
    out: list[Region] = []
    i, n = 0, len(regions)
    while i < n:
        r = regions[i]
        if r.cls == "plain text" and r.mono:
            group = [r]
            j = i + 1
            while (j < n and regions[j].cls == "plain text" and regions[j].mono
                   and regions[j].page == r.page
                   and regions[j].bbox[1] - group[-1].bbox[3] < _CODE_MERGE_GAP):
                group.append(regions[j])
                j += 1
            out.append(group[0] if len(group) == 1 else _fuse(group))
            i = j
        else:
            out.append(r)
            i += 1
    return out


def _fuse(group: list[Region]) -> Region:
    x0 = min(g.bbox[0] for g in group)
    y0 = min(g.bbox[1] for g in group)
    x1 = max(g.bbox[2] for g in group)
    y1 = max(g.bbox[3] for g in group)
    return Region(
        page=group[0].page, index=group[0].index, bbox=(x0, y0, x1, y1),
        cls="plain text", confidence=max(g.confidence for g in group),
        text="\n".join(g.text for g in group), mono=True,
    )


# ------------------------------------------------------------ caption matching
def _find_caption(r: Region, captions: list[Region], used: set[int]) -> Region | None:
    """Nearest unused caption region on the same page that overlaps horizontally
    and sits just below (preferred) or above `r`, within 60 pt."""
    best: Region | None = None
    best_gap = 1e9
    for c in captions:
        if id(c) in used or c.page != r.page:
            continue
        if _h_overlap(r.bbox, c.bbox) < 0.2:
            continue
        if c.bbox[1] >= r.bbox[3] - 2:            # caption below the figure
            gap = c.bbox[1] - r.bbox[3]
        elif c.bbox[3] <= r.bbox[1] + 2:          # caption above the figure
            gap = r.bbox[1] - c.bbox[3]
        else:
            continue
        if gap < best_gap and gap < 60:
            best_gap, best = gap, c
    if best is not None:
        used.add(id(best))
    return best


# --------------------------------------------------------------------- helpers
def _tb(r: Region, text: str | None = None) -> TextBlock:
    return TextBlock(page=r.page, index=r.index, bbox=r.bbox,
                     text=text if text is not None else r.text,
                     font_size=0.0, bold=False, mono=r.mono)


def _fig(r: Region, cap: Region | None, label: str | None,
         cat: FigureCategory, reason: str, kind: str) -> Figure:
    cand = FigureCandidate(page=r.page, index=r.index, bbox=r.bbox, kind=kind,
                           nearby_text=cap.text if cap else "", label=label,
                           caption_bbox=cap.bbox if cap else None)
    src = "text" if kind == "code" else "visual"
    return Figure(cand, cat, label, r.confidence, reason, source=src)


def _h_overlap(a: BBox, b: BBox) -> float:
    inter = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    narrow = min(a[2] - a[0], b[2] - b[0])
    return inter / narrow if narrow > 0 else 0.0


def _iou(a: BBox, b: BBox) -> float:
    iw = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    ih = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = iw * ih
    if inter == 0:
        return 0.0
    area_a = (a[2] - a[0]) * (a[3] - a[1])
    area_b = (b[2] - b[0]) * (b[3] - b[1])
    return inter / (area_a + area_b - inter)
