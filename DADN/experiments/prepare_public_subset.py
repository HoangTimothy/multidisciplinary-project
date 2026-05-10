#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import urllib.request
from pathlib import Path
from typing import Any, Optional


TARGET_LABELS = {
    "person": "person",
    "pedestrian": "person",
    "rider": "person",
    "bicycle": "vehicle",
    "motorcycle": "vehicle",
    "car": "vehicle",
    "bus": "vehicle",
    "train": "vehicle",
    "truck": "vehicle",
    "chair": "static_obstacle",
    "bench": "static_obstacle",
    "backpack": "static_obstacle",
    "suitcase": "static_obstacle",
}


def copy_or_link(src: Path, dst: Path, mode: str) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        return
    if mode == "symlink":
        dst.symlink_to(src.resolve())
    else:
        shutil.copy2(src, dst)


def download_url(url: str, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        return
    with urllib.request.urlopen(url) as response, dst.open("wb") as handle:
        shutil.copyfileobj(response, handle)


def zone_from_bbox(x: float, w: float, image_width: float) -> str:
    center = (x + w / 2) / max(image_width, 1)
    if center < 0.33:
        return "bên trái"
    if center > 0.67:
        return "bên phải"
    return "giữa"


def distance_from_bbox(w: float, h: float, image_width: float, image_height: float) -> str:
    area_ratio = (w * h) / max(image_width * image_height, 1)
    if area_ratio >= 0.18:
        return "gần"
    if area_ratio >= 0.06:
        return "trung bình"
    return "xa"


def best_expected(candidates: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    if not candidates:
        return None
    return max(candidates, key=lambda item: (item["area_ratio"], item["priority"]))


def expected_payload(expected: dict[str, Any], detail: str) -> dict[str, Any]:
    payload = {
        "expected_alert": expected["expected_alert"],
        "expected_group": expected["expected_group"],
    }
    if detail in {"zone", "all"}:
        payload["expected_zone"] = expected["expected_zone"]
    if detail in {"distance", "all"}:
        payload["expected_distance"] = expected["expected_distance"]
    return payload


def prepare_coco(
    images_dir: Optional[Path],
    annotations_path: Path,
    output_dir: Path,
    labels: dict[str, dict[str, Any]],
    max_items: int,
    mode: str,
    image_url_template: Optional[str] = None,
    label_detail: str = "group",
) -> int:
    payload = json.loads(annotations_path.read_text(encoding="utf-8"))
    categories = {item["id"]: item["name"] for item in payload.get("categories", [])}
    images = {item["id"]: item for item in payload.get("images", [])}
    per_image: dict[int, list[dict[str, Any]]] = {}

    for ann in payload.get("annotations", []):
        label = categories.get(ann.get("category_id"))
        group = TARGET_LABELS.get(label)
        if group is None:
            continue
        image = images.get(ann.get("image_id"))
        if image is None:
            continue
        x, y, w, h = ann.get("bbox", [0, 0, 0, 0])
        area_ratio = (w * h) / max(image["width"] * image["height"], 1)
        per_image.setdefault(image["id"], []).append(
            {
                "expected_alert": True,
                "expected_group": group,
                "expected_zone": zone_from_bbox(x, w, image["width"]),
                "expected_distance": distance_from_bbox(w, h, image["width"], image["height"]),
                "source_label": label,
                "area_ratio": area_ratio,
                "priority": 2 if group in {"person", "vehicle"} else 1,
            }
        )

    emitted = 0
    for image_id in sorted(per_image):
        if emitted >= max_items:
            break
        image = images[image_id]
        dst_name = f"coco_{image['file_name']}"
        dst = output_dir / dst_name
        src = images_dir / image["file_name"] if images_dir is not None else None
        if src is not None and src.exists():
            copy_or_link(src, dst, mode)
        elif image_url_template:
            download_url(image_url_template.format(file_name=image["file_name"]), dst)
        else:
            continue
        expected = best_expected(per_image[image_id])
        if expected is not None:
            labels[dst_name] = expected_payload(expected, label_detail)
        emitted += 1
    return emitted


def prepare_bdd_fiftyone(
    samples_path: Path,
    output_dir: Path,
    labels: dict[str, dict[str, Any]],
    max_items: int,
    mode: str,
    images_dir: Optional[Path] = None,
    hf_repo: Optional[str] = None,
    label_detail: str = "group",
) -> int:
    payload = json.loads(samples_path.read_text(encoding="utf-8"))
    samples = payload.get("samples", payload if isinstance(payload, list) else [])
    emitted = 0
    for item in samples:
        if emitted >= max_items:
            break
        filepath = Path(item["filepath"])
        candidates: list[dict[str, Any]] = []
        metadata = item.get("metadata", {})
        image_width = metadata.get("width", 1280)
        image_height = metadata.get("height", 720)
        for ann in item.get("detections", {}).get("detections", []):
            group = TARGET_LABELS.get(ann.get("label"))
            box = ann.get("bounding_box")
            if group is None or box is None:
                continue
            x_norm, y_norm, w_norm, h_norm = box
            x, w = x_norm * image_width, w_norm * image_width
            h = h_norm * image_height
            candidates.append(
                {
                    "expected_alert": True,
                    "expected_group": group,
                    "expected_zone": zone_from_bbox(x, w, image_width),
                    "expected_distance": distance_from_bbox(w, h, image_width, image_height),
                    "area_ratio": max(0, w_norm) * max(0, h_norm),
                    "priority": 2 if group in {"person", "vehicle"} else 1,
                }
            )
        expected = best_expected(candidates)
        if expected is None:
            continue

        dst_name = f"bdd_{filepath.name}"
        dst = output_dir / dst_name
        src = images_dir / filepath.name if images_dir is not None else None
        if src is not None and src.exists():
            copy_or_link(src, dst, mode)
        elif hf_repo:
            url = f"https://huggingface.co/datasets/{hf_repo}/resolve/main/{filepath.as_posix()}"
            download_url(url, dst)
        else:
            continue

        labels[dst_name] = expected_payload(expected, label_detail)
        emitted += 1
    return emitted


def prepare_bdd(
    images_dir: Path,
    labels_path: Path,
    output_dir: Path,
    labels: dict[str, dict[str, Any]],
    max_items: int,
    mode: str,
    label_detail: str = "group",
) -> int:
    payload = json.loads(labels_path.read_text(encoding="utf-8"))
    emitted = 0
    for item in payload:
        if emitted >= max_items:
            break
        src = images_dir / item["name"]
        if not src.exists():
            continue
        candidates: list[dict[str, Any]] = []
        for ann in item.get("labels", []):
            group = TARGET_LABELS.get(ann.get("category"))
            box = ann.get("box2d")
            if group is None or box is None:
                continue
            x1, y1, x2, y2 = box["x1"], box["y1"], box["x2"], box["y2"]
            w, h = max(0, x2 - x1), max(0, y2 - y1)
            image_width = item.get("width", 1280)
            image_height = item.get("height", 720)
            candidates.append(
                {
                    "expected_alert": True,
                    "expected_group": group,
                    "expected_zone": zone_from_bbox(x1, w, image_width),
                    "expected_distance": distance_from_bbox(w, h, image_width, image_height),
                    "area_ratio": (w * h) / max(image_width * image_height, 1),
                    "priority": 2 if group in {"person", "vehicle"} else 1,
                }
            )
        expected = best_expected(candidates)
        if expected is None:
            continue
        dst_name = f"bdd_{item['name']}"
        copy_or_link(src, output_dir / dst_name, mode)
        labels[dst_name] = expected_payload(expected, label_detail)
        emitted += 1
    return emitted


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare a small COCO/BDD subset for DADN benchmarks")
    parser.add_argument("--output-dir", type=Path, required=True, help="Output image directory")
    parser.add_argument("--labels-out", type=Path, required=True, help="Output labels JSON")
    parser.add_argument("--mode", choices=["copy", "symlink"], default="symlink")
    parser.add_argument("--max-coco", type=int, default=250)
    parser.add_argument("--max-bdd", type=int, default=250)
    parser.add_argument(
        "--label-detail",
        choices=["group", "zone", "distance", "all"],
        default="group",
        help="Ground-truth fields to emit. Public COCO/BDD benchmarks should use group-level labels.",
    )
    parser.add_argument("--coco-images", type=Path, help="COCO val/train image directory")
    parser.add_argument("--coco-annotations", type=Path, help="COCO instances JSON")
    parser.add_argument(
        "--coco-image-url-template",
        default="http://images.cocodataset.org/val2017/{file_name}",
        help="URL template used when --coco-images does not contain a selected file",
    )
    parser.add_argument("--bdd-images", type=Path, help="BDD100K image directory")
    parser.add_argument("--bdd-labels", type=Path, help="BDD100K detection labels JSON")
    parser.add_argument("--bdd-fiftyone-samples", type=Path, help="FiftyOne samples.json with BDD detections")
    parser.add_argument(
        "--bdd-hf-repo",
        default=None,
        help="Optional Hugging Face dataset repo used to fetch BDD images from sample filepaths",
    )
    args = parser.parse_args()

    labels: dict[str, dict[str, Any]] = {}
    counts: dict[str, int] = {}
    args.output_dir.mkdir(parents=True, exist_ok=True)
    args.labels_out.parent.mkdir(parents=True, exist_ok=True)

    if args.coco_annotations:
        counts["coco"] = prepare_coco(
            args.coco_images,
            args.coco_annotations,
            args.output_dir,
            labels,
            args.max_coco,
            args.mode,
            args.coco_image_url_template,
            args.label_detail,
        )
    if args.bdd_images and args.bdd_labels:
        counts["bdd"] = prepare_bdd(
            args.bdd_images,
            args.bdd_labels,
            args.output_dir,
            labels,
            args.max_bdd,
            args.mode,
            args.label_detail,
        )
    if args.bdd_fiftyone_samples:
        counts["bdd_fiftyone"] = prepare_bdd_fiftyone(
            args.bdd_fiftyone_samples,
            args.output_dir,
            labels,
            args.max_bdd,
            args.mode,
            args.bdd_images,
            args.bdd_hf_repo,
            args.label_detail,
        )

    args.labels_out.write_text(
        json.dumps({"source_counts": counts, "items": labels}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"[OK] Prepared {len(labels)} labeled item(s): {args.output_dir}")
    print(f"[OK] Wrote labels: {args.labels_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
