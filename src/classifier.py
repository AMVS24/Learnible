"""Steps 2 & 3: Content classification via a small local model (Ollama).

  * classify_text_blocks -> assigns every text block a BlockKind, then routes
        chunk-kinds  -> Chunks   (read linearly)
        figure-kinds -> Figures  (code listings, tables, callout boxes)
  * classify_figures    -> confirms category + pulls a label for visual figures
        (raster images, vector diagrams)

Each page is one batched, structured-output model call.
"""
from __future__ import annotations

import json
from collections import defaultdict

import ollama
from pydantic import ValidationError

from . import config
from .models import (
    BLOCK_TO_CHUNK,
    BLOCK_TO_FIGURE,
    BlockKind,
    BlockLabelBatch,
    Chunk,
    ChunkCategory,
    ChunkRefsBatch,
    Figure,
    FigureCandidate,
    FigureCategory,
    FigureLabelBatch,
    TextBlock,
)

_MAX_BLOCK_CHARS = 700

_BLOCK_SYSTEM = """\
You label text blocks extracted from a textbook page so a text-to-speech reader \
knows how to handle each one. Pick exactly one kind per block:

Read-aloud content:
- info: regular explanatory prose, the main body the reader listens to.
- reference: in-text citations, footnotes, bibliography entries.
- exercise: questions, problems, or homework prompts.
- illustrative_example: a worked or solved example / step-by-step demonstration.

Look-at-the-screen content (NOT read linearly):
- code: a code listing or program text (often monospaced).
- table: tabular data arranged in rows and columns.
- callout: a TIP, ASIDE, NOTE, CRUX, sidebar, or summary box set apart from the \
main flow.

Structural:
- other: headings, figure/table captions, page numbers, running headers/footers.

Use the mono / bold / font_size hints as weak signals; judge mainly by the text. \
Return one label per block, echoing its index, with a few-word reason."""

_FIGURE_SYSTEM = """\
You classify visual elements (raster images or vector diagrams) extracted from a \
textbook page, using the detection hint and nearby caption text. Categories:

- referable: a figure, diagram, illustration, or chart the prose tells the reader \
to look at; essential to understanding.
- table: a rendered table.
- misc_textbox: a boxed callout / sidebar / summary.
- decorative: a genuine image/figure with NO essential educational use — e.g. a \
chapter-opener illustration or ornamental graphic the reader need not study.
- other: page furniture that is not a figure at all — rules, logos, headers/footers.

If the nearby text contains a label like "Figure 7.2" or "Table 1.1", return it in \
the label field; otherwise null. One label per element, echoing its index, with a \
few-word reason."""

_MAP_SYSTEM = """\
You link a textbook passage to the figures it directs the reader to look at, so a \
text-to-speech reader can insert a "look at Figure X" cue at the right moment.

You are given a catalogue of figures (each with an index, label, kind, and nearby \
caption) and a batch of passages. For each passage, return the indices of the \
figures it refers to. References may be:
- explicit -- "as shown in Figure 4.2", "see the table below", or
- implicit -- "the diagram above", "as we can see", "the following code".

Only use indices that appear in the catalogue. Most passages refer to no figure -- \
return an empty list for those. Do not invent a reference for a passage that merely \
discusses a topic without pointing the reader at a specific figure. Echo each \
passage's index."""


