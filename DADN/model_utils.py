from __future__ import annotations

import urllib.request
from pathlib import Path

from config import MODEL_DIR, MODEL_PATH, MODEL_URL


def ensure_model(model_path: Path | None = None, model_url: str | None = None) -> Path:
    target_path = model_path or MODEL_PATH
    source_url = model_url or MODEL_URL
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    if target_path.exists():
        return target_path

    print(f"[INFO] Downloading model to {target_path} ...")
    urllib.request.urlretrieve(source_url, target_path)
    print("[OK] Model downloaded.")
    return target_path
