# Learnible — Architecture & Methodology (v2)

This supersedes [ARCHITECTURE.md](ARCHITECTURE.md) (v1). v1 built the pipeline on
**PyMuPDF geometry heuristics** (paragraph-indent splitting, proximity diagram
clustering, regex caption geometry) plus a **pure-LLM mapping** pass. Testing at
scale (pages 46–82, chapters 4–6) exposed that these heuristics are brittle: code
listings shredded into per-line figures, captions landed on the wrong blocks, and
the LLM mapping orphaned every figure.

v2 replaces the fragile geometry + LLM-mapping layers with a **document layout
detection model** (DocLayout-YOLO) for segmentation and captions, deterministic
**font/regex** post-processing for typing, and **regex explicit-reference
matching** for mapping. The LLM (`qwen3`) is retained only for the one thing it is
actually good at: sub-categorising prose chunks.

---

## 1. Problem & constraints

Unchanged from v1: read the prose aloud, and *verbally cue* the listener to look
at a figure at the right moment — rather than narrating diagrams TTS can't speak.

Hard constraints (from the ideation doc), still honoured:

- **Runs on a GTX 1650 Ti (4 GB VRAM)** — the floor and the dev machine.
- **No server infrastructure** — laptop / free-tier only.
- **KISS** — simplest thing that works; complexity deferred until justified.

New note: DocLayout-YOLO ships as a **CPU** torch build here, so layout detection
adds **no GPU load**. The only GPU step remains the `qwen3` chunk sub-categoriser.

---

## 2. Pipeline overview (v2)

```
PDF + page range
   │
   ▼  ① Splicer            slice the PDF to the requested pages (geometry only)
   │
   ▼  ② Layout detection   DocLayout-YOLO per page → semantic region boxes
   │     (title, plain text, abandon, figure, figure_caption, table,
   │      table_caption, table_footnote, isolate_formula, formula_caption)
   │
   ├─▶ ③ Chunk processing  plain-text + title regions → ordered Chunks
   │        · font probe   → code vs prose
   │        · shading probe → callout (shaded box) → isolated_textbox
   │        · qwen3        → sub-categorise prose (info/reference/exercise/…)
   │
   ├─▶ ④ Figure processing figure≈referable, table≈table, merged code listings;
   │        captions (regex) give each figure its ID/label
   │
   ▼  ⑤ Mapping            regex: find each figure's name in chunk text
   │     (explicit references only; orphans collected, not mapped)
   │
   ▼  output/reading_sequence.json   ordered list the TTS walks
```

The old linebreak/indent paragraph-splitting (v1 §5) is **gone** — YOLO already
emits one region per paragraph/block, so segmentation is a detection output, not
a heuristic we compute.

---

## 3. Stage ① — Splicer

Role shrinks to what it's reliable at: open the PDF, clamp to the requested page
range (CLI arg, 1-based inclusive), and render each page to an image for the
detector (`page.get_pixmap`). No more diagram clustering, caption geometry, or
paragraph splitting — those move to the detector. PyMuPDF stays essential for the
inverse operation: **given a region box, extract the text inside it**
(`page.get_text("text", clip=rect)`), which is how every region gets its text.

---

## 4. Stage ② — Layout detection (DocLayout-YOLO)

**Model:** `DocLayout-YOLO-DocStructBench` (YOLOv10, trained on diverse real docs).
Weights pulled once from HuggingFace; runs on CPU at ~1–3 s/page.

