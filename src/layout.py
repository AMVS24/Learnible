"""Stage 2 (v2): document layout detection with DocLayout-YOLO.

`LayoutDetector.detect(pdf_path, start, end)` renders each page in the range,
runs the detector, and returns the semantic `Region`s (title / plain text /
figure / figure_caption / table / abandon / ...) in reading order, each with the
PDF text found inside its box.

This replaces v1's geometry heuristics (paragraph splitting, diagram clustering,
caption geometry). PyMuPDF is still used, but only for rendering the page image
and for the inverse "text inside a box" lookup. Runs on CPU (see config).
"""
from __future__ import annotations

import fitz  # PyMuPDF
import numpy as np

from . import config
from .models import BBox, Region

# Background lighter than this (mean of the non-text pixels) is "white"; darker
# means the region sits on a shaded panel -- a callout/sidebar box. Book-agnostic:
# it reads the shading off the rendered page, not any keyword.
_SHADE_WHITE = 245

# Font-name fragments that imply a monospace face (the mono flag bit is often
# absent even on embedded monospace fonts, e.g. NimbusMon in OSTEP). Kept in
# sync with the v1 splicer heuristic.
_MONO_NAMES = ("mono", "courier", "consol", "menlo", "nimbusmon", "cmtt", "txtt")


class LayoutDetector:
    """Thin wrapper around the DocLayout-YOLO model. The model is heavy to load,
    so it is loaded once (lazily) and reused across pages."""

    def __init__(self) -> None:
        self._model = None
        self._names: dict[int, str] = {}

    def _ensure_model(self) -> None:
        if self._model is not None:
            return
        # Imported lazily so that importing this module (e.g. for the Region
        # type) does not pull in torch until detection is actually run.
        from doclayout_yolo import YOLOv10
        from huggingface_hub import hf_hub_download

        weights = hf_hub_download(config.YOLO_REPO, config.YOLO_WEIGHTS)
        self._model = YOLOv10(weights)
        self._names = self._model.names

    def detect(self, pdf_path: str, start: int, end: int) -> list[Region]:
        """Detect regions on pages `start..end` (1-based inclusive). Returns a
        flat list of `Region`s in global reading order (page, then top-to-bottom,
        then left-to-right)."""
        self._ensure_model()
        doc = fitz.open(pdf_path)
        regions: list[Region] = []
        idx = 0
        try:
            for page_no in range(start, end + 1):
                fi = page_no - 1  # fitz is 0-based
                if fi < 0 or fi >= len(doc):
                    continue
                page = doc[fi]
                for bbox, cls, conf, shaded in self._detect_page(page):
                    text, mono = _text_and_mono(page, bbox)
                    regions.append(
                        Region(page=page_no, index=idx, bbox=bbox, cls=cls,
                               confidence=conf, text=text, mono=mono, shaded=shaded)
                    )
                    idx += 1
        finally:
            doc.close()
        return regions

    def _detect_page(self, page: "fitz.Page") -> list[tuple[BBox, str, float, bool]]:
        """Run the detector on one page; return (bbox_in_pdf_points, cls, conf,
        shaded), sorted in reading order."""
        zoom = config.RENDER_ZOOM
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
        # DocLayout-YOLO accepts a numpy image; build one from the pixmap.
        img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
            pix.height, pix.width, pix.n
        )
        if pix.n == 4:            # RGBA -> RGB
            img = img[:, :, :3]
        res = self._model.predict(
            img, imgsz=config.YOLO_IMGSZ, conf=config.YOLO_CONF,
            device=config.YOLO_DEVICE, verbose=False,
        )[0]
        out: list[tuple[BBox, str, float, bool]] = []
        for b in res.boxes:
            cid = int(b.cls[0])
            conf = float(b.conf[0])
            x0, y0, x1, y1 = (float(v) / zoom for v in b.xyxy[0])  # img px -> pts
            shaded = _region_shaded(img, (x0, y0, x1, y1), zoom)
            out.append(((x0, y0, x1, y1), self._names[cid], conf, shaded))
        out = _dedup_same_class(out)
        # reading order: top-to-bottom, then left-to-right (single-column book)
        out.sort(key=lambda r: (round(r[0][1] / 5), r[0][0]))
        return out


def _region_shaded(img: "np.ndarray", bbox: BBox, zoom: float) -> bool:
    """True if the region's background is a shaded panel rather than white paper.
    Samples the light (non-glyph) pixels inside the box and checks their median
    colour -- gray/tinted => a callout/sidebar box."""
    x0, y0, x1, y1 = bbox
    crop = img[max(0, int(y0 * zoom)):int(y1 * zoom),
               max(0, int(x0 * zoom)):int(x1 * zoom)]
    if crop.size == 0:
        return False
    flat = crop.reshape(-1, crop.shape[-1])[:, :3]
    light = flat[flat.min(axis=1) > 120]          # drop dark text glyphs
    if len(light) == 0:
        return False
    return bool(np.mean(np.median(light, axis=0)) < _SHADE_WHITE)


def _iou(a: BBox, b: BBox) -> float:
    ix0, iy0 = max(a[0], b[0]), max(a[1], b[1])
    ix1, iy1 = min(a[2], b[2]), min(a[3], b[3])
    iw, ih = max(0.0, ix1 - ix0), max(0.0, iy1 - iy0)
    inter = iw * ih
    if inter == 0:
        return 0.0
    area_a = (a[2] - a[0]) * (a[3] - a[1])
    area_b = (b[2] - b[0]) * (b[3] - b[1])
    return inter / (area_a + area_b - inter)


def _dedup_same_class(
    dets: list[tuple[BBox, str, float, bool]], iou_thresh: float = 0.6
) -> list[tuple[BBox, str, float, bool]]:
    """Drop overlapping detections of the *same* class, keeping the higher-conf
    one. Cross-class overlaps (e.g. figure vs. table on one diagram) are left for
    the figure stage to tie-break."""
    kept: list[tuple[BBox, str, float, bool]] = []
    for det in sorted(dets, key=lambda d: d[2], reverse=True):  # high conf first
        if any(
            det[1] == k[1] and _iou(det[0], k[0]) >= iou_thresh for k in kept
        ):
            continue
        kept.append(det)
    return kept


def _text_and_mono(page: "fitz.Page", bbox: BBox) -> tuple[str, bool]:
    """Extract the text inside `bbox` and whether its body is monospace."""
    rect = fitz.Rect(*bbox)
    d = page.get_text("dict", clip=rect)
    parts: list[str] = []
    mono_chars = total_chars = 0
    for block in d.get("blocks", []):
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                s = span.get("text", "")
                parts.append(s)
                n = len(s.replace(" ", ""))
                total_chars += n
                if any(k in span.get("font", "").lower() for k in _MONO_NAMES):
                    mono_chars += n
    text = " ".join("".join(parts).split())
    mono = total_chars > 0 and mono_chars / total_chars > 0.5
    return text, mono
