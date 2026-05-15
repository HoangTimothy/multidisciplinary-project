#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

from core.model_registry import get_model_spec
from core.model_utils import ensure_model


BASE_DIR = Path(__file__).resolve().parent.parent
RESULTS_DIR = BASE_DIR / "experiments" / "results"
EDGE_CONFIGS = [
    BASE_DIR / "experiments" / "configs" / "tuned_lite0_int8_high_recall.json",
    BASE_DIR / "experiments" / "configs" / "tuned_lite0_int8_recall.json",
    BASE_DIR / "experiments" / "configs" / "balanced_lite0_int8.json",
    BASE_DIR / "experiments" / "configs" / "fast_ssd_mobilenet_v2_float16.json",
    BASE_DIR / "experiments" / "configs" / "accuracy_lite2_int8.json",
]
FULL_SWEEP_CONFIGS = EDGE_CONFIGS + [
    BASE_DIR / "experiments" / "configs" / "sanity_lite0_float16.json",
    BASE_DIR / "experiments" / "configs" / "sanity_lite0_float32.json",
    BASE_DIR / "experiments" / "configs" / "accuracy_lite2_float16.json",
    BASE_DIR / "experiments" / "configs" / "accuracy_lite2_float32.json",
    BASE_DIR / "experiments" / "configs" / "fast_ssd_mobilenet_v2_float32.json",
]


def run_command(cmd: list[str], cwd: Path) -> dict[str, Any]:
    start = time.time()
    completed = subprocess.run(cmd, cwd=cwd, text=True, capture_output=True)
    return {
        "cmd": cmd,
        "returncode": completed.returncode,
        "duration_seconds": time.time() - start,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def fetch_json(url: str, timeout: float = 5.0) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.load(response)


def model_ids_from_configs(configs: list[Path]) -> list[str]:
    model_ids: list[str] = []
    for path in configs:
        payload = json.loads(path.read_text(encoding="utf-8"))
        model_id = payload["detector"]["model_id"]
        if model_id not in model_ids:
            model_ids.append(model_id)
    return model_ids


def model_inventory(model_ids: list[str], download: bool) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for model_id in model_ids:
        spec = get_model_spec(model_id)
        if download:
            ensure_model(spec.path, spec.url)
        rows.append(
            {
                "model_id": model_id,
                "family": spec.family,
                "quantization": spec.quantization,
                "path": str(spec.path),
                "exists": spec.path.exists(),
                "size_bytes": spec.path.stat().st_size if spec.path.exists() else 0,
                "notes": spec.notes,
            }
        )
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Raspberry Pi edge-readiness tests for DADN")
    parser.add_argument("--dataset", type=Path, help="Optional offline image/video dataset")
    parser.add_argument("--labels", type=Path, help="Optional labels JSON for offline benchmark")
    parser.add_argument("--server-url", help="Optional running DADN server URL for stream benchmark")
    parser.add_argument("--stream-duration", type=float, default=60.0)
    parser.add_argument("--stream-interval", type=float, default=1.0)
    parser.add_argument("--full-model-sweep", action="store_true", help="Include float sanity configs")
    parser.add_argument("--download-models", action="store_true", help="Download required model files before tests")
    parser.add_argument("--min-frames", type=int, default=200)
    parser.add_argument("--min-labeled-frames", type=int, default=200)
    parser.add_argument("--min-alert-correctness", type=float, default=0.75)
    parser.add_argument("--output-dir", type=Path, default=RESULTS_DIR)
    args = parser.parse_args()

    configs = FULL_SWEEP_CONFIGS if args.full_model_sweep else EDGE_CONFIGS
    run_dir = args.output_dir / datetime.now().strftime("%Y%m%d-%H%M%S-pi-edge-suite")
    run_dir.mkdir(parents=True, exist_ok=True)

    summary: dict[str, Any] = {
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "platform": {
            "system": platform.system(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "python": sys.version,
        },
        "configs": [str(path) for path in configs],
        "models": model_inventory(model_ids_from_configs(configs), args.download_models),
        "offline_benchmark": None,
        "stream_benchmark": None,
    }

    if args.dataset:
        cmd = [
            sys.executable,
            str(BASE_DIR / "benchmark_inference.py"),
            "--dataset",
            str(args.dataset),
            "--output-dir",
            str(run_dir / "offline"),
            "--min-frames",
            str(args.min_frames),
            "--min-labeled-frames",
            str(args.min_labeled_frames),
            "--min-alert-correctness",
            str(args.min_alert_correctness),
        ]
        if args.labels:
            cmd.extend(["--labels", str(args.labels)])
        for config in configs:
            cmd.extend(["--config", str(config)])
        summary["offline_benchmark"] = run_command(cmd, BASE_DIR.parent)

    if args.server_url:
        health_url = args.server_url.rstrip("/") + "/health"
        stats_url = args.server_url.rstrip("/") + "/api/stats"
        stream_status: dict[str, Any] = {}
        try:
            stream_status["health_before"] = fetch_json(health_url)
            stream_status["stats_before"] = fetch_json(stats_url)
        except Exception as exc:
            stream_status["precheck_error"] = str(exc)

        cmd = [
            sys.executable,
            str(BASE_DIR / "benchmark_stream.py"),
            "--server-url",
            args.server_url,
            "--duration",
            str(args.stream_duration),
            "--interval",
            str(args.stream_interval),
            "--output-dir",
            str(run_dir / "stream"),
        ]
        stream_status["command"] = run_command(cmd, BASE_DIR.parent)
        try:
            stream_status["health_after"] = fetch_json(health_url)
            stream_status["stats_after"] = fetch_json(stats_url)
        except Exception as exc:
            stream_status["postcheck_error"] = str(exc)
        summary["stream_benchmark"] = stream_status

    summary["finished_at"] = datetime.now().isoformat(timespec="seconds")
    summary_path = run_dir / "pi_edge_suite_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[OK] Wrote Pi edge suite summary: {summary_path}")

    failed = [
        item
        for item in (summary.get("offline_benchmark"), (summary.get("stream_benchmark") or {}).get("command"))
        if item and item.get("returncode") != 0
    ]
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
