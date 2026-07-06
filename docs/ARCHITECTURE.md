# Learnible — Architecture & Methodology

This document explains *how* the prototype works and *why* it is built this way.
For usage see the [README](../README.md); for the original product brief see
`textbook tts ideation.pdf`.

---

## 1. Problem & constraints

Simple TTS of a textbook fails on two fronts: it narrates diagrams it cannot
speak, and it has no sense of content structure (prose vs. exercise vs. callout).
The goal is an audio experience that reads the prose and *verbally cues* the
listener to look at a figure at the right moment.

Hard constraints carried from the ideation doc, and honoured throughout:

- **Runs on a GTX 1650 Ti (4 GB VRAM)** — the floor, and the dev machine.
- **No server infrastructure** — a laptop or free-tier cloud only.
- **KISS** — the simplest thing that works first; complexity is deferred until a
  concrete result justifies it.

These constraints drive the two biggest design choices: a **small local model**
(§4) and a **text-first** view of figures (§3).

---

## 2. Pipeline overview

The ideation doc defines six steps. Current status:

| Step | Description | Status |
|------|-------------|--------|
| 1 | PDF splice + content extraction | ✅ `src/splicer.py` |
| 2 | Classify text → Chunks | ✅ `src/classifier.py` |
| 3 | Classify visuals → Figures | ✅ `src/classifier.py` |
| 4 | Chunk → Figure mapping | ⬜ next |
| 5 | TTS sequence data structure | 🟡 designed (`ReadingUnit` list) |
| 6 | TTS → MP3 | ⬜ future |

Data flows one way: `splice()` produces a `SplicedDocument` of raw candidates
with **no semantics**; the classifier assigns categories; `main.py` serialises
the result. Keeping extraction (geometry) and classification (meaning) in
separate layers is deliberate — each can be audited and fixed independently, and
the audit showed the two failure modes live in different layers.

---

## 3. Data model (`src/models.py`)

Three layers of types:

**Splicer output (raw candidates, no meaning yet)**
- `TextBlock(page, index, bbox, text, font_size, bold, mono)` — one *paragraph*
  of text plus weak layout hints.
- `FigureCandidate(page, index, bbox, kind, nearby_text, label)` — a non-text
  element; `kind` is a detection hint (`"image"` / `"diagram"`), `label` is a
  regex-parsed caption label when available.
- `SplicedDocument(pdf_path, page_start, page_end, text_blocks, visual_figures)`.

**Classifier I/O (Pydantic schemas the model fills)**
- `BlockLabel{index, kind, confidence, reason}` → `BlockLabelBatch`.
- `FigureLabel{index, category, label, confidence, reason}` → `FigureLabelBatch`.

**Final results**
- `Chunk(block, category, confidence, reason)` — read linearly by the TTS.
- `Figure(candidate, category, label, confidence, reason, source)` — referenced,
  not read; `source` is `"text"` (a classified text block) or `"visual"`.

**Categories**
- `ChunkCategory`: `info`, `reference`, `exercise`, `illustrative_example`, `other`.
- `FigureCategory`: `referable`, `table`, `misc_textbox`, `decorative`, `other`.
  `decorative` = a genuine figure with **no essential educational value** (a
  classification judgment), distinct from an *orphan*, which is any figure no
  chunk references (a mapping outcome — see §9).
- `BlockKind` (what the model picks per text block): the chunk kinds **plus**
  `code`, `table`, `callout` (the figure-kinds) and `other`.

**Routing.** `BLOCK_TO_CHUNK` / `BLOCK_TO_FIGURE` map a `BlockKind` into one of
the two output streams: `code→referable`, `table→table`, `callout→misc_textbox`
become Figures; everything else becomes a Chunk. This is the mechanism that lets
a *text* block become a "look at the screen" Figure (§3 key idea).

**Unified index space.** Every candidate on a page — text block *or* visual
figure — draws from one shared `idx` counter, so indices are globally unique.
This matters for Step 4, which will join Chunks to Figures by index/label.

---

## 4. Model choice & structured output

**Why a small local model.** The classification is trivial (bucket a block, pull
a label). Given the 4 GB-VRAM floor and "no server", a hosted API is unnecessary
and a large model is overkill. `qwen3:4b` via **Ollama** is free, keyless, fits
in VRAM with headroom, and has the most reliable structured-output behaviour in
its size class. `qwen3:1.7b` is the lighter fallback.

**Grammar-constrained JSON.** Small models left to free-form prompting emit
almost-valid JSON that breaks parsers. Instead each call passes the Pydantic
schema as Ollama's `format`, which compiles it into a grammar (GBNF) and
constrains generation token-by-token. Output is therefore *always* valid and can
never contain an out-of-vocabulary category — the model only chooses *content*,
never *shape*. Reasoning ("thinking") is disabled (`think=False`): unnecessary
for this task and the grammar forces a JSON-only reply anyway.

Calls are **batched per page** (one request per page, temperature 0). A refusal
or a validation failure returns `None`; any block the model drops falls back to
`other` and stays in the reading flow rather than vanishing.

---

## 5. Stage 1 — Splicer (`src/splicer.py`)

Pure PyMuPDF geometry. Per page:

**Font hints.** For each text block a dominant font size, and boolean `bold` /
`mono` flags. `mono` also checks font-name fragments (e.g. `nimbusmon`, `cmtt`)
because the mono flag bit is often absent on embedded monospace faces.

