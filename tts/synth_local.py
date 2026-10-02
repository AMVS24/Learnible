"""Local Chatterbox narration (no Colab): reads output/reading_sequence.json
and produces output/narration.{wav,mp3} + output/manifest.json, entirely on
this machine's GPU.

Adapted from tts/chatterbox_synth.ipynb (which offloaded synthesis to a free
Colab GPU because the original dev machine had 4 GB of VRAM). This laptop has
a 12 GB RTX 5070, so both qwen3 (via Ollama) and Chatterbox run locally now --
no upload/download round trip needed.

Usage:
    python -m tts.synth_local                # pages from the last main.py run
    python -m tts.synth_local --input path/to/reading_sequence.json

Per-chunk text is prefixed with a spoken cue the first time a figure becomes
active ("Look at Figure 6.1."), and NOT re-announced while it stays active --
the de-duplication algorithm from docs/ARCHITECTURE.md §9 (announce B \\ A,
then A = B). A short silence separates chunks (matches PAUSE_S from the
Colab notebook). `manifest.json` is the single file web/ consumes -- see
`build_manifest`.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

import numpy as np
import soundfile as sf
import torch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src import config  # noqa: E402

EXAGGERATION = 0.5   # 0.3-0.5 = calm/neutral narration; higher = more expressive
CFG_WEIGHT = 0.3      # lower = slower, more deliberate pacing (good for audiobooks)
PAUSE_S = 0.45         # silence between chunks
AUDIO_PROMPT = None    # path to a ~10s wav to clone a voice; None = built-in voice
MP3_BITRATE = "96k"    # voice-only narration; keeps the web-app asset well under
                        # Vercel's 100MB-per-file cap (a raw wav blows past it)

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
# Chatterbox mishandles bare "=" in short math-style expressions ("t = 0"
# read back as garbled syllables instead of the words) -- it's rare in the
# spoken-English text the model was trained on. Spelling it out fixes it;
# `\s*=\s*` also normalises "t=0" / "t =0" to the same wording.
_EQUALS = re.compile(r"\s*=\s*")
# Milliseconds abbreviation, plain ("10 ms") or hyphenated-adjective
# ("10-ms sub-job") -- read as "10 misses" unexpanded (confirmed via Whisper
# transcript diff against the synthesised audio, see check_pronunciation.py).
_MS = re.compile(r"(\d+)\s*-?\s*ms\b")
# PDF extraction drops subscript formatting, so these scheduling-metric
# variables (T_arrival, T_turnaround, T_completion in the book) come through
# run together as one token. Chatterbox doesn't just mispronounce it --
# Whisper showed it garbles the *whole surrounding phrase* ("Tarrival = 0"
# became "I'll enhance ... t-completion"), far worse than the bare "="
# case. A space before the metric name reads naturally ("T arrival").
_SUBSCRIPT_VARS = {
    "Tarrival": "T arrival",
    "Tturnaround": "T turnaround",
    "Tcompletion": "T completion",
}


# The memory chapters (segmentation, paging) are dense with these:
# "16KB" / "4 MB" sizes, hex addresses ("0x3C00"), C shift operators, and
# code identifiers like VPN_MASK / SEGMENTATION_FAULT -- the same kind of
# compact non-prose notation that garbled "=" and "ms" above.
_SIZE = re.compile(r"\b(\d+)\s?(KB|MB|GB)\b(?=(\s+[a-z]+)?)")
_SIZE_WORDS = {"KB": "kilobyte", "MB": "megabyte", "GB": "gigabyte"}
# After a size, these mean it's used as a noun ("grows by 2KB in size");
# any other following word means it's an adjective ("a 16KB address
# space"), which reads singular.
_NOUN_FOLLOWERS = {"of", "in", "to", "and", "or", "at", "for", "from", "is", "are",
                   "was", "were", "with", "into", "the", "a", "an", "each", "per", "but"}
_HEX = re.compile(r"\b0x([0-9A-Fa-f]+)\b")
_IDENT = re.compile(r"\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b")
# Found by the Whisper diff on ch16/ch18:
# - Section and figure numbers ("16.2", "Figure 18.2") come out garbled
#   ("16 tor", "1.6"); "16 point 2" is read cleanly, and is also right for
#   genuine decimals.
_DECIMAL = re.compile(r"\b(\d+)\.(\d+)\b")
# - x86 registers ("%eax" -> "pretend ax"): spell the name out.
_REGISTER = re.compile(r"%([a-z]{2,3})\b")
# - Binary strings ("1110101") get mangled; read them digit by digit. Five or
#   more 0/1 digits (or a leading-zero group like "0110"), but not round
#   decimal numbers like 10000 / 11000.
_BINARY = re.compile(r"\b(?:0[01]{3,}|[01]{5,})\b")
_ROUND_DECIMAL = re.compile(r"^1?1?0+$")


# Found by the Whisper diff on ch27 (Thread API): "pthread" was read
# inconsistently ("pred", "threat", "poll thread"), lowercase C identifiers
# ran together ("pthread_join" -> "threadjoin"), and NULL was spelled out.
_SNAKE = re.compile(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b")
_PTHREAD = re.compile(r"\bpthread", re.IGNORECASE)
_NULL = re.compile(r"\bNULL\b")


def _binary(m: re.Match) -> str:
    s = m.group(0)
    return s if _ROUND_DECIMAL.match(s) and not s.startswith("0") else " ".join(s)


def _size(m: re.Match) -> str:
    word = _SIZE_WORDS[m.group(2)]
    nxt = (m.group(3) or "").strip()
    adjective = nxt and nxt not in _NOUN_FOLLOWERS
    return f"{m.group(1)} {word}" + ("" if adjective or m.group(1) == "1" else "s")


def _ident(m: re.Match) -> str:
    # Parts of up to 3 letters are acronyms (VPN, PTE) and stay
    # letter-by-letter; longer ones are words that would otherwise be
    # spelled out ("MASK", "FAULT").
    return " ".join(p if len(p) <= 3 else p.lower() for p in m.group(0).split("_"))


def _normalize_math(text: str) -> str:
    text = _EQUALS.sub(" equals ", text)
    text = _MS.sub(r"\1 milliseconds", text)
    for concatenated, spaced in _SUBSCRIPT_VARS.items():
        text = text.replace(concatenated, spaced)
    text = _SIZE.sub(_size, text)
    # Digit by digit ("hex 3 C 0 0"), the way addresses are read aloud --
    # "0x3000" as "three thousand" would misstate a hex value.
    text = _HEX.sub(lambda m: "hex " + " ".join(m.group(1).upper()), text)
    text = text.replace("<<", " shifted left by ").replace(">>", " shifted right by ")
    text = _IDENT.sub(_ident, text)
    text = _SNAKE.sub(lambda m: m.group(0).replace("_", " "), text)
    text = _PTHREAD.sub("P thread", text)
    text = _NULL.sub("null", text)
    text = _DECIMAL.sub(r"\1 point \2", text)
    text = _REGISTER.sub(lambda m: " ".join(m.group(1).upper()), text)
    text = text.replace("$hex", "hex")
    text = _BINARY.sub(_binary, text)
    return text


def _sentences(text: str) -> list[str]:
    parts = [p for p in _SENTENCE_SPLIT.split(text.strip()) if p]
    return parts or [text]


def _figure_cue(labels: list[str]) -> str:
    if len(labels) == 1:
        return f"Look at {labels[0]}."
    return "Look at " + ", ".join(labels[:-1]) + f" and {labels[-1]}."


def build_script(units: list[dict]) -> list[str]:
    """Reading-order list of spoken passages, one per reading unit, with
    figure cues prepended only when a figure newly becomes active."""
    active: set[str] = set()
    script: list[str] = []
    for u in units:
        refs = u["figure_refs"]
        new = [r for r in refs if r not in active]
        active = set(refs)
        text = u["text"].strip()
        if new:
            text = _figure_cue(new) + " " + text
        # After the cue is prepended: its "Figure 18.2" needs normalising too.
        script.append(_normalize_math(text))
    return script


def synth(model, text: str) -> torch.Tensor:
    kw = dict(exaggeration=EXAGGERATION, cfg_weight=CFG_WEIGHT)
    if AUDIO_PROMPT:
        kw["audio_prompt_path"] = AUDIO_PROMPT
    wavs = [model.generate(s, **kw) for s in _sentences(text)]
    wavs = [w if w.dim() == 2 else w.unsqueeze(0) for w in wavs]
    return torch.cat(wavs, dim=-1)


def build_manifest(data: dict, durations: list[float], audio_filename: str) -> dict:
    """The single artifact the web app consumes: `reading_sequence.json`'s
    static data (pages/chunks/figures, already carrying bbox + caption_bbox)
    plus the timing this run just produced, merged into one file -- one
    fewer data source for the frontend to reconcile, matching the recovered
    original app's unified `manifest.json` contract.

    `active_figures` on each chunk is the last non-empty figure_refs seen so
    far, persisting across chunks that reference none -- the "on-the-go
    mode" signal: which figure a UI should keep showing right now, not just
    which chunk is currently mentioning one."""
    t = 0.0
    active: list[str] = []
    chunks: list[dict] = []
    for u, dur in zip(data["reading_sequence"], durations):
        refs = u["figure_refs"]
        if refs:
            active = refs
        t0, t1 = t, t + dur
        chunks.append({
            **{k: u[k] for k in ("index", "page", "category", "text", "bbox")},
            "t0": round(t0, 2), "t1": round(t1, 2), "active_figures": list(active),
        })
        t = t1 + PAUSE_S
    return {
        "source": data["source"],
        "audio": audio_filename,
        "pages": data["pages"],
        "chunks": chunks,
        "figures": data["figures"],
        "orphan_figures": data["orphan_figures"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Synthesise narration.wav from a reading_sequence.json")
    parser.add_argument("--input", default=None, help="path to reading_sequence.json")
    parser.add_argument("--output", default=None, help="path to write the wav")
    args = parser.parse_args(argv)

    in_path = Path(args.input) if args.input else config.OUTPUT_DIR / "reading_sequence.json"
    out_path = Path(args.output) if args.output else config.OUTPUT_DIR / "narration.wav"
    manifest_path = out_path.with_name("manifest.json")

    data = json.loads(in_path.read_text(encoding="utf-8"))
    units = data["reading_sequence"]
    script = build_script(units)
    print(f"{len(script)} passages to synthesise from {in_path}")

    from chatterbox.tts import ChatterboxTTS
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Loading Chatterbox on {device} ...")
    model = ChatterboxTTS.from_pretrained(device=device)
    sr = model.sr

    silence = torch.zeros(1, int(PAUSE_S * sr))
    pieces: list[torch.Tensor] = []
    durations: list[float] = []
    total_s = 0.0
    for i, text in enumerate(script):
        wav = synth(model, text).cpu()
        dur = wav.shape[-1] / sr
        durations.append(dur)
        pieces.append(wav)
        pieces.append(silence)
        total_s += dur + PAUSE_S
        if i % 10 == 0 or i == len(script) - 1:
            print(f"  {i + 1}/{len(script)}  ({total_s / 60:.1f} min so far)")

    audio = torch.cat(pieces, dim=-1).squeeze().numpy().astype(np.float32)
    config.OUTPUT_DIR.mkdir(exist_ok=True)
    sf.write(str(out_path), audio, sr)

    mp3_path = out_path.with_suffix(".mp3")
    _encode_mp3(out_path, mp3_path)

    manifest = build_manifest(data, durations, mp3_path.name)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\nDONE: {len(script)} passages, {total_s / 60:.1f} min -> {out_path}")
    print(f"  wrote {mp3_path} ({mp3_path.stat().st_size / 1e6:.1f} MB)")
    print(f"  wrote {manifest_path}")
    return 0


def _encode_mp3(wav_path: Path, mp3_path: Path) -> None:
    from imageio_ffmpeg import get_ffmpeg_exe
    subprocess.run(
        [get_ffmpeg_exe(), "-y", "-i", str(wav_path),
         "-codec:a", "libmp3lame", "-b:a", MP3_BITRATE, str(mp3_path)],
        check=True, capture_output=True,
    )


if __name__ == "__main__":
    raise SystemExit(main())
