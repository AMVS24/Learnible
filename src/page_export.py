"""Export a full-page PNG for every page in the spliced range, for the web
reader's "reading mode" -- it shows the actual PDF page (diagrams, layout,
everything) with a highlight box drawn over the currently-active chunk, not a
reflowed wall of text. A chunk's `bbox` (already carried on every `TextBlock`)
is in PDF point space, so the page's point-space size is exported alongside
each image; the frontend positions overlays as percentages of that size,
which is resolution-independent (no need to match the PNG's pixel dims).
"""
from __future__ import annotations

from pathlib import Path

import fitz  # PyMuPDF

PAGE_ZOOM = 2.0  # matches LayoutDetector.RENDER_ZOOM; plenty sharp for on-screen reading


def export_page_images(pdf_path: str, start: int, end: int, out_dir: Path) -> dict[int, dict]:
    """Writes `<out_dir>/page_<n>.png` for pages `start..end` (1-based
    inclusive). Returns {page number -> {"image": filename, "width": pt,
    "height": pt}} (width/height in PDF points, the same space `bbox` uses)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(pdf_path)
    pages: dict[int, dict] = {}
    try:
        for page_no in range(start, end + 1):
            fi = page_no - 1
            if fi < 0 or fi >= len(doc):
                continue
            page = doc[fi]
            pix = page.get_pixmap(matrix=fitz.Matrix(PAGE_ZOOM, PAGE_ZOOM))
            filename = f"page_{page_no}.png"
            pix.save(str(out_dir / filename))
            pages[page_no] = {
                "image": filename,
                "width": round(page.rect.width, 1),
                "height": round(page.rect.height, 1),
            }
    finally:
        doc.close()
    return pages
