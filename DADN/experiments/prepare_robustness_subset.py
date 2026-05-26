#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import hashlib
from pathlib import Path
from typing import Any

import cv2
import numpy as np


IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
DEFAULT_VARIANTS = (
    "motion_blur",
    "noise",
    "low_light",
    "jpeg_low_quality",
    "center_occlusion",
    "esp32_resize",
)


def load_labels(path: Path | None) -> dict[str, dict[str, Any]]:
    if path is None or not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict) and "items" in payload:
        payload = payload["items"]
    if isinstance(payload, list):
        return {str(item["id"]): item for item in payload}
    return {str(key): value for key, value in payload.items()}


def image_files(path: Path) -> list[Path]:
    if path.is_file():
        return [path] if path.suffix.lower() in IMAGE_EXTS else []
    return sorted(
        item
        for item in path.rglob("*")
        if item.is_file() and item.suffix.lower() in IMAGE_EXTS
    )


def label_for(labels: dict[str, dict[str, Any]], image_path: Path) -> dict[str, Any]:
    return dict(labels.get(image_path.name) or labels.get(image_path.stem) or {})


def stable_seed(*parts: str, base_seed: int = 42) -> int:
    payload = "::".join((str(base_seed), *parts)).encode("utf-8")
    digest = hashlib.blake2b(payload, digest_size=8).digest()
    return int.from_bytes(digest, "little", signed=False)