**Paragraph splitting.** A textbook "block" from PyMuPDF often merges several
paragraphs. TTS wants paragraph-sized units, so each block is split. The boundary
is *not* the raw `\n` (every wrapped line has one) but a **departure from the
block's dominant left margin**: a first-line indent (prose) or a hanging bullet
(list item) both show up as an outlier `x0`. Guards keep the split honest:
- monospace (code) blocks are never split;
- callout/aside boxes (`TIP:` / `ASIDE:` / `CRUX` / `NOTE:` / `WARNING`) are kept
  whole;
- centered text (headers/footers) — where few lines share the dominant margin —
  is kept whole, preventing "THREE / EASY / PIECES" over-splitting.

**Diagram detection (multi-cluster).** `page.get_drawings()` gives vector-path
rects. Full-width thin rules (running-head/footer lines) are filtered out. The
rest are **clustered by proximity** (`_DIAGRAM_GAP = 30 pt`); a cluster is a
diagram if it has ≥4 paths and covers 2–85 % of the page. Clustering (rather than
unioning *all* paths) stops a diagram from merging with an unrelated ruled table
lower on the page — the bug that previously swallowed a figure's caption.

**Internal-text suppression.** Text whose bbox is ≥60 % inside a (padded)
diagram region is a figure label ("Memory", "Running") and is dropped from the
reading flow — it belongs to the figure, not the prose. Captions sit just outside
the padded region and survive.

**Caption & label.** For each visual element, the nearest horizontally-overlapping
text block below (else above) is its caption. A real `Figure N` / `Table N`
caption within ~60 pt is preferred, and its label is parsed deterministically by
regex (`_CAPTION_RE`). This gives diagrams reliable labels without asking the
model.

---

## 6. Stage 2–3 — Classifier (`src/classifier.py`)

- `classify_text_blocks` labels every text block with a `BlockKind`, then routes
  chunk-kinds to `Chunk`s and figure-kinds to text-backed `Figure`s.
- `classify_figures` confirms a category for each visual candidate and echoes a
  label; the **deterministic** splicer label is preferred over the model's
  (`cand.label or lab.label`).

The system prompts describe the categories and tell the model to use the
`mono/bold/font_size` hints as weak signals and judge mainly by the text.

---

## 7. Design decisions (rationale)

- **Extraction vs. classification split.** Geometry errors and model errors are
  independent; separating them made the audit tractable and localised each fix.
- **Text-first figures.** Most textbook "figures" are text (code/tables/boxes);
  treating them as text blocks the classifier can *read* is more robust than
  trying to detect them geometrically. Geometry is reserved for true diagrams.
- **Deterministic labels over the model.** `Figure 4.2` is a pure pattern; regex
  is exact and free, so labels don't depend on model whim.
- **Indent, not newline, as the paragraph boundary.** Reflects how the PDF
  actually encodes paragraphs; newline-splitting would shatter every wrapped line.
- **Grammar-constrained output.** Trades a little model freedom for a guarantee of
  parseable, in-vocabulary results — essential for a 4 B model.

---

## 8. Known limitations & deferred work

- **Text-figure labels.** Code/table captions are separate blocks; associating
  them with their figures is part of the mapping phase (§9), not yet built.
- **Touching diagrams** still merge (proximity clustering).
- **Short-block classification wobble.** Headings / running headers / lone
  captions occasionally land in `info`; body prose is reliable. A deterministic
  guard (section-number regex, all-caps header, `Figure N:` caption → `other`) is
  a candidate cleanup that avoids touching the model.
- **Single-column assumption.** Multi-column layouts and math are open questions
  from the ideation doc.

The latest empirical picture is always in `output/classification_audit.md`.

---

## 9. Step 4 — Chunk → Figure mapping (design)

Links each Chunk to the Figures it references, producing an ordered
`list[ReadingUnit]` where `ReadingUnit = (chunk, [figures])`. Settled decisions:

- **Approach: pure LLM (Option A).** For each Chunk, the model is given the chunk
  text and the catalogue of available Figures (label + caption + category) and
  returns the figure indices the chunk refers to. Rationale: research papers use
  regular "as shown in Fig. N" phrasing, but textbooks reference figures
  implicitly and irregularly ("the diagram above", "as we can see"), so a
  regex/hybrid layer would add real complexity for little gain.
- **Scope: the whole splice.** A chunk may reference any figure in the range,
  including cross-page ("recall Figure 6.1"), not just its own page.
- **Prerequisite: text-figure labels.** Diagrams already carry regex labels;
  code/table captions are separate blocks, so a deterministic caption→figure
  association pass must run first — labels are the join key.
- **Orphans stay orphans.** A figure no chunk references is left unmapped; there
  is **no** snapping to the nearest chunk. Orphans are expected and legitimate.
- **`decorative` vs. orphan** (§3): *decorative* is about educational value (a
  classification), *orphan* is about being unreferenced (a mapping outcome). Most
  decorative figures are orphans, but a decorative figure could be referenced, and
  an essential figure could be orphaned by an implicit reference the model missed.

### Deferred post-processing: active-figure de-duplication

When several *consecutive* chunks reference the same figure, the TTS should
announce it once, not every time. A streaming pass over the `ReadingUnit`
sequence maintains a set `A` of currently-active figures:

```
A = {}                       # active figures
for each ReadingUnit with figure set B:
    announce = B \ A         # newly-referenced figures — spoken before this chunk
    A        = B             # new active set, since (A ∩ B) ∪ B == B
```

So a figure referenced by chunks 5–8 in a row is announced only at chunk 5. This
belongs to the **TTS / sequencing layer, after** classification + mapping, and is
**not built yet** (tracked in [TODO.md](TODO.md)). The plain ordered list is the
correct structure for this linear pass — no exotic data structure is needed;
a smarter DS may be revisited only if a concrete need appears.
