#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any


DADN_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = DADN_DIR.parent
RESULTS_DIR = DADN_DIR / "experiments" / "results"
DEFAULT_CONFIG = DADN_DIR / "experiments" / "configs" / "tuned_lite0_int8_high_recall.json"
LABEL_GROUPS = ["person", "vehicle", "static_obstacle"]


def fmean_or_none(values: list[float]) -> float | None:
    return statistics.fmean(values) if values else None


def stdev_or_none(values: list[float]) -> float | None:
    return statistics.stdev(values) if len(values) >= 2 else None


def p95_or_none(values: list[float]) -> float | None:
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    return statistics.quantiles(values, n=20, method="inclusive")[18]


def fetch_json(url: str, timeout: float) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.load(response)


def poll_stats(stats_url: str, timeout: float) -> dict[str, Any]:
    sample = fetch_json(stats_url, timeout)
    sample["_timestamp"] = time.time()
    return sample


def summarize_runtime_samples(samples: list[dict[str, Any]], server_url: str, duration: float) -> dict[str, Any]:
    capture_fps = [float(item.get("current_fps") or 0.0) for item in samples]
    inference_fps = [float(item.get("inference_fps") or 0.0) for item in samples]
    avg_inference_time = [float(item.get("avg_inference_time_ms") or 0.0) for item in samples]
    p95_inference_time = [float(item.get("p95_inference_time_ms") or 0.0) for item in samples]
    queue_drops = [int(item.get("queue_drops") or 0) for item in samples]

    alert_latencies: list[float] = []
    seen_alert_keys: set[str] = set()
    for sample in samples:
        alert = sample.get("last_alert")
        if not alert:
            continue
        key = str(alert.get("timestamp") or json.dumps(alert, sort_keys=True, ensure_ascii=False))
        if key in seen_alert_keys:
            continue
        seen_alert_keys.add(key)
        latency = alert.get("latency_ms", sample.get("last_alert_latency_ms"))
        if latency is not None:
            alert_latencies.append(float(latency))

    return {
        "server_url": server_url,
        "duration_seconds": duration,
        "samples": len(samples),
        "avg_capture_fps": fmean_or_none(capture_fps),
        "avg_inference_fps": fmean_or_none(inference_fps),
        "avg_inference_time_ms": fmean_or_none(avg_inference_time),
        "max_p95_inference_time_ms": max(p95_inference_time) if p95_inference_time else None,
        "queue_drops_delta": (queue_drops[-1] - queue_drops[0]) if len(queue_drops) >= 2 else 0,
        "server_side_alert_latency_ms_mean": fmean_or_none(alert_latencies),
        "server_side_alert_latency_ms_p95": p95_or_none(alert_latencies),
        "server_side_alert_latencies_ms": alert_latencies,
        "alert_events": len(alert_latencies),
        "last_sample": samples[-1] if samples else None,
    }


