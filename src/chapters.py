"""Chapter catalog + per-chapter rendering for a textbook PDF.

    python -m src.chapters scan              # print the chapter table, write output/<book>/catalog.json
    python -m src.chapters render 16 18      # pipeline + TTS for chapters 16 and 18
    python -m src.chapters render 16 --no-tts   # pipeline only (no audio)
    python -m src.chapters queue             # every unit in src/ostep_units.json, in order

Chapter boundaries come from the *page text*, not the book's printed index:
OSTEP is a concatenation of per-chapter PDFs, so every chapter restarts its
in-book numbering at 1 and the Contents page numbers are meaningless as PDF
page numbers. A chapter-opening page is recognised by its first two lines --
the chapter number/letter alone, then a mixed-case title ("16" /
"Segmentation") -- whereas every other page starts with a running header
whose title is ALL CAPS ("2" / "SEGMENTATION"). "Part I/II/III" divider pages
also end the previous chapter. The PDF outline is only a cross-check (it's off
by one for ch25/ch35, pointing at the blank page before each) and a fallback
for any opener with no extractable text -- those are flagged `verified: false`.

Only the chapter body is narrated: `body_end` stops before the page whose
heading is "References" (bibliographies read terribly via TTS -- see
docs/ARCHITECTURE_v2.md); References/Homework pages are still part of the
chapter's `pdf_end`.

Each chapter renders into its own fresh directory, output/<book>/ch<NN>/, so
nothing here overwrites the older ad-hoc output/ files.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import fitz  # PyMuPDF

from . import config
from .books import BOOKS

# The active book (see src/books.py); switched by `--book` via use_book().
BOOK_ID = "ostep"
BOOK: dict = BOOKS[BOOK_ID]
BOOK_TITLE = BOOK["title"]
BOOK_DIR = config.OUTPUT_DIR / BOOK_ID
UNITS_PATH = config.PROJECT_ROOT / "src" / f"{BOOK_ID}_units.json"
_ORIGINAL_ENV = dict(os.environ)  # snapshot before YOLO mutates CUDA_VISIBLE_DEVICES (see render)

_CHAPTER_NUM = re.compile(r"^(\d{1,2}|[A-I])$")
_PART = re.compile(r"^Part [IVX]+$")
_OUTLINE_CH = re.compile(r"^(\d{1,2}|[A-I])\.?\s+(.*)$")


def use_book(book_id: str) -> None:
    global BOOK_ID, BOOK, BOOK_TITLE, BOOK_DIR, UNITS_PATH
    if book_id not in BOOKS:
        raise SystemExit(f"unknown book {book_id!r}; known: {', '.join(BOOKS)}")
    BOOK_ID, BOOK = book_id, BOOKS[book_id]
    BOOK_TITLE = BOOK["title"]
    BOOK_DIR = config.OUTPUT_DIR / BOOK_ID
    UNITS_PATH = config.PROJECT_ROOT / "src" / f"{BOOK_ID}_units.json"


def book_chapters() -> list[dict]:
    if BOOK["chapters"] == "scan":
        return scan_chapters(str(BOOK["pdf"]))
    return contents_chapters()


def _squash(s: str) -> str:
    """Letters/digits only, lowercased: OCR splits words ("a nd La nguages")."""
    return re.sub(r"[^a-z0-9]", "", s.lower())


def contents_chapters() -> list[dict]:
    """Chapters from the book's Contents list (printed pages + page_offset),
    each verified against its opener page's text. Body ends before the
    "References" heading: if that heading sits partway down a page, the page
    stays in the body and `body_stop` tells render_unit to trim there."""
    off = BOOK["page_offset"]
    doc = fitz.open(str(BOOK["pdf"]))
    try:
        entries = BOOK["chapters"]
        out = []
        for i, (num, title, printed) in enumerate(entries):
            start = printed + off
            end = (entries[i + 1][2] + off - 1) if i + 1 < len(entries) else BOOK["last_page"]
            head = _squash(" ".join(_lines(doc[start - 1], 6)))
            verified = _squash(title) in head
            if not verified:
                print(f"  WARNING: ch{num} {title!r}: title not found on PDF p{start} "
                      f"(printed {printed}) -- check page_offset", file=sys.stderr)
            body_end, body_stop = end, None
            for p in range(start + 1, end + 1):
                # Case-insensitive: the section heading is "REFERENCES" while
                # the next page's running header is "References".
                lines = [l.casefold() for l in _lines(doc[p - 1], 80)]
                if "references" in lines:
                    if lines.index("references") <= 2:
                        body_end = p - 1
                    else:
                        body_end, body_stop = p, "REFERENCES"
                    break
            out.append({
                "id": f"ch{int(num):02d}", "num": num, "title": title, "part": "Chapters",
                "pdf_start": start, "pdf_end": end, "body_end": body_end,
                **({"body_stop": body_stop} if body_stop else {}),
                "verified": verified,
            })
        return out
    finally:
        doc.close()


def _lines(page: fitz.Page, n: int = 4) -> list[str]:
    return [l.strip() for l in page.get_text().splitlines() if l.strip()][:n]


def _is_opener(lines: list[str]) -> tuple[str, str] | None:
    if len(lines) < 2 or not _CHAPTER_NUM.match(lines[0]):
        return None
    title = lines[1]
    if title.upper() == title:  # running header ("SEGMENTATION"), not a title page
        return None
    return lines[0], title


def scan_chapters(pdf_path: str) -> list[dict]:
    doc = fitz.open(pdf_path)
    try:
        n_pages = len(doc)
        starts: dict[str, dict] = {}   # chapter id -> {num, title, pdf_start, verified}
        parts: dict[int, str] = {}   # divider page -> "Part I: Virtualization"
        for i in range(n_pages):
            lines = _lines(doc[i])
            if lines and _PART.match(lines[0]):
                parts[i + 1] = f"{lines[0]}: {lines[1]}" if len(lines) > 1 else lines[0]
                continue
            hit = _is_opener(lines)
            if hit and hit[0] not in starts:
                starts[hit[0]] = {"num": hit[0], "title": hit[1], "pdf_start": i + 1, "verified": True}

        # Cross-check / fill gaps from the outline.
        for level, text, page in doc.get_toc():
            m = _OUTLINE_CH.match(text)
            if level != 2 or not m:
                continue
            num, title = m.group(1).lstrip("0"), m.group(2).replace(" - ", ": ")
            if num not in starts:
                starts[num] = {"num": num, "title": title, "pdf_start": page, "verified": False}
                continue
            c = starts[num]
            # A title that wraps onto a second line on the opener page
            # ("Scheduling:" / "The Multi-Level Feedback Queue") is cut short
            # by _is_opener; the outline carries the whole thing.
            if len(title) > len(c["title"]) and title.startswith(c["title"]):
                c["title"] = title
            if c["pdf_start"] != page:
                print(f"  note: ch{num} opener found on PDF p{c['pdf_start']}, "
                      f"outline says p{page} -- using the page text", file=sys.stderr)

        ordered = sorted(starts.values(), key=lambda c: c["pdf_start"])
        boundaries = sorted({c["pdf_start"] for c in ordered} | set(parts) | {n_pages + 1})
        chapters = []
        for c in ordered:
            end = next(b for b in boundaries if b > c["pdf_start"]) - 1
            body_end = end
            for p in range(c["pdf_start"] + 1, end + 1):
                if "References" in _lines(doc[p - 1]):
                    body_end = p - 1
                    break
            # Sidebar grouping: the last Part divider before this chapter
            # (ch1-2 precede Part I; lettered chapters are the appendix).
            part = next((t for pg, t in sorted(parts.items(), reverse=True)
                         if pg < c["pdf_start"]), "Introduction")
            if not c["num"].isdigit():
                part = "Appendix"
            chapters.append({
                "id": f"ch{int(c['num']):02d}" if c["num"].isdigit() else f"app{c['num']}",
                "num": c["num"],
                "title": c["title"],
                "part": part,
                "pdf_start": c["pdf_start"],
                "pdf_end": end,
                "body_end": body_end,
                "verified": c["verified"],
            })
        return chapters
    finally:
        doc.close()


def _chapter_dir(ch: dict) -> Path:
    return BOOK_DIR / ch["id"]


def load_units() -> list[dict]:
    if not UNITS_PATH.exists():
        return []
    return json.loads(UNITS_PATH.read_text(encoding="utf-8"))["units"]


def _is_rendered(d: Path) -> bool:
    return (d / "manifest.json").exists() and (d / "narration.mp3").exists()


def write_catalog(chapters: list[dict]) -> Path:
    """catalog.json drives the web app's sidebar; `rendered` marks entries
    whose manifest.json + narration.mp3 exist. Partial-chapter units from
    ostep_units.json are listed right after their parent chapter
    (`partial: true`, `parent: "chNN"`)."""
    BOOK_DIR.mkdir(parents=True, exist_ok=True)
    out = BOOK_DIR / "catalog.json"
    partials: dict[str, list[dict]] = {}
    for u in load_units():
        if u.get("id"):
            partials.setdefault(u["chapter"].lstrip("0"), []).append(u)
    entries = []
    for ch in chapters:
        ch["rendered"] = _is_rendered(_chapter_dir(ch))
        entries.append(ch)
        for u in partials.get(ch["num"], []):
            d = BOOK_DIR / u["id"]
            src = {}
            if (d / "reading_sequence.json").exists():
                src = json.loads((d / "reading_sequence.json").read_text(encoding="utf-8"))["source"]
            entries.append({
                **{k: ch[k] for k in ("num", "part", "verified")},
                "id": u["id"], "title": u["title"], "partial": True, "parent": ch["id"],
                "start_heading": u.get("start"), "stop_heading": u.get("stop"),
                "pdf_start": src.get("page_start", ch["pdf_start"]),
                "pdf_end": src.get("page_end", ch["body_end"]),
                "body_end": src.get("page_end", ch["body_end"]),
                "rendered": _is_rendered(d),
            })
    out.write_text(json.dumps({"id": BOOK_ID, "title": BOOK_TITLE, "page_offset": BOOK["page_offset"],
                               "chapters": entries},
                              ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def _find(chapters: list[dict], key: str) -> dict:
    for ch in chapters:
        if ch["num"].lower() == key.lower().lstrip("0") or ch["id"] == key:
            return ch
    raise SystemExit(f"no chapter {key!r} -- run `python -m src.chapters scan` to list them")


def _norm(s: str) -> str:
    s = s.replace("ﬁ", "fi").replace("ﬂ", "fl").replace("’", "'")
    return re.sub(r"\s+", " ", s).strip().casefold()


def heading_page(pdf_path: str, heading: str, lo: int, hi: int) -> int:
    """PDF page (in lo..hi) whose text has `heading` as its own line -- or
    split over two lines ("28.3" / "Building A Lock"). Exactly one match is
    required, so a heading that also shows up in running text can't
    silently pick the wrong page."""
    want = _norm(heading)
    hits = set()
    doc = fitz.open(pdf_path)
    try:
        for p in range(lo, hi + 1):
            lines = [_norm(l) for l in doc[p - 1].get_text().splitlines() if l.strip()]
            for i, l in enumerate(lines):
                if (l == want or (i + 1 < len(lines) and f"{l} {lines[i + 1]}" == want)
                        or _garbled_number(l, want)):
                    hits.add(p)
    finally:
        doc.close()
    if len(hits) != 1:
        raise RuntimeError(f"heading {heading!r} found on pages {sorted(hits)} in {lo}-{hi}; need exactly one")
    return hits.pop()


def _garbled_number(text: str, want: str) -> bool:
    """`text` is `want` behind one short junk token -- an OCR-mangled section
    number ("liij pushdown automata" for "3.3 PUSHDOWN AUTOMATA"), with `want`
    given bare ("PUSHDOWN AUTOMATA"). A token ending in ":" is a running
    header ("3.3: Pushdown Automata"), not the heading itself."""
    return bool(re.fullmatch(r"[^\s:]{1,6} " + re.escape(want), text))


def _chunk_matches(unit: dict, heading: str) -> bool:
    text, want = _norm(unit["text"]), _norm(heading)
    bare = re.sub(r"^[\d.]+\s+", "", want)  # "28.3 building a lock" -> "building a lock"
    return (text.startswith(want)
            or (unit["category"] == "title" and (text.startswith(bare) or _garbled_number(text, want))))


def _line_positions(pdf_path: str, p0: int, p1: int) -> list[tuple[int, float, str]]:
    """(page, y, whitespace-normalised text) for every text line in p0..p1."""
    out = []
    doc = fitz.open(pdf_path)
    try:
        for p in range(p0, p1 + 1):
            for b in doc[p - 1].get_text("dict")["blocks"]:
                for l in b.get("lines", []):
                    t = re.sub(r"\s+", " ", " ".join(sp["text"] for sp in l["spans"])).strip()
                    if t:
                        out.append((p, l["bbox"][1], t))
    finally:
        doc.close()
    return out


def _is_heading_line(line: str, heading: str) -> bool:
    """`line` is the section heading `heading` as printed (case-sensitive:
    headings here are ALL CAPS), optionally behind a section number or its
    OCR-garbled stand-in -- but not a running header, which repeats the
    title as "2.2: Nondeterministic Finite Automata"."""
    if not line.endswith(heading):
        return False
    prefix = line[: len(line) - len(heading)].strip()
    return len(prefix) <= 6 and ":" not in prefix


def skip_sections(path: Path, pdf_path: str, p0: int, p1: int,
                  start_prefix: str, until_headings: list[str]) -> int:
    """Drop end-of-section exercise lists by *page position*: every chunk
    whose top edge lies between a line starting with `start_prefix` ("Problems
    for Section 2.1") and the next section heading (one of `until_headings`,
    allowing an OCR-garbled section number in front). Position-based because
    layout detection on scans sometimes merges a heading into the exercise
    block above it, so no chunk *starts* with the heading -- a text-based
    skip then runs straight through the next section."""
    lines = _line_positions(pdf_path, p0, p1)
    marks = [(pg, y) for pg, y, t in lines if t.startswith(start_prefix)]
    heads = [(pg, y) for pg, y, t in lines if any(_is_heading_line(t, h) for h in until_headings)]
    spans = []
    for m in marks:
        nxt = min((h for h in heads if h > m), default=(p1 + 1, 0.0))
        # End a little above the heading's text line: on scans the layout box
        # of the heading itself can sit a few points higher than its OCR text.
        spans.append((m, (nxt[0], nxt[1] - 15.0)))
    data = json.loads(path.read_text(encoding="utf-8"))
    keep = [u for u in data["reading_sequence"]
            if not any(a <= (u["page"], u["bbox"][1]) < b for a, b in spans)]
    dropped = len(data["reading_sequence"]) - len(keep)
    data["reading_sequence"] = keep
    data["source"].setdefault("trim", {})["skip"] = {
        "from": start_prefix, "spans": [[list(a), list(b)] for a, b in spans], "dropped": dropped}
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return dropped


def _iou(a: list[float], b: list[float]) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def _heading_core(text: str) -> str:
    """Heading text without its leading section number (or the OCR's garbled
    stand-in for one, which precedes an ALL-CAPS heading): "2.3 FINITE
    AUTOMATA" / "liiJ FINITE AUTOMATA" -> "finiteautomata". A short ordinary
    word ("The Abstraction") is left alone."""
    t = text.strip()
    m = re.match(r"(\d+(?:\.\d+)*|\S{1,4})[:.]?\s+(.*)$", t)
    if m and (m.group(1)[0].isdigit() or m.group(2)[:3].isupper()):
        t = m.group(2)
    return _squash(t)


def clean_sequence(path: Path, drop_patterns: list[str], keep_empty: bool = False) -> int:
    """Drop (a) a chunk whose region duplicates an earlier one on the same
    page (layout detection sometimes emits the same box twice, e.g. as text
    *and* title -- it would be read twice), and (b) chunks that are only a
    running header / page number (book-specific `drop_patterns`), and (c)
    chunks with no extracted text -- unless `keep_empty` (scanned books: the
    vision rewrite reads them straight off the image, e.g. a section heading
    whose OCR text is misaligned)."""
    data = json.loads(path.read_text(encoding="utf-8"))
    keep: list[dict] = []
    for u in data["reading_sequence"]:
        t = u["text"].strip()
        if not t and not keep_empty:
            continue
        if any(re.match(pat, t) for pat in drop_patterns):
            continue
        if any(k["page"] == u["page"] and _iou(k["bbox"], u["bbox"]) > 0.8 for k in keep):
            continue
        # The same heading boxed twice, with and without its number
        # ("2.3 FINITE AUTOMATA ..." then "FINITE AUTOMATA ..."): keep the
        # fuller one.
        prev = keep[-1] if keep else None
        if (prev and u["category"] == "title" and prev["category"] == "title" and prev["page"] == u["page"]
                and _squash(t) and _squash(prev["text"])):
            # Equal once the leading section number is stripped -- not mere
            # containment, or the chapter title "Finite Automata" would be
            # swallowed by "2.1 Deterministic Finite Automata".
            a_, b_ = _heading_core(prev["text"]), _heading_core(t)
            if a_ == b_:
                if len(_squash(t)) > len(_squash(prev["text"])):
                    keep[-1] = u  # keep the copy that carries the number
                continue
        keep.append(u)
    dropped = len(data["reading_sequence"]) - len(keep)
    data["reading_sequence"] = keep
    data["source"]["cleaned"] = dropped
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return dropped


def _heading_pos(pdf_path: str, heading: str, p0: int, p1: int) -> tuple[int, float]:
    """(page, y) of `heading` as its own text line (garbled section number
    tolerated); exactly one match required."""
    want = _norm(heading)
    hits = [(pg, y) for pg, y, t in _line_positions(pdf_path, p0, p1)
            if _norm(t) == want or _garbled_number(_norm(t), want)]
    if len(hits) != 1:
        raise RuntimeError(f"heading {heading!r}: {len(hits)} text-layer matches in PDF {p0}-{p1}; need one")
    return hits[0]


def _first_at_or_after(seq: list[dict], pos: tuple[int, float], tol: float = 15.0) -> int:
    """Index of the first chunk at or below page position `pos` (with a little
    tolerance: on scans the OCR text layer can sit a few points off the image
    the layout boxes were drawn on)."""
    return next((i for i, u in enumerate(seq) if (u["page"], u["bbox"][1] + tol) >= pos), len(seq))


def trim_sequence(path: Path, start: str | None, stop: str | None,
                  pdf_path: str | None = None, p0: int = 0, p1: int = 0) -> tuple[int, int]:
    """Cut reading_sequence.json down to [start heading, stop heading). The
    pipeline runs over whole pages, so this drops the bleed from the
    neighbouring sections that share the first/last page.

    Headings are matched against chunk text first. On scanned books a heading
    chunk can come out with no text at all (the OCR layer is misaligned with
    the image the layout boxes were drawn on), so if that fails the cut falls
    back to the heading's position in the PDF text layer."""
    data = json.loads(path.read_text(encoding="utf-8"))
    seq = data["reading_sequence"]
    how = {}
    i0 = 0
    if start:
        i0 = next((i for i, u in enumerate(seq) if _chunk_matches(u, start)), None)
        how["start"] = "chunk text"
        if i0 is None and pdf_path:
            i0, how["start"] = _first_at_or_after(seq, _heading_pos(pdf_path, start, p0, p1)), "text-layer position"
        if i0 is None:
            raise RuntimeError(f"start heading {start!r} not found among extracted chunks")
    i1 = len(seq)
    if stop:
        i1 = next((i for i, u in enumerate(seq) if i > i0 and _chunk_matches(u, stop)), None)
        how["stop"] = "chunk text"
        if i1 is None and pdf_path:
            i1, how["stop"] = max(i0, _first_at_or_after(seq, _heading_pos(pdf_path, stop, p0, p1))), "text-layer position"
        if i1 is None:
            raise RuntimeError(f"stop heading {stop!r} not found among extracted chunks")
    data["source"].setdefault("trim", {})["matched_by"] = how
    data["reading_sequence"] = seq[i0:i1]
    data["source"].setdefault("trim", {}).update({"start": start, "stop": stop})
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return i1 - i0, len(seq) - (i1 - i0)


