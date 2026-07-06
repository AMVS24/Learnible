"""Stage 5 (v2): map chunks to the figures they explicitly reference.

Now that captions give every figure a trustworthy label, mapping is deterministic
regex: for each chunk, find the figure/table names it mentions ("as shown in
Figure 4.5", "see Table 4.4") and link it to the figure carrying that label.

Only **explicit** references are handled (per ARCHITECTURE_v2 §7); implicit ones
("the diagram above") are out of scope for now. Figures no chunk references are
returned as the orphan list rather than force-mapped.
"""
from __future__ import annotations

from .assemble import find_labels
from .models import Chunk, Figure, ReadingUnit


def map_references(
    chunks: list[Chunk], figures: list[Figure]
) -> tuple[dict[int, list[str]], list[Figure]]:
    """Returns ({chunk index -> [figure labels it references]}, orphan figures)."""
    have = {f.label for f in figures if f.label}
    refs: dict[int, list[str]] = {}
    referenced: set[str] = set()
    for c in chunks:
        hits = [lab for lab in find_labels(c.block.text) if lab in have]
        if hits:
            refs[c.block.index] = hits
            referenced.update(hits)
    orphans = [f for f in figures if not f.label or f.label not in referenced]
    return refs, orphans


def build_reading_sequence(
    chunks: list[Chunk], figures: list[Figure], refs: dict[int, list[str]]
) -> list[ReadingUnit]:
    """Ordered (chunk, [figures]) sequence the TTS walks. Chunks stay in reading
    order; each is paired with the figures its text references (empty if none)."""
    by_label: dict[str, Figure] = {f.label: f for f in figures if f.label}
    units: list[ReadingUnit] = []
    for c in chunks:
        figs = [by_label[lab] for lab in refs.get(c.block.index, []) if lab in by_label]
        units.append(ReadingUnit(c, figs))
    return units