def run_runtime_benchmark(args: argparse.Namespace, run_dir: Path) -> dict[str, Any]:
    base_url = args.server_url.rstrip("/")
    health_url = base_url + "/health"
    stats_url = base_url + "/api/stats"
    runtime_dir = run_dir / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)

    precheck: dict[str, Any] = {}
    try:
        precheck["health"] = fetch_json(health_url, args.timeout)
        precheck["stats"] = fetch_json(stats_url, args.timeout)
    except Exception as exc:
        precheck["error"] = str(exc)
        return {
            "status": "failed",
            "reason": "Could not reach DADN server before runtime benchmark.",
            "precheck": precheck,
        }

    run_summaries: list[dict[str, Any]] = []
    all_alert_latencies: list[float] = []

    for run_idx in range(1, args.runs + 1):
        warmup_deadline = time.time() + args.warmup
        while time.time() < warmup_deadline:
            try:
                poll_stats(stats_url, args.timeout)
            except Exception:
                pass
            time.sleep(args.interval)

        samples: list[dict[str, Any]] = []
        deadline = time.time() + args.duration
        while time.time() < deadline:
            try:
                samples.append(poll_stats(stats_url, args.timeout))
            except Exception as exc:
                samples.append({"_timestamp": time.time(), "_error": str(exc)})
            time.sleep(args.interval)

        samples_path = runtime_dir / f"runtime_run_{run_idx}.json"
        samples_path.write_text(json.dumps({"samples": samples}, indent=2, ensure_ascii=False), encoding="utf-8")

        summary = summarize_runtime_samples(samples, args.server_url, args.duration)
        summary["run"] = run_idx
        summary["samples_path"] = str(samples_path)
        run_summaries.append(summary)
        all_alert_latencies.extend(
            float(item) for item in summary.get("server_side_alert_latencies_ms", [])
        )

    capture_run_avgs = [
        float(item["avg_capture_fps"])
        for item in run_summaries
        if item.get("avg_capture_fps") is not None
    ]
    inference_run_avgs = [
        float(item["avg_inference_fps"])
        for item in run_summaries
        if item.get("avg_inference_fps") is not None
    ]
    alert_event_count = sum(int(item.get("alert_events") or 0) for item in run_summaries)

    return {
        "status": "ok",
        "protocol": {
            "runs": args.runs,
            "warmup_seconds": args.warmup,
            "duration_seconds": args.duration,
            "interval_seconds": args.interval,
            "note": "Latency is server-side alert latency, not full user-perceived end-to-end latency.",
        },
        "precheck": precheck,
        "runs": run_summaries,
        "summary": {
            "avg_capture_fps_mean": fmean_or_none(capture_run_avgs),
            "avg_capture_fps_std": stdev_or_none(capture_run_avgs),
            "avg_inference_fps_mean": fmean_or_none(inference_run_avgs),
            "avg_inference_fps_std": stdev_or_none(inference_run_avgs),
            "server_side_alert_latency_ms_mean": fmean_or_none(all_alert_latencies),
            "server_side_alert_latency_ms_p95": p95_or_none(all_alert_latencies),
            "alert_events": alert_event_count,
        },
    }


