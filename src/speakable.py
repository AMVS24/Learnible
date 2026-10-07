"""Vision-model rewrite of each reading unit into speakable text.

Scanned books (e.g. Lewis & Papadimitriou) carry an OCR text layer that reads
prose fine but mangles notation: Σ comes out as "~", δ as "J", ∈ as "E",
⊆ as "~". Spoken as-is, a definition like "M = (K, Σ, δ, s, F)" is
gibberish -- and text alone can't tell whether an "E" is ∈ or the letter E.

So for each unit we crop its region from the page image and ask a local
vision model (Ollama) to write out what a lecturer would *say*, word for word,
with the OCR text as a hint for the prose. The result goes in `spoken`; the
original `text` is kept untouched (the reader shows the page image anyway).
tts/synth_local.py speaks `spoken` when present.

Guard against paraphrase/hallucination: the rewrite must keep most of the
OCR's ordinary words (`_overlap`); if it doesn't, the unit keeps its OCR text
and is reported. Resumable: units that already have `spoken` are skipped.
"""
from __future__ import annotations

import base64
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

import fitz  # PyMuPDF

from . import config

MODEL = "qwen3.5:9b"
CROP_ZOOM = 2.5
PAD_PT = 4
MIN_OVERLAP = 0.6   # share of the OCR's ordinary words the rewrite must keep

PROMPT = (
    "This image is a passage from a theory-of-computation textbook. Rewrite it exactly as a lecturer "
    "would read it aloud, word for word, keeping all the prose unchanged, but speaking every mathematical "
    "symbol and expression in plain English (e.g. Σ as 'sigma', δ as 'delta', ∈ as 'is in' or 'in', "
    "⊆ as 'is a subset of', ∪ as 'union', ∅ as 'the empty set', ε or e as 'the empty string', K × Σ as "
    "'K cross sigma', q₀ as 'q zero', Σ* as 'sigma star', M = (K, Σ, δ, s, F) as 'M equals the quintuple "
    "K, sigma, delta, s, F'). Do not add, summarise, or explain anything, and do not describe diagrams. "
    "Output only the spoken text. An OCR transcript (with garbled symbols) is provided as a hint for the "
    "prose:\n\n"
)

# For a region whose OCR text is empty (on scans, usually a heading whose text
# layer is misaligned): the model only gets the image, and given free rein on
# a tiny crop it will *invent* a plausible continuation. So: heading-only
# prompt, first line only, a handful of words.
HEADING_PROMPT = (
    "This image is a single heading from a textbook. Output only the heading text exactly as printed "
    "(including its section number), nothing else."
)
HEADING_MAX_WORDS = 10
# Spelling out notation lengthens text (a garbled "{a^n b^n : n >= 0}" is a
# few OCR tokens but a dozen spoken words), but not unboundedly. A rewrite
# longer than this many words per OCR token (+ slack) is treated as invented
# -- the model padding a tiny fragment like "Similarly," into a paragraph --
# and the OCR text is used instead.
MAX_WORDS_PER_TOKEN = 3.5
WORD_SLACK = 12


def too_long(ocr: str, spoken: str) -> bool:
    return len(spoken.split()) > MAX_WORDS_PER_TOKEN * len(ocr.split()) + WORD_SLACK

# Units whose text needs no rewrite.
_SKIP_CATEGORIES = {"code_listing"}
_WORD = re.compile(r"[A-Za-z]{4,}")


def _overlap(ocr: str, spoken: str) -> float:
    words = [w.lower() for w in _WORD.findall(ocr)]
    if len(words) < 5:
        return 1.0  # too short to judge (titles, one-liners)
    have = set(w.lower() for w in _WORD.findall(spoken))
    return sum(w in have for w in words) / len(words)


def _ask(png: bytes, ocr: str, keep_alive: str = "5m", glossary: str = "") -> str:
    prompt = (PROMPT.replace("An OCR transcript", glossary + " An OCR transcript") if glossary else PROMPT) + ocr
    body = {
        "model": MODEL, "prompt": prompt if ocr.strip() else HEADING_PROMPT, "images": [base64.b64encode(png).decode()],
        "stream": False, "think": False, "keep_alive": keep_alive,
        "options": {"temperature": 0},
    }
    req = urllib.request.Request(f"{config.OLLAMA_HOST}/api/generate", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=900) as r:
        return json.load(r)["response"].strip()


def _cache_key(u: dict) -> tuple:
    return (u["page"], *(round(v) for v in u["bbox"]))