def _prepared(seq_path: Path, trimmed: bool) -> bool:
    """Text prep (pipeline + any trim) finished: `chapter_start` is the last
    thing render_unit writes, and a partial unit must also carry `trim`."""
    if not seq_path.exists():
        return False
    src = json.loads(seq_path.read_text(encoding="utf-8"))["source"]
    return "chapter_start" in src and (not trimmed or "trim" in src)


def render_unit(chapters: list[dict], unit: dict, tts: bool = True, llm: bool = True) -> str:
    """Render one unit (a whole chapter body, or a heading-trimmed part of
    one) into its own directory. Never overwrites: an existing output dir is
    skipped (complete) or reported (incomplete) and left untouched."""
    from . import main as pipeline
    ch = _find(chapters, unit["chapter"])
    uid = unit.get("id") or ch["id"]
    out_dir = BOOK_DIR / uid
    # A whole chapter whose References heading sits mid-page still trims there.
    start, stop = unit.get("start"), unit.get("stop") or ch.get("body_stop")
    skip = unit.get("skip")
    seq_path = out_dir / "reading_sequence.json"
    if _is_rendered(out_dir):
        return "skipped (already rendered)"
    if out_dir.exists() and not _prepared(seq_path, trimmed=bool(start or stop or skip)):
        # Empty dir = claimed by the other machine in a split queue; anything
        # else half-made is left for a human to look at, never overwritten.
        raise RuntimeError(f"{out_dir} exists but isn't a resumable unit -- leaving it alone")

    if out_dir.exists():
        # Text prep finished in an earlier, interrupted run; only the audio is
        # missing, so just add it (new files only).
        src = json.loads(seq_path.read_text(encoding="utf-8"))["source"]
        p0, p1 = src["page_start"], src["page_end"]
        print(f"\n##### {uid}: resuming at TTS (text prep already done) -> {out_dir}")
        note = ", resumed at TTS"
    else:
        pdf = str(BOOK["pdf"])
        p0 = heading_page(pdf, start, ch["pdf_start"], ch["body_end"]) if start else ch["pdf_start"]
        p1 = heading_page(pdf, stop, p0, ch["body_end"]) if stop else ch["body_end"]
        print(f"\n##### {uid} ({ch['title']}): PDF pages {p0}-{p1}"
              f"{f', from {start!r}' if start else ''}{f', stop before {stop!r}' if stop else ''} -> {out_dir}")

        pipeline.main([f"{p0}-{p1}", "--out", str(out_dir), "--pdf", pdf] + ([] if llm else ["--no-llm"]))
        note = ""
        if start or stop:
            kept, dropped = trim_sequence(seq_path, start, stop, pdf, p0, p1)
            note = f", trimmed to {kept} chunks ({dropped} bleed chunks dropped)"
        if skip:
            n = skip_sections(seq_path, pdf, p0, p1, skip["from"], skip["until_headings"])
            note += f", {n} chunks of {skip['from']!r} skipped"
        n = clean_sequence(seq_path, BOOK.get("drop_patterns", []), keep_empty=bool(BOOK.get("speakable")))
        if n:
            note += f", {n} duplicate/header chunks dropped"
        if BOOK.get("speakable"):
            from .speakable import make_speakable
            # Rewrites from an earlier, superseded run of this unit are reused
            # (matched by page + region) instead of asking the model again.
            make_speakable(seq_path, pdf, cache=sorted((BOOK_DIR / "_superseded").glob(f"{uid}-*/reading_sequence.json")),
                           glossary=BOOK.get("speakable_glossary", ""))
            note += ", speakable rewrite"
        data = json.loads(seq_path.read_text(encoding="utf-8"))
        data["source"]["page_offset"] = BOOK["page_offset"]
        # Chapter-relative page numbers in the web header count from the
        # chapter opener, not from wherever a partial unit starts. Written
        # last: its presence marks the text prep as complete (see _prepared).
        data["source"]["chapter_start"] = ch["pdf_start"]
        seq_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    if tts:
        # Separate process with the *original* environment: the layout
        # stage's YOLO device selection ("cpu") sets
        # os.environ["CUDA_VISIBLE_DEVICES"] = "-1" (doclayout_yolo
        # torch_utils.select_device), which would otherwise silently push
        # Chatterbox onto the CPU -- in-process or inherited by a child.
        subprocess.run([sys.executable, "-m", "tts.synth_local",
                        "--input", str(seq_path), "--output", str(out_dir / "narration.wav")],
                       cwd=config.PROJECT_ROOT, env=_ORIGINAL_ENV, check=True)
    return f"rendered PDF {p0}-{p1}{note}"


