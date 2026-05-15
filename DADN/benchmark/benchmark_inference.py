#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import statistics
import time
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Iterator, Optional

import cv2

from core.decision_engine import DecisionEngine, ScoredObstacle
from core.detector import DetectionItem, ObstacleDetector
from core.experiment_config import ExperimentConfig, load_experiment_config
from core.frame_preprocessing import preprocess_for_inference
from core.model_registry import get_model_spec
from core.model_utils import ensure_model
from core.risk_smoothing import AlertSmoother


IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
VIDEO_EXTS = {".mp4", ".avi", ".mov", ".mkv", ".mjpeg"}
GROUPS = {
    "person": {"person"},
    "vehicle": {"bicycle", "motorcycle", "car", "bus", "truck", "train"},
    "static_obstacle": {"chair", "bench", "potted plant", "suitcase", "backpack"},
}
DEFAULT_MODEL_ID = "efficientdet_lite0_int8"
DEFAULT_MIN_ALERT_CORRECTNESS = 0.75
DEFAULT_CLOSE_SCORE_DELTA = 0.03


def group_for_label(label: Optional[str]) -> Optional[str]:
    if label is None:
        return None
    for group, labels in GROUPS.items():
        if label in labels:
            return group
    return "other"


def load_labels(path: Optional[Path]) -> dict[str, dict[str, Any]]:
    if path is None or not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict) and "items" in payload:
        payload = payload["items"]
    if isinstance(payload, list):
        return {str(item["id"]): item for item in payload}
    return {str(key): value for key, value in payload.items()}


def media_files(dataset: Path) -> list[Path]:
    if dataset.is_file():
        return [dataset]
    files = [
        path
        for path in dataset.rglob("*")
        if path.is_file() and path.suffix.lower() in IMAGE_EXTS | VIDEO_EXTS
    ]
    return sorted(files)


def iter_frames(path: Path, sample_every: int, max_frames: Optional[int]) -> Iterator[tuple[str, Any]]:
    suffix = path.suffix.lower()
    if suffix in IMAGE_EXTS:
        frame = cv2.imread(str(path))
        if frame is not None:
            yield path.name, frame
        return

    cap = cv2.VideoCapture(str(path))
    frame_idx = 0
    emitted = 0
    while cap.isOpened():
        ok, frame = cap.read()
        if not ok:
            break
        if frame_idx % sample_every == 0:
            yield f"{path.name}#frame={frame_idx}", frame
            emitted += 1
            if max_frames is not None and emitted >= max_frames:
                break
        frame_idx += 1
    cap.release()


def expected_for(
    labels: dict[str, dict[str, Any]],
    item_id: str,
    source_path: Path,
) -> tuple[dict[str, Any], Optional[str]]:
    if item_id in labels:
        return labels[item_id], item_id
    if source_path.name in labels:
        return labels[source_path.name], source_path.name
    return {}, None


def evaluate_alert(alert: Optional[ScoredObstacle], expected: dict[str, Any]) -> dict[str, Any]:
    expected_group = expected.get("expected_group") or expected.get("group")
    expected_zone = expected.get("expected_zone") or expected.get("zone")
    expected_distance = expected.get("expected_distance") or expected.get("distance")
    expected_alert = expected.get("expected_alert", bool(expected_group))

    alert_group = group_for_label(alert.label if alert else None)
    has_alert = alert is not None

    group_ok = expected_group is None or alert_group == expected_group
    zone_ok = expected_zone is None or (alert is not None and alert.horizontal_zone == expected_zone)
    distance_ok = expected_distance is None or (alert is not None and alert.distance_level == expected_distance)
    alert_ok = has_alert == expected_alert
    risk_correct = alert_ok
    correct = alert_ok and group_ok and zone_ok and distance_ok

    return {
        "expected_alert": expected_alert,
        "expected_group": expected_group,
        "expected_zone": expected_zone,
        "expected_distance": expected_distance,
        "alert_group": alert_group,
        "group_ok": group_ok,
        "zone_ok": zone_ok,
        "distance_ok": distance_ok,
        "alert_ok": alert_ok,
        "risk_correct": risk_correct,
        "correct": correct,
    }


def p95(values: list[float]) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    return statistics.quantiles(values, n=20, method="inclusive")[18]


