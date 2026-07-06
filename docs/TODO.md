# Learnible — TODO / Features backlog

Running list of deferred work so nothing is forgotten. See
[ARCHITECTURE.md](ARCHITECTURE.md) for design context and
`../output/classification_audit.md` for the latest empirical state.

## Next up — Step 4: Chunk → Figure mapping
- [ ] **Text-figure label association (prerequisite).** Attach `Figure N` /
      `Table N` labels to code/table Figures by matching their nearby caption
      block (deterministic geometry + regex, same as diagrams). Labels are the
      join key for mapping.
- [ ] **Mapping pass (pure LLM, Option A).** For each Chunk, give the model the
      chunk text + catalogue of Figures (label/caption/category); it returns the
      referenced figure indices. Scope = whole splice (cross-page allowed).
      Output: `list[ReadingUnit]` → `output/mapping.json`.

## Deferred — TTS / sequencing layer (Steps 5–6)
- [ ] **Active-figure announcement de-duplication.** Streaming pass over the
      `ReadingUnit` list: keep active set `A`; for each unit with figures `B`,
      announce `B \ A`, then set `A = B`. Announces a continuously-referenced
      figure once, not per chunk. (Post-processing, after mapping.)
- [ ] **Per-category TTS behaviour.** Decide: skip `exercise` chunks? summarise
      `misc_textbox`? skip `decorative` figures entirely? (from ideation doc)
- [ ] **Output DS optimization (maybe).** The ordered `list[ReadingUnit]` is
      correct for linear playback; revisit a smarter structure only if a concrete
      need appears.
- [ ] **Better audio UX.** Earcon/audio cue instead of a spoken prompt; distinct
      voice for prompts vs. content.
- [ ] TTS → MP3 (Step 6).

## Classifier / splicer cleanups
- [ ] **Short-block guard (deterministic).** Force `other` for headings
      (`^\d+\.\d+`), all-caps running headers, and `Figure N:` captions — the
      spots where the model drifts to `info`. Avoids touching the model.
- [ ] **Touching diagrams.** Proximity clustering still merges two diagrams that
      physically touch; refine if a real case appears.
- [ ] **Caption routing.** Figure/Table captions sometimes classified as
      `misc_textbox` instead of `other`; unify caption handling.

## Broader / future (from the ideation doc)
- [ ] Multi-column page layouts.
- [ ] Math equations (MathML / rendered images).
- [ ] Mobile companion app to display figures on cue.
- [ ] Generalise beyond the single hardcoded test PDF / page range in
      `src/config.py`.