def run_command(cmd: list[str], cwd: Path, env: dict[str, str]) -> dict[str, Any]:
    start = time.time()
    completed = subprocess.run(cmd, cwd=cwd, env=env, text=True, capture_output=True)
    return {
        "cmd": cmd,
        "returncode": completed.returncode,
        "duration_seconds": time.time() - start,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def newest_summary_json(root: Path) -> Path | None:
    candidates = sorted(root.rglob("summary.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    return candidates[0] if candidates else None


def selected_offline_result(summary: dict[str, Any]) -> dict[str, Any] | None:
    results = summary.get("results") or []
    winner = summary.get("winner") or {}
    winner_id = winner.get("experiment_id")
    if winner_id:
        for item in results:
            if item.get("experiment_id") == winner_id:
                return item
    return results[0] if results else None


def run_offline_benchmark(args: argparse.Namespace, run_dir: Path) -> dict[str, Any]:
    output_dir = run_dir / "offline"
    output_dir.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    existing_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(DADN_DIR) if not existing_pythonpath else f"{DADN_DIR}{os.pathsep}{existing_pythonpath}"

    cmd = [
        sys.executable,
        str(DADN_DIR / "benchmark" / "benchmark_inference.py"),
        "--dataset",
        str(args.dataset),
        "--output-dir",
        str(output_dir),
        "--sample-every",
        str(args.sample_every),
        "--min-frames",
        str(args.min_frames),
        "--min-labeled-frames",
        str(args.min_labeled_frames),
        "--min-alert-correctness",
        str(args.min_alert_correctness),
    ]
    if args.labels:
        cmd.extend(["--labels", str(args.labels)])
    if args.max_frames_per_video is not None:
        cmd.extend(["--max-frames-per-video", str(args.max_frames_per_video)])
    for config in args.config:
        cmd.extend(["--config", str(config)])
    if args.dry_run_offline:
        cmd.append("--dry-run")

    command = run_command(cmd, REPO_ROOT, env)
    summary_path = newest_summary_json(output_dir)
    parsed_summary = None
    selected = None
    if summary_path and summary_path.exists():
        parsed_summary = json.loads(summary_path.read_text(encoding="utf-8"))
        selected = selected_offline_result(parsed_summary)

    return {
        "status": "ok" if command["returncode"] == 0 else "failed",
        "command": command,
        "summary_path": str(summary_path) if summary_path else None,
        "summary": parsed_summary,
        "selected_result": selected,
    }


def compact_summary(payload: dict[str, Any]) -> dict[str, Any]:
    offline = payload.get("offline") or {}
    selected = offline.get("selected_result") or {}
    runtime = payload.get("runtime") or {}
    runtime_summary = runtime.get("summary") or {}

    return {
        "generated_at": payload["generated_at"],
        "label_groups": LABEL_GROUPS,
        "offline": {
            "status": offline.get("status"),
            "dataset": str(payload.get("dataset")) if payload.get("dataset") else None,
            "labels": str(payload.get("labels")) if payload.get("labels") else None,
            "config": selected.get("experiment_id"),
            "frames": selected.get("frames"),
            "labeled_frames": selected.get("labeled_frames"),
            "risk_alert_correctness": selected.get("risk_alert_correctness"),
            "alert_correctness": selected.get("alert_correctness"),
            "avg_latency_ms": selected.get("avg_latency_ms"),
            "p95_latency_ms": selected.get("p95_latency_ms"),
        },
        "runtime": {
            "status": runtime.get("status"),
            "runs": (runtime.get("protocol") or {}).get("runs"),
            "warmup_seconds": (runtime.get("protocol") or {}).get("warmup_seconds"),
            "duration_seconds": (runtime.get("protocol") or {}).get("duration_seconds"),
            "interval_seconds": (runtime.get("protocol") or {}).get("interval_seconds"),
            "avg_capture_fps_mean": runtime_summary.get("avg_capture_fps_mean"),
            "avg_capture_fps_std": runtime_summary.get("avg_capture_fps_std"),
            "avg_inference_fps_mean": runtime_summary.get("avg_inference_fps_mean"),
            "avg_inference_fps_std": runtime_summary.get("avg_inference_fps_std"),
            "server_side_alert_latency_ms_mean": runtime_summary.get("server_side_alert_latency_ms_mean"),
            "server_side_alert_latency_ms_p95": runtime_summary.get("server_side_alert_latency_ms_p95"),
            "alert_events": runtime_summary.get("alert_events"),
            "latency_note": "server-side alert latency, not full end-to-end audio latency",
        },
    }


def format_value(value: Any, digits: int = 3) -> str:
    if value is None:
        return "N/A"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def format_seconds(value: Any) -> str:
    return "N/A" if value is None else f"{value}s"


def write_markdown_summary(path: Path, summary: dict[str, Any]) -> None:
    offline = summary["offline"]
    runtime = summary["runtime"]
    lines = [
        "# DADN Metrics Summary",
        "",
        f"- Generated at: `{summary['generated_at']}`",
        f"- Label groups: `{', '.join(summary['label_groups'])}`",
        "",
        "## Offline dataset benchmark",
        "",
        f"- Status: `{offline['status']}`",
        f"- Dataset: `{format_value(offline['dataset'])}`",
        f"- Labels: `{format_value(offline['labels'])}`",
        f"- Config: `{format_value(offline['config'])}`",
        f"- Frames / labeled frames: `{format_value(offline['frames'])}` / `{format_value(offline['labeled_frames'])}`",
        f"- Risk alert correctness: `{format_value(offline['risk_alert_correctness'])}`",
        f"- Alert correctness: `{format_value(offline['alert_correctness'])}`",
        f"- Offline avg / p95 latency: `{format_value(offline['avg_latency_ms'], 1)} ms` / `{format_value(offline['p95_latency_ms'], 1)} ms`",
        "",
        "## Runtime benchmark",
        "",
        f"- Status: `{runtime['status']}`",
        f"- Protocol: `{format_value(runtime['runs'])}` runs, `{format_seconds(runtime['warmup_seconds'])}` warm-up, `{format_seconds(runtime['duration_seconds'])}` record, `{format_seconds(runtime['interval_seconds'])}` interval",
        f"- Average capture FPS: `{format_value(runtime['avg_capture_fps_mean'], 2)} +/- {format_value(runtime['avg_capture_fps_std'], 2)}`",
        f"- Average inference FPS: `{format_value(runtime['avg_inference_fps_mean'], 2)} +/- {format_value(runtime['avg_inference_fps_std'], 2)}`",
        f"- Server-side alert latency mean / p95: `{format_value(runtime['server_side_alert_latency_ms_mean'], 1)} ms` / `{format_value(runtime['server_side_alert_latency_ms_p95'], 1)} ms`",
        f"- Alert events observed: `{format_value(runtime['alert_events'])}`",
        "",
        "Note: server-side alert latency is measured from backend timestamps and is not full user-perceived end-to-end audio latency.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Record report-ready DADN benchmark metrics")
    parser.add_argument("--dataset", type=Path, help="Offline image/video dataset for correctness benchmark")
    parser.add_argument("--labels", type=Path, help="Labels JSON for offline benchmark")
    parser.add_argument("--config", type=Path, action="append", help="Experiment config JSON")
    parser.add_argument("--server-url", default="http://127.0.0.1:5000", help="Running DADN server URL")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--warmup", type=float, default=10.0)
    parser.add_argument("--duration", type=float, default=60.0)
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument("--output-dir", type=Path, default=RESULTS_DIR)
    parser.add_argument("--sample-every", type=int, default=15)
    parser.add_argument("--max-frames-per-video", type=int, default=None)
    parser.add_argument("--min-frames", type=int, default=0)
    parser.add_argument("--min-labeled-frames", type=int, default=0)
    parser.add_argument("--min-alert-correctness", type=float, default=0.75)
    parser.add_argument("--skip-offline", action="store_true")
    parser.add_argument("--skip-runtime", action="store_true")
    parser.add_argument("--dry-run-offline", action="store_true")
    args = parser.parse_args()
    if not args.config:
        args.config = [DEFAULT_CONFIG]

    run_dir = args.output_dir / datetime.now().strftime("%Y%m%d-%H%M%S-record-metrics")
    run_dir.mkdir(parents=True, exist_ok=True)

    payload: dict[str, Any] = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "dataset": str(args.dataset) if args.dataset else None,
        "labels": str(args.labels) if args.labels else None,
        "configs": [str(path) for path in args.config],
        "offline": None,
        "runtime": None,
    }

    if not args.skip_offline and args.dataset:
        payload["offline"] = run_offline_benchmark(args, run_dir)
    elif args.skip_offline:
        payload["offline"] = {"status": "skipped", "reason": "--skip-offline was provided"}
    else:
        payload["offline"] = {"status": "skipped", "reason": "No --dataset was provided"}

    if not args.skip_runtime:
        payload["runtime"] = run_runtime_benchmark(args, run_dir)
    else:
        payload["runtime"] = {"status": "skipped", "reason": "--skip-runtime was provided"}

    full_path = run_dir / "metrics_full.json"
    full_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    summary = compact_summary(payload)
    summary_path = run_dir / "metrics_summary.json"
    markdown_path = run_dir / "metrics_summary.md"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    write_markdown_summary(markdown_path, summary)

    print(f"[OK] Wrote full metrics: {full_path}")
    print(f"[OK] Wrote summary JSON: {summary_path}")
    print(f"[OK] Wrote summary Markdown: {markdown_path}")

    failed = [
        item
        for item in (payload.get("offline"), payload.get("runtime"))
        if item and item.get("status") == "failed"
    ]
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