**Class map (the model's 10 native ids):**

| id | class | v2 use |
|----|-------|--------|
| 0 | `title` | Chunk, subcategory **`title`** |
| 1 | `plain text` | Chunk candidate → font/shading probe (§5) |
| 2 | `abandon` | page furniture (headers/footers/page #s) → dropped / `other` |
| 3 | `figure` | Figure, category **`referable`** |
| 4 | `figure_caption` | **label source** — parsed for the figure's ID (§6) |
| 5 | `table` | Figure, category **`table`** |
| 6 | `table_caption` | **label source** for tables |
| 7 | `table_footnote` | attach to the table (minor) |
| 8 | `isolate_formula` | future (math) |
| 9 | `formula_caption` | future (math) |

**Empirically verified on pages 46–82** (see the demo run):

- Callout boxes (TIP/ASIDE/CRUX) are **not** a native class — they come through as
  `plain text`. ⇒ we detect them by **background shading**, not by YOLO or any
  keyword (§5) — a book-agnostic geometric signal.
- Code listings also come through as `plain text`; the **monospace font** signal
  separates them cleanly (§5), so **no custom `code_listing` YOLO class is
  needed** — training one was considered and rejected as effort for a signal we
  already have for free.
- `figure_caption` detection is reliable (12/12 real figures on the range) — this
  is the join key that v1's geometry got wrong.
- `abandon` reliably captures running headers/footers/page numbers — a free fix
  for v1's short-block "heading read aloud" wobble.

Post-processing knobs: `conf`, `imgsz` (1024), `iou`; class ids are remapped into
our taxonomy in code (no retraining). Known edge cases to tie-break later: `figure`
and `table` sometimes both fire on one diagram (take higher conf); shell
transcripts (`prompt> …`) read as mono/code (acceptable — they are referable
listings).

---

## 5. Stage ③ — Chunk processing

Chunks are the primary sequential flow. They are built from the `plain text` and
`title` regions, **kept in reading order top-to-bottom** (and page after page),
and serialised as the ordered list the TTS walks. Region = chunk; no manual
splitting.

**Cross-page stitching.** A paragraph split by a page break (its first half ends
mid-word, e.g. `read-`, and the next page opens lower-case, `ing`) is merged back
into one chunk by `merge_cross_page`: a trailing hyphen is dissolved, otherwise
the halves are space-joined. This runs after assembly, before the LLM step, so
the model sees the whole paragraph. The two halves don't need to be on adjacent
pages -- one or more whole pages of figure/table/callout content (which never
becomes a Chunk) can sit between them and the merge still fires, since figures
never appear in the chunk list the stitcher walks.

**Typing a `plain text` region (deterministic, pre-LLM):**

1. **Monospace font?** → it is **code** (see §6 for the code-listing decision).
2. **Sits on a shaded (non-white) background?** → Chunk subcategory
   **`isolated_textbox`** (a callout/sidebar box). DocLayout-YOLO has no callout
   class and splits a box into `title` + `plain text` fragments; we detect the
   box by sampling its background colour in the rendered page (`_region_shaded`),
   then fuse the consecutive shaded fragments into one box (`_merge_shaded`). This
   is **book-agnostic** — it keys on the near-universal "sidebars are shaded"
   convention, not on this book's `TIP/ASIDE/CRUX` wording. (Bordered-but-unshaded
   callouts would need a border-detection companion — deferred.)
3. Otherwise → **prose**, handed to the LLM.

**LLM sub-categorisation (`qwen3`, grammar-constrained).** Prose chunks are
sub-categorised into `info` / `reference` / `exercise` / `illustrative_example`.
This is the only remaining model step. **CLIP was rejected for this role**: its
text encoder caps at **77 tokens** (paragraphs overflow and truncate) and it
produces retrieval embeddings, not the paragraph-level judgement we need. `qwen3`
reads full paragraphs in an 8K context and is the right tool.

`title` regions become Chunks with subcategory **`title`** (spoken as a heading,
or skippable — a TTS-layer choice).

---

## 6. Stage ④ — Figure processing

`figure` ≈ **referable**, `table` ≈ **table**. Figures exist **only to be
mapped/referenced** — they are never read linearly.

**Code listings (new handling).** A monospace `plain text` region is a code line
or listing. **Consecutive code regions with adjacent bounding boxes are merged**
into a single box representing the whole listing. Then:

- **If a `figure_caption` sits directly below the merged block** → it is a
  **Figure** with category **`code_listing`**, labelled with the caption's ID
  (e.g. `Figure 4.5`). It becomes a referenced figure like any other.
- **If there is no caption** (just illustrative lines of code) → it is a **Chunk**
  with subcategory **`code_listing`**, and its spoken body is replaced by a
  placeholder: **"Refer to the code segment here."** This keeps it **sequentially
  in place** between the surrounding chunks (its position is what matters).
  *Acknowledged grey area:* this is mildly referential, but treating it as an
  inline chunk preserves reading order with far less machinery.

**Labels via regex.** A caption region's text is matched with a regex on
`Fig` / `Figure` / `Table` + number to extract the figure's canonical **name/ID**
(`Figure 6.2`, `Table 4.4`). Captions are supreme: the ID they yield is the join
key for mapping. Association is trivial now — a caption maps to the figure/table
region immediately adjacent to it (same column), not "nearest block anywhere".

**Orphans.** A figure that no chunk references is kept in an **orphan list**, not
force-mapped. Speculative future use: after the main reading, optionally surface
them ("these figures also exist — worth a look"). Not built now.

---

## 7. Stage ⑤ — Mapping (regex, explicit-only)

v1's pure-LLM mapping is **replaced** with deterministic regex matching, now that
captions give reliable figure names:

1. From captions, build the set of canonical figure names/IDs (§6).
2. For each chunk, **regex-scan its text for those names** (`Figure 4.1`,
   `Fig. 6.2`, `Table 4.4`, …).
3. A hit = an **explicit reference** → link that chunk to that figure.

**Scope: explicit references only.** Implicit references ("the diagram above", "as
we can see") are **out of scope for now** — the earlier pure-LLM attempt to catch
them is what orphaned everything. Explicit-only is reliable and sufficient for the
current goal; implicit handling can return later (LLM or otherwise) if needed.

Output: the ordered chunk list, each chunk carrying its referenced figure IDs
(empty for most), plus the separate orphan list.

---

## 8. Data model changes (from v1)

**Chunk subcategories:** `info`, `reference`, `exercise`, `illustrative_example`,
**`title`** *(new)*, **`isolated_textbox`** *(new — callouts)*, **`code_listing`**
*(new — uncaptioned inline code)*, `other`.

**Figure categories:** `referable` (`figure`), `table`, **`code_listing`** *(new —
captioned merged code)*, `decorative`, `other`. **`misc_textbox` is retired** —
callout boxes are now Chunks (`isolated_textbox`), not figures.

The unified index space and the `decorative` (educational-value) vs *orphan*
(unreferenced-outcome) distinction from v1 §3 carry over unchanged.

---

## 9. What changed & why (rationale)

- **Detection over heuristics.** A layout model gives semantic regions (esp.
  captions) that v1's indent/proximity geometry approximated badly at scale.
- **Font/shading probes over a trained class.** Code (mono) and callouts (shaded)
  are exactly detectable deterministically — cheaper and more reliable than
  training a YOLO class or asking the LLM.
- **Regex mapping over LLM mapping.** With trustworthy caption IDs, explicit
  references are a solved problem; the LLM added nondeterminism and orphaned
  everything. Scope to explicit now; revisit implicit later.
- **LLM kept only for prose sub-categorisation.** The one genuinely fuzzy call.
- **CLIP rejected.** 77-token limit + retrieval-only embeddings; wrong tool.

---

## 10. Deferred / future

- Implicit-reference mapping (currently explicit-only).
- Orphan-figure surfacing after the main reading.
- Active-figure announcement de-duplication (TTS layer — v1 §9 algorithm still
  applies: announce `B \ A`, then `A = B`).
- Math (`isolate_formula` / `formula_caption` classes) — MathML / rendered.
- Multi-column layouts; generalising past the single test PDF.
- Possible custom `code_listing` YOLO class — only if font detection ever proves
  unreliable across other books.
```
