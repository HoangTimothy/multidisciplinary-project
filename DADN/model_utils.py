from __future__ import annotations

import urllib.request
from pathlib import Path

from config import MODEL_DIR, MODEL_PATH, MODEL_URL


def ensure_model() -> Path:
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    if MODEL_PATH.exists():
        return MODEL_PATH

    print(f"[INFO] Downloading model to {MODEL_PATH} ...")
    urllib.request.urlretrieve(MODEL_URL, MODEL_PATH)
    print("[OK] Model downloaded.")
    return MODEL_PATH