def benchmark_config(
    config_path: Path,
    dataset: Path,
    labels: dict[str, dict[str, Any]],
    output_dir: Path,
    sample_every: int,
    max_frames_per_video: Optional[int],
    dry_run: bool = False,
) -> dict[str, Any]:
    exp = load_experiment_config(config_path)
    model_spec = get_model_spec(exp.detector.model_id)
    detector: Optional[ObstacleDetector] = None
    if not dry_run:
        model_path = ensure_model(model_spec.path, model_spec.url)
        detector = ObstacleDetector(
            model_path=model_path,
            score_threshold=exp.detector.score_threshold,
            max_results=exp.detector.max_results,
        )
    decision = DecisionEngine(
        exp.runtime.frame_width,
        exp.runtime.frame_height,
        **asdict(exp.decision),
    )
    smoother = AlertSmoother(
        hold_frames=exp.alert.temporal_hold_frames,
        hold_seconds=exp.alert.temporal_hold_seconds,
    )

    rows: list[dict[str, Any]] = []
    latencies_ms: list[float] = []
    correctness_values: list[bool] = []
    risk_correctness_values: list[bool] = []
    matched_label_ids: set[str] = set()
    frame_index = 0
    last_source_key: Optional[str] = None

    for media_path in media_files(dataset):
        for item_id, frame in iter_frames(media_path, sample_every, max_frames_per_video):
            frame_index += 1
            if frame.shape[1] != exp.runtime.frame_width or frame.shape[0] != exp.runtime.frame_height:
                frame = cv2.resize(frame, (exp.runtime.frame_width, exp.runtime.frame_height))

            start = time.perf_counter()
            inference_frame = frame
            if exp.runtime.inference_preprocessing_enabled:
                inference_frame = preprocess_for_inference(
                    frame,
                    denoise_enabled=exp.runtime.preprocess_denoise_enabled,
                    low_light_enabled=exp.runtime.preprocess_low_light_enabled,
                )
            detections: list[DetectionItem] = [] if dry_run or detector is None else detector.detect(inference_frame)
            latency_ms = (time.perf_counter() - start) * 1000
            raw_alert = decision.choose_alert(detections)
            expected, matched_label_id = expected_for(labels, item_id, media_path)
            if matched_label_id is not None:
                matched_label_ids.add(matched_label_id)

            source_key = str(expected.get("source_id") or media_path.name)
            if source_key != last_source_key:
                smoother.reset()
                last_source_key = source_key
            if exp.alert.temporal_smoothing_enabled:
                alert = smoother.update(
                    raw_alert,
                    frame_index=frame_index,
                    now_seconds=float(frame_index),
                )
            else:
                alert = raw_alert
            eval_result = evaluate_alert(alert, expected)

            if expected:
                correctness_values.append(bool(eval_result["correct"]))
                risk_correctness_values.append(bool(eval_result["risk_correct"]))
            latencies_ms.append(latency_ms)

            rows.append(
                {
                    "experiment_id": exp.experiment_id,
                    "model_id": exp.detector.model_id,
                    "item_id": item_id,
                    "latency_ms": f"{latency_ms:.3f}",
                    "detections_count": len(detections),
                    "raw_alert_label": raw_alert.label if raw_alert else "",
                    "alert_label": alert.label if alert else "",
                    "alert_display_label": alert.label_vi if alert else "",
                    "alert_raw_label_vi": alert.raw_label_vi if alert else "",
                    "alert_kind": alert.alert_kind if alert else "",
                    "alert_group": eval_result["alert_group"] or "",
                    "alert_zone": alert.horizontal_zone if alert else "",
                    "alert_distance": alert.distance_level if alert else "",
                    "alert_priority": f"{alert.priority:.6f}" if alert else "",
                    "alert_semantic_priority": f"{alert.semantic_priority:.6f}" if alert else "",
                    "alert_collision_risk_priority": f"{alert.collision_risk_priority:.6f}" if alert else "",
                    "expected_alert": eval_result["expected_alert"] if expected else "",
                    "expected_group": eval_result["expected_group"] or "",
                    "expected_zone": eval_result["expected_zone"] or "",
                    "expected_distance": eval_result["expected_distance"] or "",
                    "risk_correct": eval_result["risk_correct"] if expected else "",
                    "correct": eval_result["correct"] if expected else "",
                }
            )

    output_dir.mkdir(parents=True, exist_ok=True)
    rows_path = output_dir / f"{exp.experiment_id}_metrics.csv"
    with rows_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()) if rows else ["experiment_id"])
        writer.writeheader()
        writer.writerows(rows)

    avg_latency = statistics.fmean(latencies_ms) if latencies_ms else 0.0
    p95_latency = p95(latencies_ms)
    correctness = statistics.fmean(correctness_values) if correctness_values else None
    risk_correctness = statistics.fmean(risk_correctness_values) if risk_correctness_values else None
    labeled_frames = len(correctness_values)
    label_coverage = labeled_frames / len(rows) if rows else 0.0
    unmatched_labels_count = max(0, len(labels) - len(matched_label_ids))
    latency_score = max(0.0, 1.0 - min(p95_latency, 250.0) / 250.0)
    detection_rate = statistics.fmean([1.0 if int(row["detections_count"]) > 0 else 0.0 for row in rows]) if rows else 0.0
    alert_rate = statistics.fmean([1.0 if row["alert_label"] else 0.0 for row in rows]) if rows else 0.0
    correctness_score = (
        risk_correctness
        if risk_correctness is not None
        else correctness
        if correctness is not None
        else detection_rate
    )
    correctness_for_false_alert = risk_correctness if risk_correctness is not None else 0.0
    false_alert_score = 1.0 - max(0.0, alert_rate - correctness_for_false_alert)
    balanced_score = (
        0.40 * correctness_score
        + 0.25 * latency_score
        + 0.20 * detection_rate
        + 0.15 * max(0.0, min(1.0, false_alert_score))
    )

    return {
        "experiment_id": exp.experiment_id,
        "description": exp.description,
        "model_id": exp.detector.model_id,
        "model_family": model_spec.family,
        "quantization": model_spec.quantization,
        "frames": len(rows),
        "avg_latency_ms": avg_latency,
        "p50_latency_ms": statistics.median(latencies_ms) if latencies_ms else 0.0,
        "p95_latency_ms": p95_latency,
        "detection_rate": detection_rate,
        "alert_rate": alert_rate,
        "alert_correctness": correctness,
        "risk_alert_correctness": risk_correctness,
        "false_alert_rate": max(0.0, alert_rate - correctness_for_false_alert),
        "labeled_frames": labeled_frames,
        "label_coverage": label_coverage,
        "unmatched_labels": unmatched_labels_count,
        "balanced_score": balanced_score,
        "metrics_csv": str(rows_path),
        "config": asdict(exp),
    }


