"""Step 4 helpers: the deterministic parts of chunk -> figure mapping.

  * associate_labels    -> give text-figures (code/tables) the label from their
        nearby caption block; diagrams are already labelled by the splicer.
        Labels are the join key, so this runs *before* the mapping model call.
  * build_reading_sequence -> assemble the ordered (chunk, [figures]) list the
        TTS layer walks, from the model's chunk -> figure-indices mapping.

The reference inference itself (Option A, LLM) lives in
Classifier.map_chunk_references.
"""
from __future__ import annotations

import re
from collections import defaultdict

from .models import BBox, Chunk, Figure, ReadingUnit, TextBlock
from .splicer import _h_overlap

# A real caption ("Figure 5.1: Calling fork()") -- the trailing colon
# distinguishes it from a passing prose mention ("as shown in Figure 5.1").
_CAPTION_LABEL_RE = re.compile(
    r"(figure|fig\.?|table)\s+(\d+(?:\.\d+)*)\s*:", re.IGNORECASE
)


def _caption_label(text: str) -> str | None:
    m = _CAPTION_LABEL_RE.search(text)
    if not m:
        return None
    kind = "Table" if m.group(1).lower().startswith("tab") else "Figure"
    return f"{kind} {m.group(2)}"


def associate_labels(figures: list[Figure], text_blocks: list[TextBlock]) -> None:
    """Fill in missing figure labels by matching each unlabelled figure to the
    nearest caption block **on the same page**. Mutates `figures` in place;
    figures already labelled (e.g. diagrams, done by the splicer) are untouched.

    Only true caption blocks are candidates (see `_caption_label`), and matching
    is page-scoped -- bbox coordinates are page-relative, so cross-page geometry
    is meaningless and previously produced garbage labels.
    """
    captions_by_page: dict[int, list[tuple[BBox, str]]] = defaultdict(list)
    for tb in text_blocks:
        lab = _caption_label(tb.text)
        if lab:
            captions_by_page[tb.page].append((tb.bbox, lab))
    for f in figures:
        if not f.label:
            f.label = _nearest_label(
                f.candidate.bbox, captions_by_page.get(f.candidate.page, [])
            )


def _nearest_label(fig_bbox: BBox, captions: list[tuple[BBox, str]]) -> str | None:
    """Nearest horizontally-overlapping caption below the figure, else above."""
    below: list[tuple[float, str]] = []
    above: list[tuple[float, str]] = []
    for cbbox, lab in captions:
        if _h_overlap(fig_bbox, cbbox) < 0.3:
            continue
        if cbbox[1] >= fig_bbox[3]:
            below.append((cbbox[1] - fig_bbox[3], lab))
        elif cbbox[3] <= fig_bbox[1]:
            above.append((fig_bbox[1] - cbbox[3], lab))
    if below:
        return min(below)[1]
    if above:
        return min(above)[1]
    return None


def build_reading_sequence(
    chunks: list[Chunk],
    figure_refs: dict[int, list[int]],
    figures: list[Figure],
) -> list[ReadingUnit]:
    """Ordered (chunk, [figures]) sequence for the TTS. Chunks are already in
    reading order; each is paired with its referenced figures (empty if none)."""
    by_index = {f.candidate.index: f for f in figures}
    units: list[ReadingUnit] = []
    for c in chunks:
        figs = [by_index[i] for i in figure_refs.get(c.block.index, []) if i in by_index]
        units.append(ReadingUnit(c, figs))
    return units
