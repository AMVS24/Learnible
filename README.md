# Learnible — Textbook TTS + Figure Referencer (prototype)

An Audible-style reader for **textbooks**: it reads the prose aloud and tells the
listener when to *"look at Figure X"* instead of trying to narrate diagrams it
can't speak.

**Built so far:** Step 1 (Splice) and Steps 2–3 (Classify). The Chunk→Figure
**mapping** (Step 4) is next. Full design rationale lives in
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Pipeline

```
PDF + page range
      │
      ▼  src/splicer.py    — geometry only, no semantics
  SplicedDocument
    ├─ text_blocks     one per paragraph (indent-aware split); font hints (size/bold/mono)
    └─ visual_figures  raster images + clustered vector diagrams + caption & parsed label
      │
      ▼  src/classifier.py  — qwen3:4b via Ollama, grammar-constrained JSON
    ├─ classify_text_blocks → Chunks (info / reference / exercise / illustrative_example)
    │                          + text Figures (code→referable, table, callout→misc_textbox)
    └─ classify_figures     → visual Figures (referable / table / misc_textbox / decorative)
      │
      ▼  src/main.py
  output/spliced.pdf, output/classified.json, console summary
```

**Key idea:** in real textbooks most "figures" (code listings, tables, TIP/ASIDE
boxes) are *text*, not raster images — so the text classifier decides whether a
block is read linearly (a **Chunk**) or referenced (a **Figure**). Geometry is
reserved for genuine vector diagrams and raster images, which the text model
can't see.

## Setup

```bash
# 1. install Ollama from https://ollama.com/download (local model server)
# 2. in a fresh Python 3.11 env:
python setup_env.py     # PyTorch for your GPU/CPU, requirements.txt,
                        # chatterbox-tts, the models in ollama-models.txt,
                        # and the web app's npm packages

python -m src.chapters scan                    # list chapters
python -m src.chapters --book toc queue        # render a book's unit queue
```

Everything runs locally — no API key or `.env`. The Qwen 4B prose
sub-categorisation step is off for now (`config.SUBCATEGORIZE`; `--llm` to run
it), so only the models in `ollama-models.txt` are needed.

## Config

Everything hardcoded "for now" lives in `src/config.py`: the test PDF
(`Operating Systems - Three Easy Pieces.pdf`), the page range (46–54, 1-based
inclusive), the model (`qwen3:4b`) and the Ollama host, and the output dir.

## Output

- `output/spliced.pdf` — the extracted page range.
- `output/classified.json` — every Chunk and Figure with category, confidence,
  bbox, text, and a parsed label.
- `output/mapping.json` — the ordered `ReadingUnit` sequence: each chunk paired
  with the figures it references (Step 4).
- `output/classification_audit.md` — the latest ground-truth review of a run.

## Known limitations / deferred to the mapping phase

- **Text-figure labels.** Diagrams get a deterministic label (regex on the
  nearby caption). Code/table captions are *separate* text blocks, so associating
  their labels happens in the mapping phase — not yet done.
- **Touching diagrams.** Vector paths are clustered by proximity, so a page can
  carry several diagrams; but two diagrams that physically touch still merge.
- **Unruled tables** rely entirely on the classifier — PyMuPDF `find_tables`
  doesn't detect them in this book.
- **Short-block wobble.** The model occasionally mislabels headings / running
  headers / lone captions as `info`; body prose is reliable. A deterministic
  guard is a candidate cleanup.
