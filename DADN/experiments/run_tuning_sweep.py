#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any


DADN_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = DADN_DIR.parent
RESULTS_DIR = DADN_DIR / "experiments" / "results"
BASE_CONFIG = DADN_DIR / "experiments" / "configs" / "balanced_lite0_int8.json"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def run_command(cmd: list[str], cwd: Path, env: dict[str, str] | None = None) -> dict[str, Any]:
    start = time.time()
    completed = subprocess.run(cmd, cwd=cwd, env=env, text=True, capture_output=True)
    return {
        "cmd": cmd,
        "returncode": completed.returncode,
        "duration_seconds": time.time() - start,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def deep_update(target: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            deep_update(target[key], value)
        else:
            target[key] = value
    return target


def candidate_config(base: dict[str, Any], experiment_id: str, description: str, updates: dict[str, Any]) -> dict[str, Any]:
    payload = deepcopy(base)
    payload["experiment_id"] = experiment_id
    payload["description"] = description
    deep_update(payload, updates)
    return payload


def build_candidates(base: dict[str, Any]) -> list[dict[str, Any]]:
    common_runtime = {
        "frame_width": 640,
        "frame_height": 480,
        "infer_every_n_frames": 5,
        "jpeg_quality": 60,
        "inference_queue_size": 1,
    }
    preprocess_on = {
        "inference_preprocessing_enabled": True,
        "preprocess_denoise_enabled": True,
        "preprocess_low_light_enabled": True,
    }
    smoothing_on = {
        "temporal_smoothing_enabled": True,
        "temporal_hold_frames": 2,
        "temporal_hold_seconds": 0.8,
    }
    current_generic_risk = {
        "generic_risk_min_area_ratio": 0.08,
        "generic_risk_min_center_area_ratio": 0.045,
        "generic_risk_priority_threshold": 0.48,
    }

    return [
        candidate_config(
            base,
            "sweep_lite0_s050_r05_baseline",
            "Baseline Lite0 int8 threshold/results.",
            {
                "detector": {"model_id": "efficientdet_lite0_int8", "score_threshold": 0.50, "max_results": 5},
                "runtime": common_runtime,
                "alert": {"temporal_smoothing_enabled": False},
            },
        ),
        candidate_config(
            base,
            "sweep_lite0_s045_r08",
            "Lower threshold and more results for recall.",
            {
                "detector": {"model_id": "efficientdet_lite0_int8", "score_threshold": 0.45, "max_results": 8},
                "runtime": common_runtime,
            },
        ),
        candidate_config(
            base,
            "sweep_lite0_s040_r10",
            "Intermediate alert-recall probe.",
            {
                "detector": {"model_id": "efficientdet_lite0_int8", "score_threshold": 0.40, "max_results": 10},
                "runtime": common_runtime,
            },
        ),
        candidate_config(
            base,
            "sweep_lite0_s035_r15",
            "High-recall detector probe before preprocessing/smoothing.",
            {
                "detector": {"model_id": "efficientdet_lite0_int8", "score_threshold": 0.35, "max_results": 15},
                "runtime": common_runtime,
            },
        ),
        candidate_config(
            base,
            "sweep_lite0_s035_r15_pre_smooth",
            "Selected high-recall detector with preprocessing and smoothing.",
            {
                "detector": {"model_id": "efficientdet_lite0_int8", "score_threshold": 0.35, "max_results": 15},
                "runtime": {**common_runtime, **preprocess_on},
                "decision": current_generic_risk,
                "alert": smoothing_on,
            },
        ),
        candidate_config(
            base,
            "sweep_lite0_s025_r25_hard",
            "Aggressive hard-case recall probe.",
            {
                "detector": {"model_id": "efficientdet_lite0_int8", "score_threshold": 0.25, "max_results": 25},
                "runtime": {**common_runtime, **preprocess_on},
                "decision": {
                    "generic_risk_min_area_ratio": 0.06,
                    "generic_risk_min_center_area_ratio": 0.035,
                    "generic_risk_priority_threshold": 0.40,
                },
                "alert": smoothing_on,
            },
        ),
        candidate_config(
            base,
            "sweep_lite2_s045_r08",
            "Higher-accuracy EfficientDet-Lite2 int8 comparison.",
            {
                "detector": {"model_id": "efficientdet_lite2_int8", "score_threshold": 0.45, "max_results": 8},
                "runtime": common_runtime,
            },
        ),
        candidate_config(
            base,
            "sweep_ssd_s045_r05_faster",
            "SSD MobileNetV2 float16 speed-oriented comparison.",
            {
                "detector": {"model_id": "ssd_mobilenet_v2_float16", "score_threshold": 0.45, "max_results": 5},
                "runtime": {**common_runtime, "infer_every_n_frames": 3},
                "decision": {"near_area_ratio": 0.16},
            },
        ),
    ]


def selected_summary(summary: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for item in summary.get("results", []):
        rows.append(
            {
                "experiment_id": item.get("experiment_id"),
                "model_id": item.get("model_id"),
                "frames": item.get("frames"),
                "labeled_frames": item.get("labeled_frames"),
                "risk_alert_correctness": item.get("risk_alert_correctness"),
                "alert_correctness": item.get("alert_correctness"),
                "detection_rate": item.get("detection_rate"),
                "alert_rate": item.get("alert_rate"),
                "avg_latency_ms": item.get("avg_latency_ms"),
                "p95_latency_ms": item.get("p95_latency_ms"),
                "balanced_score": item.get("balanced_score"),
                "winner_eligible": item.get("winner_eligible"),
            }
        )
    return rows


def dataset_files(dataset: Path) -> list[Path]:
    image_exts = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
    video_exts = {".mp4", ".avi", ".mov", ".mkv", ".mjpeg"}
    if dataset.is_file():
        return [dataset]
    return sorted(
        path
        for path in dataset.rglob("*")
        if path.is_file() and path.suffix.lower() in image_exts | video_exts
    )


def labels_items(payload: Any) -> dict[str, Any]:
    if isinstance(payload, dict) and isinstance(payload.get("items"), dict):
        return payload["items"]
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, list):
        return {str(item.get("id", index)): item for index, item in enumerate(payload)}
    return {}


def infer_group_counts(items: dict[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in items.values():
        if not isinstance(value, dict):
            continue
        group = value.get("expected_group") or value.get("group")
        if group:
            counts[str(group)] = counts.get(str(group), 0) + 1
    return counts


def infer_alert_counts(items: dict[str, Any]) -> dict[str, int]:
    counts = {"expected_alert_true": 0, "expected_alert_false": 0, "expected_alert_missing": 0}
    for value in items.values():
        if not isinstance(value, dict):
            counts["expected_alert_missing"] += 1
            continue
        expected = value.get("expected_alert")
        if expected is True:
            counts["expected_alert_true"] += 1
        elif expected is False:
            counts["expected_alert_false"] += 1
        else:
            counts["expected_alert_missing"] += 1
    return counts


def format_float(value: Any, digits: int = 3) -> str:
    if value is None:
        return "N/A"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def write_markdown(path: Path, payload: dict[str, Any]) -> None:
    lines = [
        "# DADN Tuning Sweep Summary",
        "",
        f"- Generated at: `{payload['generated_at']}`",
        f"- Dataset: `{payload['dataset']}`",
        f"- Labels: `{payload['labels']}`",
        f"- Config directory: `{payload['config_dir']}`",
        f"- Benchmark summary: `{payload['benchmark_summary_path']}`",
        "",
        "## Dataset Trace",
        "",
        f"- Dataset source: `{payload['dataset_trace'].get('source')}`",
        f"- Source counts: `{payload['dataset_trace'].get('source_counts')}`",
        f"- Group counts: `{payload['dataset_trace'].get('group_counts')}`",
        f"- Alert-label counts: `{payload['dataset_trace'].get('alert_counts')}`",
        f"- Media files / label items: `{payload['dataset_trace'].get('media_files')}` / `{payload['dataset_trace'].get('label_items')}`",
        "",
        "## Winner",
        "",
        f"- Winner: `{payload['winner'].get('experiment_id')}`",
        f"- Model: `{payload['winner'].get('model_id')}`",
        f"- Reason: {payload['winner'].get('reason')}",
        "",
        "## Results",
        "",
        "| Config | Model | Risk | Alert | Detect | Alert rate | Avg ms | P95 ms | Score | Eligible |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in payload["results"]:
        lines.append(
            "| {config} | {model} | {risk} | {alert} | {detect} | {alert_rate} | {avg} | {p95} | {score} | {eligible} |".format(
                config=row["experiment_id"],
                model=row["model_id"],
                risk=format_float(row["risk_alert_correctness"]),
                alert=format_float(row["alert_correctness"]),
                detect=format_float(row["detection_rate"]),
                alert_rate=format_float(row["alert_rate"]),
                avg=format_float(row["avg_latency_ms"], 1),
                p95=format_float(row["p95_latency_ms"], 1),
                score=format_float(row["balanced_score"]),
                eligible=row["winner_eligible"],
            )
        )
    lines.extend(
        [
            "",
        "## Interpretation",
        "",
        "- Lowering `score_threshold` and increasing `max_results` tests the recall/latency tradeoff.",
        "- Preprocessing and temporal smoothing are tested as a separate final-candidate step.",
        "- Lite2 and SSD candidates are kept as model-family comparisons.",
        "- Public datasets are offline evidence; real ESP32-CAM frames are needed for deployment evidence.",
        "- If `expected_alert_false` is low or zero, the run cannot justify an aggressive threshold against false-alert spam.",
        "",
    ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a reproducible DADN tuning sweep")
    parser.add_argument("--dataset", type=Path, required=True, help="Dataset directory or media file")
    parser.add_argument("--labels", type=Path, required=True, help="Labels JSON")
    parser.add_argument("--output-dir", type=Path, default=RESULTS_DIR)
    parser.add_argument("--min-frames", type=int, default=50)
    parser.add_argument("--min-labeled-frames", type=int, default=50)
    parser.add_argument("--min-alert-correctness", type=float, default=0.75)
    args = parser.parse_args()

    run_dir = args.output_dir / datetime.now().strftime("%Y%m%d-%H%M%S-tuning-sweep")
    run_dir.mkdir(parents=True, exist_ok=True)

    dataset = args.dataset
    labels = args.labels

    labels_payload = load_json(labels)
    label_items = labels_items(labels_payload)
    labels_meta = labels_payload if isinstance(labels_payload, dict) else {}
    dataset_trace = {
        "source": labels_meta.get("source", "provided dataset"),
        "source_counts": labels_meta.get("source_counts"),
        "group_counts": labels_meta.get("group_counts") or infer_group_counts(label_items),
        "alert_counts": infer_alert_counts(label_items),
        "label_detail": labels_meta.get("label_detail"),
        "media_files": len(dataset_files(dataset)),
        "label_items": len(label_items),
    }

    config_dir = run_dir / "configs"
    configs = []
    base = load_json(BASE_CONFIG)
    for config in build_candidates(base):
        config_path = config_dir / f"{config['experiment_id']}.json"
        write_json(config_path, config)
        configs.append(config_path)

    env = os.environ.copy()
    existing_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(DADN_DIR) if not existing_pythonpath else f"{DADN_DIR}{os.pathsep}{existing_pythonpath}"

    benchmark_dir = run_dir / "benchmark"
    cmd = [
        sys.executable,
        str(DADN_DIR / "benchmark" / "benchmark_inference.py"),
        "--dataset",
        str(dataset),
        "--labels",
        str(labels),
        "--output-dir",
        str(benchmark_dir),
        "--min-frames",
        str(args.min_frames),
        "--min-labeled-frames",
        str(args.min_labeled_frames),
        "--min-alert-correctness",
        str(args.min_alert_correctness),
    ]
    for config_path in configs:
        cmd.extend(["--config", str(config_path)])
    benchmark_command = run_command(cmd, REPO_ROOT, env)
    if benchmark_command["returncode"] != 0:
        write_json(run_dir / "tuning_sweep_failed.json", {"benchmark_command": benchmark_command})
        return benchmark_command["returncode"]

    summary_candidates = sorted(benchmark_dir.rglob("summary.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    if not summary_candidates:
        raise SystemExit("Benchmark completed but no summary.json was found.")
    benchmark_summary_path = summary_candidates[0]
    benchmark_summary = load_json(benchmark_summary_path)

    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "dataset": str(dataset),
        "labels": str(labels),
        "dataset_trace": dataset_trace,
        "config_dir": str(config_dir),
        "configs": [str(path) for path in configs],
        "benchmark_command": benchmark_command,
        "benchmark_summary_path": str(benchmark_summary_path),
        "winner": benchmark_summary.get("winner", {}),
        "results": selected_summary(benchmark_summary),
    }
    write_json(run_dir / "tuning_sweep_summary.json", payload)
    write_markdown(run_dir / "tuning_sweep_summary.md", payload)
    print(f"[OK] Wrote tuning sweep JSON: {run_dir / 'tuning_sweep_summary.json'}")
    print(f"[OK] Wrote tuning sweep Markdown: {run_dir / 'tuning_sweep_summary.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
