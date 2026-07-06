"""Central config for the splicer + classifier prototype.

Everything that is hardcoded "for now" lives here so the next step (context
mapping) only has to change one file.
"""
from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# --- Input PDF + page range -------------------------------------------------
# The test textbook kept in the repo, and the page range we're focusing on.
# These page numbers are 1-based and INCLUSIVE (i.e. 46..54 = 9 pages), matching
# how a human reads "pages 46 to 54". The splicer converts to 0-based indices.
PDF_PATH = PROJECT_ROOT / "Operating Systems - Three Easy Pieces.pdf"
PAGE_START = 46  # inclusive, 1-based
PAGE_END = 54    # inclusive, 1-based

# --- Classifier model -------------------------------------------------------
# The classification is trivial (chunk-vs-figure + a subcategory), so a small
# local model run through Ollama is plenty -- free, no key, no billing, and it
# fits the 4 GB-VRAM floor from the ideation doc. Qwen3 4B has the most reliable
# structured-output behaviour in this size class; swap in "qwen3:1.7b" for a
# lighter/faster option (remember to `ollama pull` whichever you choose).
MODEL = "qwen3:4b"
OLLAMA_HOST = "http://localhost:11434"  # default local Ollama endpoint

# --- Layout detection (v2) --------------------------------------------------
# DocLayout-YOLO (YOLOv10) does document layout segmentation on a rendered page
# image -- it gives us semantic regions (title / plain text / figure /
# figure_caption / table / ...) that replace v1's brittle geometry heuristics.
# Weights are pulled once from HuggingFace and cached; inference runs on CPU here
# (the installed torch is a CPU build), so this stage adds no GPU load.
YOLO_REPO = "juliozhao/DocLayout-YOLO-DocStructBench"
YOLO_WEIGHTS = "doclayout_yolo_docstructbench_imgsz1024.pt"
YOLO_IMGSZ = 1024          # detector input size
YOLO_CONF = 0.20           # detection confidence floor
YOLO_DEVICE = "cpu"        # "cpu" or e.g. "cuda:0"
RENDER_ZOOM = 2.0          # page -> image scale (2.0 ~= 144 dpi)

# --- Output -----------------------------------------------------------------
OUTPUT_DIR = PROJECT_ROOT / "output"
