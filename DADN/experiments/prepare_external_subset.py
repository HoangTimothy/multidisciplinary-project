#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import urllib.request
from pathlib import Path
from typing import Any, Iterable


ZENODO_10781048_FILES = {
    "Corridor_marked.csv": "https://zenodo.org/api/records/10781048/files/Corridor_marked.csv/content",
    "RoomL_marked.csv": "https://zenodo.org/api/records/10781048/files/RoomL_marked.csv/content",
    "Office_marked.csv": "https://zenodo.org/api/records/10781048/files/Office_marked.csv/content",
    "Corridor_RoomL_Office_marked.csv": "https://zenodo.org/api/records/10781048/files/Corridor_RoomL_Office_marked.csv/content",
}

GROUP_ALIASES = {
    "person": "person",
    "pedestrian": "person",
    "people": "person",
    "bicycle": "vehicle",
    "bike": "vehicle",
    "motorcycle": "vehicle",
    "car": "vehicle",
    "bus": "vehicle",
    "truck": "vehicle",
    "vehicle": "vehicle",
    "chair": "static_obstacle",
    "bench": "static_obstacle",
    "table": "static_obstacle",
    "dining table": "static_obstacle",
    "couch": "static_obstacle",
    "sofa": "static_obstacle",
    "suitcase": "static_obstacle",
    "backpack": "static_obstacle",
    "obstacle": "static_obstacle",
}


def zone_from_bbox(x: float, w: float, image_width: float) -> str:
    center = (x + w / 2) / max(image_width, 1)
    if center < 0.33:
        return "bên trái"
    if center > 0.67:
        return "bên phải"
    return "giữa"


def distance_from_depth(depth: float | None) -> str | None:
    if depth is None:
        return None
    if depth <= 2.0:
        return "gần"
    if depth <= 5.0:
        return "trung bình"
    return "xa"


def normalize_group(label: str | None) -> str | None:
    if not label:
        return None
    return GROUP_ALIASES.get(label.strip().lower(), "other")


def save_image(image: Any, path: Path) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        return True
    try:
        image.save(path)
        return True
    except Exception:
        return False


def bbox_fields(
    bbox: Iterable[float] | None,
    *,
    image_width: int,
    image_height: int,
    depth: float | None = None,
) -> dict[str, Any]:
    if not bbox:
        return {}
    values = list(bbox)
    if len(values) != 4:
        return {}
    x, y, w, h = values
    if 0 <= x <= 1 and 0 <= w <= 1:
        x *= image_width
        w *= image_width
    if 0 <= y <= 1 and 0 <= h <= 1:
        y *= image_height
        h *= image_height
    payload: dict[str, Any] = {
        "expected_zone": zone_from_bbox(float(x), float(w), image_width),
    }
    distance = distance_from_depth(depth)
    if distance:
        payload["expected_distance"] = distance
    return payload