def print_status(log: Path | None) -> None:
    """Per-unit state of the render queue (read-only): done (with narration
    length), in progress / claimed, or pending -- plus the latest passage
    counter from a queue log, if given."""
    done = 0
    units = load_units()
    for u in units:
        uid = u.get("id") or f"ch{int(u['chapter']):02d}"
        d = BOOK_DIR / uid
        if _is_rendered(d):
            chunks = json.loads((d / "manifest.json").read_text(encoding="utf-8"))["chunks"]
            state, done = f"done      {chunks[-1]['t1'] / 60:5.1f} min", done + 1
        elif (d / "reading_sequence.json").exists():
            src = json.loads((d / "reading_sequence.json").read_text(encoding="utf-8"))["source"]
            state = "in progress (TTS)" if "chapter_start" in src else "in progress (text)"
        elif d.exists():
            state = "in progress (text)"
        else:
            state = "pending"
        print(f"  {uid:16} {state}")
    print(f"\n  {done}/{len(units)} units done")
    if log and log.exists():
        text = log.read_text(encoding="utf-8", errors="replace").replace("\r", "\n")
        heads = re.findall(r"^##### (\S+)", text, re.M)
        counts = re.findall(r"^\s+(\d+)/(\d+)\s+\(([\d.]+) min so far\)", text, re.M)
        if heads:
            cur = f"  current: {heads[-1]}"
            if counts and text.rfind("##### ") < text.rfind(f"{counts[-1][0]}/{counts[-1][1]}"):
                cur += f"  passage {counts[-1][0]}/{counts[-1][1]} ({counts[-1][2]} min of audio so far)"
            print(cur)


