"""Textbooks the chapter tooling (src/chapters.py) knows about.

`chapters` -- how chapter boundaries are found:
  * "scan": detect chapter-opener pages from the page text (OSTEP: each
    chapter restarts its printed numbering, so the Contents page is useless).
  * a list of (num, title, printed_start): taken from the book's own Contents
    page and converted with `page_offset` (PDF page = printed page + offset);
    each opener is verified against the page text before use.

`page_offset` -- printed page number = PDF page - page_offset, for books with
one continuous numbering. None = per-chapter numbering (OSTEP).

`speakable` -- run the vision-model rewrite (src/speakable.py) before TTS:
for scanned books whose OCR layer mangles math notation.
"""
from __future__ import annotations

from . import config

BOOKS: dict[str, dict] = {
    "ostep": {
        "title": "Operating Systems: Three Easy Pieces",
        "pdf": config.PROJECT_ROOT / "Operating Systems - Three Easy Pieces.pdf",
        "chapters": "scan",
        "page_offset": None,
        # On for every book now, not just scans: it also spells out notation
        # the OCR-free text layer has but TTS can't say well.
        "speakable": True,
    },
    "toc": {
        "title": "Elements of the Theory of Computation",
        "pdf": config.PROJECT_ROOT / "Elements_of_Theory_of_Computation_2ed_Lewis_Papadimitriou.pdf",
        # From the Contents page (PDF pp. 5-7). Printed page = PDF page - 14,
        # verified on every page header of chapters 1-3.
        "chapters": [
            ("1", "Sets, Relations, and Languages", 5),
            ("2", "Finite Automata", 55),
            ("3", "Context-Free Languages", 113),
            ("4", "Turing Machines", 179),
            ("5", "Undecidability", 245),
            ("6", "Computational Complexity", 275),
            ("7", "NP-completeness", 301),
        ],
        "last_page": 366,  # printed 352: end of ch7's References, before the Index
        "page_offset": 14,
        "speakable": True,
        # How this book says its relation symbols aloud (its own wording), so
        # the vision rewrite doesn't fall back on "turnstile" / "implies".
        "speakable_glossary": (
            "In this book: '⊢_M' (also printed as a turnstile with subscript M) is read 'yields in one step' "
            "and '⊢*_M' is read 'yields'; '⇒_G' is read 'derives in one step' and '⇒*_G' is read 'derives'; "
            "'⇒*_L' and '⇒*_R' are read 'derives by a leftmost derivation' and 'derives by a rightmost "
            "derivation'; in a rule 'A → w' the arrow is read 'goes to'; 'e' (or ε) on its own is 'the empty "
            "string'; '≡_M' is read 'is equivalent with respect to M to'."
        ),
        # Running headers the layout detector sometimes keeps as titles:
        # "2.1: Deterministic Finite Automata", "Chapter 2: FINITE AUTOMATA",
        # bare page numbers.
        "drop_patterns": [r"^\d+\.\d+:\s", r"^Chapter \d+:", r"^\d{1,3}$"],
    },
}