def choose_winner(
    summaries: list[dict[str, Any]],
    *,
    default_model_id: str,
    min_alert_correctness: float,
    close_score_delta: float,
    min_frames: int,
    min_labeled_frames: int,
) -> dict[str, Any]:
    for item in summaries:
        gate_correctness = item.get("risk_alert_correctness")
        if gate_correctness is None:
            gate_correctness = item.get("alert_correctness")
        item["meets_min_frames"] = item["frames"] >= min_frames
        item["meets_min_labeled_frames"] = item["labeled_frames"] >= min_labeled_frames
        item["meets_alert_correctness"] = (
            gate_correctness is not None
            and gate_correctness >= min_alert_correctness
        )
        item["winner_gate_correctness"] = gate_correctness
        item["winner_eligible"] = (
            item["meets_min_frames"]
            and item["meets_min_labeled_frames"]
            and item["meets_alert_correctness"]
        )

    eligible = [item for item in summaries if item["winner_eligible"]]
    if eligible:
        best_score = max(item["balanced_score"] for item in eligible)
        close = [
            item
            for item in eligible
            if best_score - item["balanced_score"] <= close_score_delta
        ]
        winner = min(close, key=lambda item: item["p95_latency_ms"])
        return {
            "experiment_id": winner["experiment_id"],
            "model_id": winner["model_id"],
            "selected": True,
            "fallback": False,
            "reason": (
                f"Eligible configs met risk/alert correctness >= {min_alert_correctness:.2f}; "
                f"selected lowest p95 latency among configs within {close_score_delta:.2f} "
                "balanced_score of the best score."
            ),
        }

    fallback = next(
        (item for item in summaries if item["model_id"] == default_model_id),
        summaries[0] if summaries else None,
    )
    return {
        "experiment_id": fallback["experiment_id"] if fallback else "",
        "model_id": fallback["model_id"] if fallback else default_model_id,
        "selected": bool(fallback),
        "fallback": True,
        "reason": (
            "No config met the minimum evidence gate; keep the existing default "
            f"{default_model_id} until a labeled run passes."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline model/hyperparameter benchmark for DADN")
    parser.add_argument("--dataset", type=Path, required=True, help="Image/video file or directory")
    parser.add_argument("--labels", type=Path, default=None, help="Optional labels JSON")
    parser.add_argument("--config", type=Path, action="append", required=True, help="Experiment config JSON")
    parser.add_argument("--output-dir", type=Path, default=Path("DADN/experiments/results"))
    parser.add_argument("--sample-every", type=int, default=15, help="Sample every N video frames")
    parser.add_argument("--max-frames-per-video", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true", help="Validate configs/dataset/output without loading models")
    parser.add_argument("--min-frames", type=int, default=0, help="Minimum frames/images required for winner eligibility")
    parser.add_argument("--min-labeled-frames", type=int, default=0, help="Minimum labeled frames required for winner eligibility")
    parser.add_argument(
        "--min-alert-correctness",
        type=float,
        default=DEFAULT_MIN_ALERT_CORRECTNESS,
        help="Minimum alert correctness required for winner eligibility",
    )
    parser.add_argument(
        "--close-score-delta",
        type=float,
        default=DEFAULT_CLOSE_SCORE_DELTA,
        help="When scores are this close, prefer lower p95 latency",
    )
    parser.add_argument("--default-model-id", default=DEFAULT_MODEL_ID, help="Fallback model when no config is eligible")
    args = parser.parse_args()

    run_dir = args.output_dir / datetime.now().strftime("%Y%m%d-%H%M%S")
    labels = load_labels(args.labels)
    files = media_files(args.dataset)
    if not files:
        raise SystemExit(f"No supported image/video files found in dataset: {args.dataset}")
    if args.labels is None:
        print("[WARN] No labels file provided; alert_correctness will be null and winner will fall back.")
    elif not labels:
        print(f"[WARN] Labels file has no usable items: {args.labels}")

    summaries = [
        benchmark_config(
            config_path,
            args.dataset,
            labels,
            run_dir,
            args.sample_every,
            args.max_frames_per_video,
            dry_run=args.dry_run,
        )
        for config_path in args.config
    ]
    summaries.sort(key=lambda item: item["balanced_score"], reverse=True)
    winner = choose_winner(
        summaries,
        default_model_id=args.default_model_id,
        min_alert_correctness=args.min_alert_correctness,
        close_score_delta=args.close_score_delta,
        min_frames=args.min_frames,
        min_labeled_frames=args.min_labeled_frames,
    )

    max_labeled_frames = max((item["labeled_frames"] for item in summaries), default=0)
    max_unmatched_labels = max((item["unmatched_labels"] for item in summaries), default=0)
    if labels and max_labeled_frames == 0:
        print("[WARN] Labels were provided, but none matched dataset item ids or filenames.")
    elif labels and max_unmatched_labels:
        print(
            "[WARN] "
            f"{max_labeled_frames} labeled frame(s) matched; "
            f"{max_unmatched_labels} label item(s) did not match any benchmark frame."
        )
    if args.min_frames and any(item["frames"] < args.min_frames for item in summaries):
        print(f"[WARN] Some configs have fewer than --min-frames={args.min_frames}.")
    if args.min_labeled_frames and any(item["labeled_frames"] < args.min_labeled_frames for item in summaries):
        print(f"[WARN] Some configs have fewer than --min-labeled-frames={args.min_labeled_frames}.")

    summary_path = run_dir / "summary.json"
    payload = {
        "dataset": str(args.dataset),
        "dataset_files": len(files),
        "labels": str(args.labels) if args.labels else None,
        "label_items": len(labels),
        "policy": {
            "min_frames": args.min_frames,
            "min_labeled_frames": args.min_labeled_frames,
            "min_alert_correctness": args.min_alert_correctness,
            "close_score_delta": args.close_score_delta,
            "default_model_id": args.default_model_id,
        },
        "winner": winner,
        "results": summaries,
    }
    summary_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"[OK] Wrote benchmark summary: {summary_path}")
    if summaries and winner["experiment_id"]:
        best = next((item for item in summaries if item["experiment_id"] == winner["experiment_id"]), summaries[0])
        label = "[WINNER]" if not winner["fallback"] else "[FALLBACK_SELECTED]"
        print(
            f"{label} "
            f"{best['experiment_id']} score={best['balanced_score']:.3f} "
            f"p95={best['p95_latency_ms']:.1f}ms frames={best['frames']} "
            f"labeled={best['labeled_frames']} "
            f"risk_correctness={best.get('risk_alert_correctness')} "
            f"group_correctness={best['alert_correctness']}"
        )
        if winner["fallback"]:
            print(f"[FALLBACK] {winner['reason']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
