"""Data structures shared by the splicer and the classifier.

Layers:
  * Splicer output  -> raw candidates (TextBlock, FigureCandidate, SplicedDocument)
  * Classifier I/O  -> Pydantic schemas the model fills in (structured outputs)
  * Final results   -> Chunk, Figure

Key design point: in real textbooks most "figures" (code listings, tables,
callout/TIP boxes) are *text*, not raster images. So every text block is first
classified into a unified BlockKind; chunk-kinds become Chunks and figure-kinds
become (text-backed) Figures. Only genuine vector diagrams / raster images are
detected geometrically by the splicer and classified separately.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

# A bounding box on a page: (x0, y0, x1, y1) in PDF points, origin top-left.
BBox = tuple[float, float, float, float]


# --------------------------------------------------------------------------- #
# Final categories (from the ideation doc; "other" is the reserved catch-all)
# --------------------------------------------------------------------------- #
class ChunkCategory(str, Enum):
    info = "info"                                  # regular explanatory prose
    reference = "reference"                        # citations, footnotes, biblio
    exercise = "exercise"                          # questions / problem sets
    illustrative_example = "illustrative_example"  # solved / worked examples
    # v2 additions ...
    title = "title"                                # a section heading (its own unit)
    isolated_textbox = "isolated_textbox"          # TIP / ASIDE / CRUX callout box
    code_listing = "code_listing"                  # inline, un-captioned code sample
    other = "other"                                # furniture / catch-all


class FigureCategory(str, Enum):
    referable = "referable"        # figure/diagram a chunk points the eye to
    table = "table"               # tabular data
    code_listing = "code_listing"  # v2: a captioned code listing (a real figure)
    misc_textbox = "misc_textbox"  # DEPRECATED (v1): callouts are Chunks in v2
    decorative = "decorative"      # a real figure with no essential educational use
    other = "other"               # reserved for new cases


# --------------------------------------------------------------------------- #
# Unified kind for a single text block (what the model decides per block)
# --------------------------------------------------------------------------- #
class BlockKind(str, Enum):
    # chunk kinds (read linearly by the TTS) ...
    info = "info"
    reference = "reference"
    exercise = "exercise"
    illustrative_example = "illustrative_example"
    # figure kinds (referenced, not read linearly) ...
    code = "code"          # code listing / program text -> referable
    table = "table"        # tabular data
    callout = "callout"    # TIP / ASIDE / sidebar / summary box -> misc_textbox
    # structural / skip ...
    other = "other"        # headings, captions, page numbers, running headers


# How each BlockKind routes into the two output streams.
BLOCK_TO_CHUNK = {
    BlockKind.info: ChunkCategory.info,
    BlockKind.reference: ChunkCategory.reference,
    BlockKind.exercise: ChunkCategory.exercise,
    BlockKind.illustrative_example: ChunkCategory.illustrative_example,
    BlockKind.other: ChunkCategory.other,
}
BLOCK_TO_FIGURE = {
    BlockKind.code: FigureCategory.referable,
    BlockKind.table: FigureCategory.table,
    BlockKind.callout: FigureCategory.misc_textbox,
}


# --------------------------------------------------------------------------- #
# Splicer output: raw candidates with layout info, no semantics yet
# --------------------------------------------------------------------------- #
@dataclass
class TextBlock:
    """A contiguous run of text the splicer pulled off a page."""
    page: int           # 1-based page number in the original PDF
    index: int          # stable id within the spliced run (reading order)
    bbox: BBox
    text: str
    font_size: float    # dominant font size, a weak layout hint
    bold: bool
    mono: bool          # dominant font is monospace (strong code signal)


@dataclass
class FigureCandidate:
    """A non-text visual element (raster image or vector-diagram cluster)."""
    page: int
    index: int
    bbox: BBox
    kind: str           # detection hint: "image" | "diagram"
    nearby_text: str = ""              # caption text near the element
    label: Optional[str] = None        # parsed caption label, e.g. "Figure 4.2"
    table_rows: Optional[list[list[Optional[str]]]] = None


@dataclass
class SplicedDocument:
    pdf_path: str
    page_start: int
    page_end: int
    text_blocks: list[TextBlock] = field(default_factory=list)
    visual_figures: list[FigureCandidate] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# Layout detection output (v2): one semantic region per DocLayout-YOLO box
# --------------------------------------------------------------------------- #
@dataclass
class Region:
    """A single DocLayout-YOLO detection: a semantic region on a page.

    `cls` is the model's class name (e.g. "plain text", "figure",
    "figure_caption", "title", "abandon", "table"). `text` is the PDF text found
    inside the box (empty for pure-image regions). `mono` flags a monospace body,
    the strong code signal. Boxes are in PDF points; `index` is the reading-order
    id within the spliced run.
    """
    page: int           # 1-based page number in the original PDF
    index: int          # stable id within the spliced run (reading order)
    bbox: BBox
    cls: str            # YOLO class name
    confidence: float
    text: str = ""
    mono: bool = False
    shaded: bool = False  # sits on a non-white background -> a callout/sidebar box


# --------------------------------------------------------------------------- #
# Classifier structured-output schemas (what the model returns)
# --------------------------------------------------------------------------- #
class BlockLabel(BaseModel):
    index: int = Field(description="Index of the text block being classified.")
    kind: BlockKind
    confidence: float = Field(description="0.0-1.0 confidence in the kind.")
    reason: str = Field(description="One short phrase justifying the kind.")


class BlockLabelBatch(BaseModel):
    labels: list[BlockLabel]


class FigureLabel(BaseModel):
    index: int = Field(description="Index of the visual figure candidate.")
    category: FigureCategory
    label: Optional[str] = Field(
        default=None,
        description="Reference label if present in the caption, e.g. 'Figure 7.2' "
        "or 'Table 1.1'. Null if none.",
    )
    confidence: float = Field(description="0.0-1.0 confidence in the category.")
    reason: str = Field(description="One short phrase justifying the category.")


class FigureLabelBatch(BaseModel):
    labels: list[FigureLabel]


class ChunkRefs(BaseModel):
    index: int = Field(description="Index of the chunk (text passage).")
    figure_indices: list[int] = Field(
        default_factory=list,
        description="Indices of figures this chunk tells the reader to look at; "
        "empty if it references none.",
    )
    reason: str = Field(description="Which reference(s), or 'none'.")


class ChunkRefsBatch(BaseModel):
    refs: list[ChunkRefs]


# --------------------------------------------------------------------------- #
# Final classified results
# --------------------------------------------------------------------------- #
@dataclass
class Chunk:
    block: TextBlock
    category: ChunkCategory
    confidence: float
    reason: str


@dataclass
class Figure:
    candidate: FigureCandidate
    category: FigureCategory
    label: Optional[str]
    confidence: float
    reason: str
    # Where it came from: "text" (a classified text block) or "visual".
    source: str = "visual"


@dataclass
class ReadingUnit:
    """One step in TTS playback: a chunk paired with the figures it references.

    An ordered list of these is the Step-4 output the TTS layer walks; a chunk's
    `figures` list is empty when it references none.
    """
    chunk: Chunk
    figures: list[Figure] = field(default_factory=list)
