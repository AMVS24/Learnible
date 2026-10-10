"""One-step setup for the Learnible pipeline on any machine.

    python setup_env.py              # everything
    python setup_env.py --cpu        # force a CPU-only PyTorch
    python setup_env.py --skip-ollama --skip-web

Run it with the Python you'll use for the project (3.11, ideally in a fresh
venv / conda env). Steps:

  1. PyTorch 2.11 for this machine: CUDA 12.8 build if an NVIDIA GPU is found
     (needed for RTX 50-series), the default build on macOS, otherwise CPU.
  2. requirements.txt (pinned, known-good versions).
  3. chatterbox-tts with --no-deps (it pins torch==2.6).
  4. Ollama models from ollama-models.txt -- needs Ollama itself installed
     (https://ollama.com/download); skipped with a message if it isn't.
  5. The web app's npm packages (web/), if Node.js is installed.
"""
from __future__ import annotations

import argparse
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TORCH = ["torch==2.11.0", "torchaudio==2.11.0", "torchvision==0.26.0"]
CHATTERBOX = "chatterbox-tts==0.1.7"


def run(cmd: list[str], **kw) -> None:
    print("\n$ " + " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True, **kw)


def pip(*args: str) -> None:
    run([sys.executable, "-m", "pip", "install", *args])


def has_nvidia_gpu() -> bool:
    if not shutil.which("nvidia-smi"):
        return False
    try:
        return subprocess.run(["nvidia-smi", "-L"], capture_output=True, text=True, timeout=20).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def install_torch(force_cpu: bool) -> None:
    if platform.system() == "Darwin":
        print("macOS: default PyTorch build (CPU / Apple GPU).")
        pip(*TORCH)
    elif has_nvidia_gpu() and not force_cpu:
        print("NVIDIA GPU found: CUDA 12.8 PyTorch build.")
        pip(*TORCH, "--index-url", "https://download.pytorch.org/whl/cu128")
    else:
        print("No NVIDIA GPU (or --cpu): CPU-only PyTorch build. TTS will be slow.")
        pip(*TORCH, "--index-url", "https://download.pytorch.org/whl/cpu")


def pull_ollama_models() -> None:
    models = [l.split("#")[0].strip() for l in (ROOT / "ollama-models.txt").read_text(encoding="utf-8").splitlines()]
    models = [m for m in models if m]
    exe = shutil.which("ollama")
    if not exe:
        print("\nOllama isn't installed, so these models weren't pulled: " + ", ".join(models))
        print("Install it from https://ollama.com/download, then run:  python setup_env.py --only-ollama")
        return
    for m in models:
        run([exe, "pull", m])


def install_web() -> None:
    npm = shutil.which("npm")
    if not npm:
        print("\nNode.js / npm not found -- skipping the web app (install Node 20+ and run `npm ci` in web/).")
        return
    run([npm, "ci"], cwd=ROOT / "web")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cpu", action="store_true", help="install the CPU-only PyTorch even if a GPU is present")
    ap.add_argument("--skip-ollama", action="store_true", help="don't pull Ollama models")
    ap.add_argument("--skip-web", action="store_true", help="don't install the web app's npm packages")
    ap.add_argument("--only-ollama", action="store_true", help="only pull the Ollama models")
    args = ap.parse_args()

    if sys.version_info[:2] != (3, 11):
        print(f"Note: tested with Python 3.11; this is {platform.python_version()}.")

    if args.only_ollama:
        pull_ollama_models()
        return 0

    pip("--upgrade", "pip")
    install_torch(args.cpu)
    pip("-r", str(ROOT / "requirements.txt"))
    pip("--no-deps", CHATTERBOX)
    if not args.skip_ollama:
        pull_ollama_models()
    if not args.skip_web:
        install_web()

    import importlib
    for mod in ("fitz", "doclayout_yolo", "chatterbox.tts", "soundfile", "ollama"):
        importlib.import_module(mod)
    import torch
    print(f"\nDone. torch {torch.__version__}, CUDA available: {torch.cuda.is_available()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