class Classifier:
    def __init__(self, model: str = config.MODEL):
        # Talk to the local Ollama server (no API key needed). Structured output
        # is enforced by handing each Pydantic model's JSON schema to Ollama as
        # `format`, which it compiles into a grammar so generation can't stray
        # from the shape we want.
        self.client = ollama.Client(host=config.OLLAMA_HOST)
        self.model = model

    # --------------------------------------------------------------- text blocks
    def classify_text_blocks(
        self, blocks: list[TextBlock]
    ) -> tuple[list[Chunk], list[Figure]]:
        by_page: dict[int, list[TextBlock]] = defaultdict(list)
        for b in blocks:
            by_page[b.page].append(b)
        by_index = {b.index: b for b in blocks}

        chunks: list[Chunk] = []
        text_figures: list[Figure] = []

        for page in sorted(by_page):
            page_blocks = by_page[page]
            payload = [
                {
                    "index": b.index,
                    "mono": b.mono,
                    "bold": b.bold,
                    "font_size": b.font_size,
                    "text": b.text[:_MAX_BLOCK_CHARS],
                }
                for b in page_blocks
            ]
            batch = self._call(
                _BLOCK_SYSTEM,
                f"Label these {len(payload)} text blocks from page {page}:\n"
                + json.dumps(payload, ensure_ascii=False, indent=2),
                BlockLabelBatch,
            )

            seen = set()
            if batch is not None:
                for lab in batch.labels:
                    block = by_index.get(lab.index)
                    if block is None or lab.index in seen:
                        continue
                    seen.add(lab.index)
                    self._route(block, lab.kind, lab.confidence, lab.reason,
                                chunks, text_figures)
            # Anything the model dropped stays in the linear flow as 'other'.
            for b in page_blocks:
                if b.index not in seen:
                    chunks.append(Chunk(b, ChunkCategory.other, 0.0, "unclassified"))

        chunks.sort(key=lambda c: c.block.index)
        text_figures.sort(key=lambda f: f.candidate.index)
        return chunks, text_figures

    @staticmethod
    def _route(block, kind, confidence, reason, chunks, text_figures):
        if kind in BLOCK_TO_FIGURE:
            cand = FigureCandidate(
                page=block.page, index=block.index, bbox=block.bbox,
                kind=kind.value, nearby_text=block.text[:_MAX_BLOCK_CHARS],
            )
            text_figures.append(
                Figure(cand, BLOCK_TO_FIGURE[kind], None, confidence, reason,
                       source="text")
            )
        else:
            chunks.append(
                Chunk(block, BLOCK_TO_CHUNK.get(kind, ChunkCategory.other),
                      confidence, reason)
            )

    # ------------------------------------------------------------ visual figures
    def classify_figures(self, candidates: list[FigureCandidate]) -> list[Figure]:
        by_page: dict[int, list[FigureCandidate]] = defaultdict(list)
        for c in candidates:
            by_page[c.page].append(c)
        by_index = {c.index: c for c in candidates}

        figures: list[Figure] = []
        for page in sorted(by_page):
            page_figs = by_page[page]
            payload = [
                {
                    "index": c.index,
                    "detection_hint": c.kind,
                    "label": c.label,
                    "nearby_text": c.nearby_text[:_MAX_BLOCK_CHARS],
                }
                for c in page_figs
            ]
            batch = self._call(
                _FIGURE_SYSTEM,
                f"Classify these {len(payload)} visual elements from page {page}:\n"
                + json.dumps(payload, ensure_ascii=False, indent=2),
                FigureLabelBatch,
            )
            seen = set()
            if batch is not None:
                for lab in batch.labels:
                    cand = by_index.get(lab.index)
                    if cand is None or lab.index in seen:
                        continue
                    seen.add(lab.index)
                    figures.append(
                        Figure(cand, lab.category, cand.label or lab.label,
                               lab.confidence, lab.reason, source="visual")
                    )
            for c in page_figs:
                if c.index not in seen:
                    fallback = (FigureCategory.referable if c.kind in ("image", "diagram")
                                else FigureCategory.other)
                    figures.append(Figure(c, fallback, c.label, 0.0, "unclassified",
                                          source="visual"))

        figures.sort(key=lambda f: f.candidate.index)
        return figures

    # ------------------------------------------------------ chunk -> figure mapping
    _READ_ALOUD = {
        ChunkCategory.info, ChunkCategory.reference,
        ChunkCategory.exercise, ChunkCategory.illustrative_example,
    }

    def map_chunk_references(
        self, chunks: list[Chunk], figures: list[Figure]
    ) -> dict[int, list[int]]:
        """Step 4 (Option A): for each read-aloud chunk, infer which figures it
        refers to. Returns {chunk_index -> [figure_index, ...]}.

        Only read-aloud chunks (info/reference/exercise/example) are sent to the
        model -- headings/footers/captions can't reference anything. The whole
        figure catalogue is offered to every batch so cross-page references work.
        """
        if not figures:
            return {}
        # Keep the catalogue compact -- it is resent on every page call. The
        # label is the join key; a short caption is enough context (never the
        # figure's full text, which for code would be huge).
        catalogue = [
            {
                "index": f.candidate.index,
                "label": f.label,
                "kind": f.category.value,
                "caption": " ".join(f.candidate.nearby_text.split())[:60],
            }
            for f in figures
        ]
        valid = {f.candidate.index for f in figures}

        by_page: dict[int, list[Chunk]] = defaultdict(list)
        for c in chunks:
            if c.category in self._READ_ALOUD:
                by_page[c.block.page].append(c)

        refs: dict[int, list[int]] = {}
        # --- mapping diagnostics (temporary): tell apart the three failure modes
        #   pages_failed  -> calls erroring out (context overflow etc.)  [H1]
        #   raw_total==0  -> model returns no references at all           [H2]
        #   raw_total>0 but kept_total==0 -> model uses wrong index space [H3]
        pages_ok = pages_failed = raw_total = kept_total = 0
        samples: list[str] = []
        for page in sorted(by_page):
            passages = [
                {"index": c.block.index, "text": c.block.text[:_MAX_BLOCK_CHARS]}
                for c in by_page[page]
            ]
            try:
                batch = self._call(
                    _MAP_SYSTEM,
                    "Figure catalogue (the only figures that exist):\n"
                    + json.dumps(catalogue, ensure_ascii=False, indent=2)
                    + f"\n\nPassages from page {page}:\n"
                    + json.dumps(passages, ensure_ascii=False, indent=2),
                    ChunkRefsBatch,
                )
            except ollama.ResponseError as e:
                # One page failing (e.g. context overflow) shouldn't abort the
                # whole mapping -- skip it and keep going.
                pages_failed += 1
                if len(samples) < 6:
                    samples.append(f"  p{page}: ResponseError {e}")
                continue
            if batch is None:
                pages_failed += 1
                continue
            pages_ok += 1
            for r in batch.refs:
                kept = [i for i in r.figure_indices if i in valid]
                raw_total += len(r.figure_indices)
                kept_total += len(kept)
                # capture the first few non-empty model answers to inspect the
                # index space the model actually used (real vs. ordinal)
                if r.figure_indices and len(samples) < 6:
                    samples.append(
                        f"  chunk#{r.index}: model={r.figure_indices} kept={kept} "
                        f"reason={r.reason!r}"
                    )
                refs[r.index] = kept
        print(
            f"  [map diag] pages ok={pages_ok} failed={pages_failed} | "
            f"model refs raw={raw_total} kept-after-filter={kept_total} | "
            f"valid figure indices e.g. {sorted(valid)[:8]}"
        )
        for s in samples:
            print(s)
        return refs

    # --------------------------------------------------------------------- internal
    def _call(self, system: str, user: str, schema):
        """One grammar-constrained Ollama call; returns the parsed model or None.

        Passing ``format=schema.model_json_schema()`` constrains generation to
        valid JSON matching the schema, so even a small model cannot emit
        malformed output or an out-of-vocabulary category.
        """
        kwargs = dict(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            format=schema.model_json_schema(),
            options={"temperature": 0, "num_ctx": 8192},
        )
        # Skip Qwen3's "thinking" pass -- this labeling is trivial and the grammar
        # already forces a JSON-only reply. Fall back for models / client
        # versions that don't accept the think toggle.
        try:
            resp = self.client.chat(think=False, **kwargs)
        except (TypeError, ollama.ResponseError):
            resp = self.client.chat(**kwargs)
        try:
            return schema.model_validate_json(resp.message.content)
        except ValidationError:
            return None
