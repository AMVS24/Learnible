"""Stage 3b (v2): sub-categorise prose chunks with qwen3.

The assembler types everything it can deterministically (titles, callouts, code,
figures). What remains is ordinary prose, tagged `PENDING_SUBCAT`. This is the
one genuinely fuzzy call, so it goes to the local model: label each prose chunk
`info` / `reference` / `exercise` / `illustrative_example`.

Grammar-constrained JSON (via Ollama's `format`) guarantees a valid, in-vocabulary
answer even from a 4B model. This is the only GPU step in the pipeline.
"""
from __future__ import annotations

import json
from collections import defaultdict
from enum import Enum

import ollama
from pydantic import BaseModel, Field

from . import config
from .assemble import PENDING_SUBCAT
from .models import Chunk, ChunkCategory

_MAX_CHARS = 700


class _ProseCat(str, Enum):
    info = "info"
    reference = "reference"
    exercise = "exercise"
    illustrative_example = "illustrative_example"


class _ProseLabel(BaseModel):
    index: int = Field(description="Index of the passage being labelled.")
    category: _ProseCat
    confidence: float = Field(description="0.0-1.0 confidence.")
    reason: str = Field(description="One short phrase justifying the category.")


class _ProseBatch(BaseModel):
    labels: list[_ProseLabel]


_SYSTEM = """\
You sub-categorise a passage of textbook prose for a text-to-speech reader. Choose \
exactly one category per passage. Judge the passage as a WHOLE by what it *is*, not \
by isolated words it happens to contain. When unsure, choose info.

- info: ordinary explanatory prose. This is the DEFAULT and by far the most common \
case. Explanatory text stays info even if it contains an inline citation like \
"[CK+08]", asks a rhetorical question, or mentions an example in passing.

- reference: the passage IS a standalone bibliography / citation entry -- e.g. it \
begins with a cite key and title such as `[SR05] "Advanced Programming in the UNIX \
Environment"` followed by authors/venue/year. A normal sentence that merely cites a \
source inline (".. in the xv6 kernel [CK+08].") is NOT reference -- it is info.

- exercise: the passage ASKS THE READER TO DO a concrete task -- run a program, \
write code, measure something, answer a numbered homework question. A rhetorical or \
thought-provoking question inside explanation (".. how does the OS do this?") is NOT \
an exercise -- it is info.

- illustrative_example: a worked/solved example walked through step by step (e.g. \
"In this example (p2.c), the parent calls wait() .. the output is ..").

Echo each passage's index."""


class Subcategorizer:
    def __init__(self, model: str = config.MODEL) -> None:
        self.client = ollama.Client(host=config.OLLAMA_HOST)
        self.model = model

    def run(self, chunks: list[Chunk]) -> None:
        """Refine every `PENDING_SUBCAT` prose chunk in place. Chunks the model
        drops keep their provisional `info` label so nothing leaves the flow."""
        prose = [c for c in chunks if c.reason == PENDING_SUBCAT]
        if not prose:
            return
        by_index = {c.block.index: c for c in prose}
        by_page: dict[int, list[Chunk]] = defaultdict(list)
        for c in prose:
            by_page[c.block.page].append(c)

        for page in sorted(by_page):
            passages = [
                {"index": c.block.index, "text": c.block.text[:_MAX_CHARS]}
                for c in by_page[page]
            ]
            batch = self._call(
                _SYSTEM,
                f"Passages from page {page}:\n"
                + json.dumps(passages, ensure_ascii=False, indent=2),
            )
            if batch is None:
                continue
            for lab in batch.labels:
                c = by_index.get(lab.index)
                if c is not None:
                    c.category = ChunkCategory(lab.category.value)
                    c.confidence = lab.confidence
                    c.reason = lab.reason

    def _call(self, system: str, user: str) -> _ProseBatch | None:
        try:
            resp = self.client.chat(
                model=self.model,
                messages=[{"role": "system", "content": system},
                          {"role": "user", "content": user}],
                format=_ProseBatch.model_json_schema(),
                options={"temperature": 0, "num_ctx": 8192},
                think=False,
            )
        except ollama.ResponseError:
            return None
        try:
            return _ProseBatch.model_validate_json(resp["message"]["content"])
        except Exception:
            return None
