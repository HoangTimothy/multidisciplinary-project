#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import statistics
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any


def fetch_json(url: str, timeout: float) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.load(response)


def main() -> int:
    parser = argparse.ArgumentParser(description="Poll DADN /api/stats for stream runtime metrics")
    parser.add_argument("--server-url", default="http://127.0.0.1:5000")
    parser.add_argument("--duration", type=float, default=60.0)
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument("--output-dir", type=Path, default=Path("DADN/experiments/results"))
    parser.add_argument("--timeout", type=float, default=5.0)
    args = parser.parse_args()

    stats_url = args.server_url.rstrip("/") + "/api/stats"
    samples: list[dict[str, Any]] = []
    deadline = time.time() + args.duration

    while time.time() < deadline:
        sample = fetch_json(stats_url, args.timeout)
        sample["_timestamp"] = time.time()
        samples.append(sample)
        time.sleep(args.interval)

    output_dir = args.output_dir / datetime.now().strftime("%Y%m%d-%H%M%S-stream")
    output_dir.mkdir(parents=True, exist_ok=True)
    samples_path = output_dir / "stream_samples.json"
    samples_path.write_text(json.dumps({"samples": samples}, indent=2, ensure_ascii=False), encoding="utf-8")

    fps_values = [float(item.get("current_fps") or 0.0) for item in samples]
    inf_fps_values = [float(item.get("inference_fps") or 0.0) for item in samples]
    p95_values = [float(item.get("p95_inference_time_ms") or 0.0) for item in samples]
    queue_drops = [int(item.get("queue_drops") or 0) for item in samples]
    summary = {
        "server_url": args.server_url,
        "duration_seconds": args.duration,
        "samples": len(samples),
        "avg_capture_fps": statistics.fmean(fps_values) if fps_values else 0.0,
        "avg_inference_fps": statistics.fmean(inf_fps_values) if inf_fps_values else 0.0,
        "max_p95_inference_time_ms": max(p95_values) if p95_values else 0.0,
        "queue_drops_delta": (queue_drops[-1] - queue_drops[0]) if len(queue_drops) >= 2 else 0,
        "last_sample": samples[-1] if samples else None,
    }
    summary_path = output_dir / "stream_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[OK] Wrote stream samples: {samples_path}")
    print(f"[OK] Wrote stream summary: {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