def prepare_guidedog(args: argparse.Namespace) -> int:
    try:
        from datasets import load_dataset
    except Exception as exc:
        raise SystemExit(f"Install Hugging Face datasets first: {exc}") from exc

    args.output_dir.mkdir(parents=True, exist_ok=True)
    args.labels_out.parent.mkdir(parents=True, exist_ok=True)

    try:
        dataset = load_dataset("kjunh/GuideDog", args.config, split=args.split, streaming=True)
    except Exception as exc:
        raise SystemExit(
            "Could not load kjunh/GuideDog. The dataset is gated; log in with "
            "`huggingface-cli login` and accept the dataset terms, then rerun. "
            f"Original error: {exc}"
        ) from exc

    labels: dict[str, dict[str, Any]] = {}
    emitted = 0
    for idx, item in enumerate(dataset):
        if emitted >= args.max_items:
            break
        image = item.get("image")
        if image is None:
            continue

        if args.config == "object":
            raw_label = item.get("answer") or item.get("answer_raw")
            bbox = item.get("answer_bbox") or item.get("answer_ratio_bbox")
            depth = item.get("answer_depth")
            failure_type = "guidedog_object"
        elif args.config == "depth":
            raw_label = item.get("closer") or item.get("closer_raw")
            bbox = item.get("closer_bbox") or item.get("closer_ratio_bbox")
            depth = item.get("closer_depth")
            failure_type = "guidedog_depth_closer"
        else:
            raw_label = None
            bbox = None
            depth = None
            failure_type = "guidedog_guidance"

        image_id = str(item.get("id") or f"guidedog_{args.config}_{idx:06d}")
        filename = f"{image_id}.jpg".replace("/", "_")
        if not save_image(image.convert("RGB"), args.output_dir / filename):
            continue

        expected: dict[str, Any] = {
            "expected_alert": True,
            "failure_type": failure_type,
            "source_dataset": "kjunh/GuideDog",
        }
        group = normalize_group(raw_label)
        if group and not args.risk_only:
            expected["expected_group"] = group
        if bbox and not args.risk_only:
            expected.update(
                bbox_fields(
                    bbox,
                    image_width=image.width,
                    image_height=image.height,
                    depth=float(depth) if depth is not None else None,
                )
            )
        labels[filename] = expected
        emitted += 1

    args.labels_out.write_text(
        json.dumps({"source": "kjunh/GuideDog", "config": args.config, "items": labels}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"[OK] Prepared {len(labels)} GuideDog image item(s): {args.output_dir}")
    print(f"[OK] Wrote labels: {args.labels_out}")
    return 0


def download_url(url: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        return
    with urllib.request.urlopen(url) as response, path.open("wb") as handle:
        shutil.copyfileobj(response, handle)


def prepare_zenodo_sensor(args: argparse.Namespace) -> int:
    import pandas as pd

    args.output_dir.mkdir(parents=True, exist_ok=True)
    args.labels_out.parent.mkdir(parents=True, exist_ok=True)
    csv_name = args.file
    if csv_name not in ZENODO_10781048_FILES:
        raise SystemExit(f"Unknown Zenodo file: {csv_name}. Choices: {', '.join(ZENODO_10781048_FILES)}")

    csv_path = args.output_dir / csv_name
    download_url(ZENODO_10781048_FILES[csv_name], csv_path)

    df = pd.read_csv(csv_path)
    if args.max_rows:
        df = df.head(args.max_rows)

    rows = []
    for idx, row in df.iterrows():
        expected_alert = bool(int(row.get("label", 0)))
        distance_cm = float(row.get("distance", 500))
        if distance_cm <= 120:
            expected_distance = "gần"
        elif distance_cm <= 300:
            expected_distance = "trung bình"
        else:
            expected_distance = "xa"
        rows.append(
            {
                "id": f"{csv_path.stem}#row={idx}",
                "expected_alert": expected_alert,
                "expected_distance": expected_distance,
                "distance_cm": distance_cm,
                "scenario": row.get("scenario"),
                "head_orientation": row.get("head orientation"),
                "mode": row.get("mode"),
                "failure_type": "zenodo_head_mounted_sensor",
            }
        )

    label_counts = df["label"].value_counts(dropna=False).to_dict() if "label" in df else {}
    payload = {
        "source": "zenodo:10781048",
        "note": "Sensor-only ultrasonic/IMU benchmark; not image input for benchmark_inference.py.",
        "csv": str(csv_path),
        "rows": len(rows),
        "label_counts": {str(key): int(value) for key, value in label_counts.items()},
        "items": rows,
    }
    args.labels_out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[OK] Prepared {len(rows)} Zenodo sensor item(s): {csv_path}")
    print(f"[OK] Wrote sensor manifest: {args.labels_out}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare external DADN-compatible benchmark subsets")
    subparsers = parser.add_subparsers(dest="command", required=True)

    guidedog = subparsers.add_parser("guidedog", help="Prepare GuideDog image subset after HF access is accepted")
    guidedog.add_argument("--config", choices=["object", "depth"], default="object")
    guidedog.add_argument("--split", default="train")
    guidedog.add_argument("--output-dir", type=Path, required=True)
    guidedog.add_argument("--labels-out", type=Path, required=True)
    guidedog.add_argument("--max-items", type=int, default=200)
    guidedog.add_argument("--risk-only", action="store_true", help="Emit only expected_alert labels for risk scoring")
    guidedog.set_defaults(func=prepare_guidedog)

    zenodo = subparsers.add_parser("zenodo-sensor", help="Download/summarize Zenodo head-mounted sensor benchmark")
    zenodo.add_argument("--file", choices=sorted(ZENODO_10781048_FILES), default="Corridor_marked.csv")
    zenodo.add_argument("--output-dir", type=Path, required=True)
    zenodo.add_argument("--labels-out", type=Path, required=True)
    zenodo.add_argument("--max-rows", type=int, default=0)
    zenodo.set_defaults(func=prepare_zenodo_sensor)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