def make_speakable(seq_path: Path, pdf_path: str, cache: list[Path] = (), glossary: str = "") -> dict:
    data = json.loads(seq_path.read_text(encoding="utf-8"))
    units = data["reading_sequence"]
    # Reuse rewrites from earlier runs of the same unit: same page + region
    # + OCR text means the same passage.
    cached = {}
    for c in cache:
        for u in json.loads(Path(c).read_text(encoding="utf-8"))["reading_sequence"]:
            if "spoken" in u and "spoken_fallback" not in u:
                cached[(_cache_key(u), u["text"])] = u["spoken"]
    reused = 0
    for u in units:
        hit = cached.get((_cache_key(u), u["text"]))
        if "spoken" not in u and hit is not None:
            u["spoken"], reused = hit, reused + 1
    if reused:
        print(f"Reused {reused} cached rewrite(s) from {len(cache)} earlier run(s)")
    todo = [u for u in units if "spoken" not in u and u["category"] not in _SKIP_CATEGORIES]
    print(f"Speakable rewrite with {MODEL}: {len(todo)} of {len(units)} units")
    doc = fitz.open(pdf_path)
    flagged, t_start = [], time.time()
    try:
        for n, u in enumerate(todo, 1):
            page = doc[u["page"] - 1]
            x0, y0, x1, y1 = u["bbox"]
            clip = fitz.Rect(x0 - PAD_PT, y0 - PAD_PT, x1 + PAD_PT, y1 + PAD_PT) & page.rect
            png = page.get_pixmap(matrix=fitz.Matrix(CROP_ZOOM, CROP_ZOOM), clip=clip).tobytes("png")
            spoken = _ask(png, u["text"], glossary=glossary)
            ratio = _overlap(u["text"], spoken)
            if not u["text"].strip():
                words = spoken.splitlines()[0].split() if spoken.strip() else []
                if 0 < len(words) <= HEADING_MAX_WORDS:
                    u["spoken"] = " ".join(words)
                else:
                    flagged.append({"index": u["index"], "page": u["page"], "reason": "empty OCR, no short heading read"})
                    u["spoken"], u["spoken_fallback"] = "", "empty OCR and the model didn't return a short heading"
            elif too_long(u["text"], spoken):
                flagged.append({"index": u["index"], "page": u["page"], "reason": "rewrite much longer than source"})
                u["spoken"] = u["text"]
                u["spoken_fallback"] = (f"rewrite was {len(spoken.split())} words for {len(u['text'].split())} "
                                        "OCR tokens (likely invented); using OCR text")
            elif ratio < MIN_OVERLAP:
                flagged.append({"index": u["index"], "page": u["page"], "overlap": round(ratio, 2)})
                u["spoken"] = u["text"]
                u["spoken_fallback"] = f"rewrite kept only {ratio:.0%} of the OCR words; using OCR text"
            else:
                u["spoken"] = spoken
            if n % 10 == 0 or n == len(todo):
                print(f"  {n}/{len(todo)}  ({time.time() - t_start:.0f}s)", flush=True)
                # checkpoint, so an interrupted run resumes where it stopped
                seq_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    finally:
        doc.close()
        _unload()
    data["source"]["speakable"] = {"model": MODEL, "flagged": flagged}
    seq_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    if flagged:
        print(f"  {len(flagged)} unit(s) fell back to OCR text: {flagged}", file=sys.stderr)
    return data


def _unload() -> None:
    """Free the VLM's VRAM before Chatterbox loads (both share one GPU)."""
    try:
        body = json.dumps({"model": MODEL, "keep_alive": 0}).encode()
        urllib.request.urlopen(urllib.request.Request(f"{config.OLLAMA_HOST}/api/generate", data=body,
                                                      headers={"Content-Type": "application/json"}), timeout=60)
    except Exception:  # noqa: BLE001 -- best effort
        pass


def revalidate(seq_path: Path, pdf_path: str) -> dict:
    """Re-check a prepared unit's rewrites against the current guards: drop
    rewrites of empty-OCR regions so they're re-asked with the heading-only
    prompt, fall back to OCR text where a rewrite is implausibly long or keeps
    too few OCR words, then fill in anything missing."""
    data = json.loads(seq_path.read_text(encoding="utf-8"))
    reasked, fell_back = 0, 0
    for u in data["reading_sequence"]:
        if "spoken" not in u or "spoken_fallback" in u:
            continue
        if not u["text"].strip():
            del u["spoken"]
            reasked += 1
        elif too_long(u["text"], u["spoken"]) or _overlap(u["text"], u["spoken"]) < MIN_OVERLAP:
            u["spoken"], u["spoken_fallback"] = u["text"], "failed revalidation (likely invented); using OCR text"
            fell_back += 1
    seq_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"revalidate {seq_path.parent.name}: {fell_back} fell back to OCR, {reasked} empty-OCR units re-asked")
    return make_speakable(seq_path, pdf_path)


_SECNUM = re.compile(r"^\s*(section\s+)?\d+(\.\d+)+", re.I)


def _core(heading: str) -> str:
    """Heading minus "Section", its number or a short garbled stand-in, and
    punctuation: "Section 2.3: Finite Automata." / "B Finite Automata" ->
    "finiteautomata"."""
    h = re.sub(r"^\s*(section\s+)?(\d+(\.\d+)*|\S{1,4})[:.]?\s+", "", heading, flags=re.I)
    return re.sub(r"[^a-z0-9]", "", h.lower())


def polish_titles(seq_path: Path) -> int:
    """Final pass over headings: ALL-CAPS headings ("2.2 NONDETERMINISTIC
    FINITE AUTOMATA") are re-cased so TTS doesn't treat words as acronyms, and
    a heading that repeats the one right before it (the same heading boxed
    twice, one copy only readable via the image) is dropped."""
    data = json.loads(seq_path.read_text(encoding="utf-8"))
    out, dropped = [], 0
    for u in data["reading_sequence"]:
        sp = u.get("spoken") or ""
        if u["category"] == "title" and sp and sp.upper() == sp and any(ch.isalpha() for ch in sp):
            u["spoken"] = " ".join(w.capitalize() if w.isalpha() else w for w in sp.lower().split())
        prev = out[-1] if out else None
        if prev and u["category"] == "title" and prev["category"] == "title":
            cur_s, prev_s = (u.get("spoken") or u["text"]), (prev.get("spoken") or prev["text"])
            if _core(cur_s) and _core(cur_s) == _core(prev_s):
                # Same heading twice; keep the copy with a real section number
                # ("2.6 ...") over a garbled one ("B ...").
                if _SECNUM.match(cur_s) and not _SECNUM.match(prev_s):
                    out[-1] = u
                dropped += 1
                continue
        out.append(u)
    data["reading_sequence"] = out
    seq_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return dropped