def motion_blur(image: np.ndarray, rng: np.random.Generator, severity: int) -> np.ndarray:
    size = {1: 7, 2: 9, 3: 13}.get(severity, 9)
    kernel = np.zeros((size, size), dtype=np.float32)
    direction = rng.choice(["horizontal", "vertical", "diag_l", "diag_r"])
    if direction == "horizontal":
        kernel[size // 2, :] = 1.0 / size
    elif direction == "vertical":
        kernel[:, size // 2] = 1.0 / size
    elif direction == "diag_l":
        np.fill_diagonal(kernel, 1.0 / size)
    else:
        np.fill_diagonal(np.fliplr(kernel), 1.0 / size)
    return cv2.filter2D(image, -1, kernel)


def noise(image: np.ndarray, rng: np.random.Generator, severity: int) -> np.ndarray:
    sigma = {1: 12.0, 2: 18.0, 3: 28.0}.get(severity, 18.0)
    noisy = image.astype(np.int16) + rng.normal(0, sigma, image.shape).astype(np.int16)
    return np.clip(noisy, 0, 255).astype(np.uint8)


def low_light(image: np.ndarray, rng: np.random.Generator, severity: int) -> np.ndarray:
    brightness = {1: 0.62, 2: 0.48, 3: 0.34}.get(severity, 0.48)
    gamma = {1: 1.2, 2: 1.4, 3: 1.8}.get(severity, 1.4)
    dark = cv2.convertScaleAbs(image, alpha=brightness, beta=int(rng.integers(-4, 5)))
    table = np.array([((i / 255.0) ** gamma) * 255 for i in range(256)]).astype("uint8")
    return cv2.LUT(dark, table)


def jpeg_low_quality(image: np.ndarray, rng: np.random.Generator, severity: int) -> np.ndarray:
    quality = {1: 40, 2: 32, 3: 20}.get(severity, 32)
    quality = int(np.clip(quality + rng.integers(-4, 5), 10, 60))
    ok, encoded = cv2.imencode(".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    if not ok:
        return image
    decoded = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
    return decoded if decoded is not None else image


def center_occlusion(image: np.ndarray, rng: np.random.Generator, severity: int) -> np.ndarray:
    result = image.copy()
    height, width = result.shape[:2]
    scale = {1: 0.18, 2: 0.24, 3: 0.32}.get(severity, 0.24)
    box_w = max(12, int(width * scale))
    box_h = max(12, int(height * (scale + 0.08)))
    center_x = int(width * 0.5 + rng.integers(-width * 0.03, width * 0.03 + 1))
    center_y = int(height * 0.53 + rng.integers(-height * 0.03, height * 0.03 + 1))
    x1 = int(np.clip(center_x - box_w // 2, 0, width - 1))
    y1 = int(np.clip(center_y - box_h // 2, 0, height - 1))
    x2 = int(np.clip(x1 + box_w, 0, width))
    y2 = int(np.clip(y1 + box_h, 0, height))
    cv2.rectangle(result, (x1, y1), (x2, y2), (35, 35, 35), thickness=-1)
    return result


def esp32_resize(image: np.ndarray, rng: np.random.Generator, severity: int) -> np.ndarray:
    height, width = image.shape[:2]
    small_w, small_h = {
        1: (320, 240),
        2: (240, 180),
        3: (160, 120),
    }.get(severity, (320, 240))
    small = cv2.resize(image, (small_w, small_h), interpolation=cv2.INTER_AREA)
    if rng.random() < 0.4:
        small = cv2.GaussianBlur(small, (3, 3), 0)
    return cv2.resize(small, (width, height), interpolation=cv2.INTER_LINEAR)


TRANSFORMS = {
    "motion_blur": motion_blur,
    "noise": noise,
    "low_light": low_light,
    "jpeg_low_quality": jpeg_low_quality,
    "center_occlusion": center_occlusion,
    "esp32_resize": esp32_resize,
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Create synthetic robustness images for DADN risk benchmarking")
    parser.add_argument("--input", type=Path, required=True, help="Input image file or directory")
    parser.add_argument("--labels", type=Path, default=None, help="Optional source labels JSON")
    parser.add_argument("--output", type=Path, required=True, help="Output image directory")
    parser.add_argument("--labels-out", type=Path, required=True, help="Output labels JSON")
    parser.add_argument("--max-images", type=int, default=None, help="Optional cap before augmentation")
    parser.add_argument(
        "--variant",
        action="append",
        choices=sorted(TRANSFORMS),
        help="Variant to generate; may be repeated. Defaults to all variants.",
    )
    parser.add_argument("--severity", type=int, choices=[1, 2, 3], default=2, help="Augmentation severity level")
    parser.add_argument("--seed", type=int, default=42, help="Base seed for deterministic augmentation")
    args = parser.parse_args()

    files = image_files(args.input)
    if args.max_images is not None:
        files = files[: args.max_images]
    if not files:
        raise SystemExit(f"No supported images found: {args.input}")

    labels = load_labels(args.labels)
    variants = args.variant or list(DEFAULT_VARIANTS)
    args.output.mkdir(parents=True, exist_ok=True)
    args.labels_out.parent.mkdir(parents=True, exist_ok=True)

    output_items: list[dict[str, Any]] = []
    for image_path in files:
        image = cv2.imread(str(image_path))
        if image is None:
            continue
        source_label = label_for(labels, image_path)
        for variant in variants:
            rng = np.random.default_rng(stable_seed(image_path.name, variant, base_seed=args.seed))
            transformed = TRANSFORMS[variant](image, rng, args.severity)
            item_id = f"{image_path.stem}__{variant}.jpg"
            out_path = args.output / item_id
            cv2.imwrite(str(out_path), transformed, [int(cv2.IMWRITE_JPEG_QUALITY), 85])

            item = {
                "id": item_id,
                "source_id": source_label.get("id", image_path.name),
                "variant": variant,
                "expected_alert": source_label.get("expected_alert", True),
                "expected_group": source_label.get("expected_group") or source_label.get("group"),
                "expected_zone": source_label.get("expected_zone") or source_label.get("zone"),
                "expected_distance": source_label.get("expected_distance") or source_label.get("distance"),
                "failure_type": variant,
            }
            output_items.append({key: value for key, value in item.items() if value is not None})

    args.labels_out.write_text(
        json.dumps({"items": output_items}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"[OK] Wrote {len(output_items)} robustness images to {args.output}")
    print(f"[OK] Wrote labels to {args.labels_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