def run_units(chapters: list[dict], units: list[dict], tts: bool, llm: bool) -> None:
    """Render units in order; one failure doesn't stop the rest."""
    results = []
    for u in units:
        uid = u.get("id") or _find(chapters, u["chapter"])["id"]
        try:
            results.append((uid, "ok", render_unit(chapters, u, tts, llm)))
        except Exception as e:  # noqa: BLE001 -- report it and carry on with the queue
            results.append((uid, "FAILED", f"{type(e).__name__}: {e}"))
            print(f"\n!!!!! {uid} FAILED: {e}", file=sys.stderr)
        write_catalog(chapters)  # keep the catalog current as units land
    print("\n===== queue summary")
    for uid, status, msg in results:
        print(f"  {uid:14} {status:6} {msg}")


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    parser = argparse.ArgumentParser(prog="python -m src.chapters")
    parser.add_argument("--book", default="ostep", help=f"one of: {', '.join(BOOKS)} (see src/books.py)")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("scan", help="detect chapters and write catalog.json")
    r = sub.add_parser("render", help="run pipeline (+TTS) for chapters, e.g. 16 18")
    r.add_argument("chapters", nargs="+")
    r.add_argument("--no-tts", action="store_true", help="skip Chatterbox narration")
    r.add_argument("--no-llm", action="store_true", help="skip qwen3 prose sub-categorisation")
    q = sub.add_parser("queue", help=f"render every unit in src/{UNITS_PATH.name}, in order, skipping done ones")
    q.add_argument("--no-tts", action="store_true")
    q.add_argument("--no-llm", action="store_true")
    q.add_argument("--reverse", action="store_true",
                   help="work from the back of the list (a second machine splitting the queue; "
                        "a unit whose output dir already exists is left alone either way)")
    s = sub.add_parser("status", help="show render-queue progress (read-only)")
    s.add_argument("--log", default=None, help="queue log to read the current passage counter from")
    args = parser.parse_args(argv)
    use_book(args.book)

    if args.cmd == "status":
        print_status(Path(args.log) if args.log else None)
        return 0
    chapters = book_chapters()
    if args.cmd == "scan":
        for ch in chapters:
            flag = "" if ch["verified"] else "  (outline fallback)"
            print(f"  {ch['id']:6} PDF {ch['pdf_start']:>3}-{ch['pdf_end']:<3} body..{ch['body_end']:<3} "
                  f"{ch['title']}{flag}")
    elif args.cmd == "queue":
        units = load_units()
        run_units(chapters, units[::-1] if args.reverse else units,
                  tts=not args.no_tts, llm=not args.no_llm)
    else:
        run_units(chapters, [{"chapter": k} for k in args.chapters],
                  tts=not args.no_tts, llm=not args.no_llm)
    print(f"\n  wrote {write_catalog(chapters)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
