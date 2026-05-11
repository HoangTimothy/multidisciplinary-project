#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

import cv2


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture real ESP32/laptop camera frames for DADN risk review")
    parser.add_argument("--camera-url", required=True, help="MJPEG stream URL, e.g. http://192.168.1.11:8081/stream")
    parser.add_argument("--output", type=Path, required=True, help="Output image directory")
    parser.add_argument("--labels-out", type=Path, required=True, help="Output review manifest JSON")
    parser.add_argument("--frames", type=int, default=60, help="Number of frames to save")
    parser.add_argument("--interval-seconds", type=float, default=0.5, help="Delay between saved frames")
    parser.add_argument("--expected-alert", action="store_true", help="Mark captured frames as expected collision-risk alerts")
    parser.add_argument("--expected-zone", default=None, help="Optional expected zone label")
    parser.add_argument("--expected-distance", default=None, help="Optional expected distance label")
    parser.add_argument("--failure-type", default="real_camera_review", help="Review/failure type tag")
    args = parser.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)
    args.labels_out.parent.mkdir(parents=True, exist_ok=True)

    cap = cv2.VideoCapture(args.camera_url)
    if not cap.isOpened():
        raise SystemExit(f"Could not open camera stream: {args.camera_url}")

    items: list[dict[str, Any]] = []
    saved = 0
    last_saved_at = 0.0
    started_at = time.time()

    try:
        while saved < args.frames:
            ok, frame = cap.read()
            if not ok or frame is None:
                time.sleep(0.1)
                continue
            now = time.time()
            if saved > 0 and now - last_saved_at < args.interval_seconds:
                continue

            item_id = f"real_camera_{saved:04d}.jpg"
            out_path = args.output / item_id
            cv2.imwrite(str(out_path), frame, [int(cv2.IMWRITE_JPEG_QUALITY), 85])

            item: dict[str, Any] = {
                "id": item_id,
                "source": args.camera_url,
                "expected_alert": bool(args.expected_alert),
                "failure_type": args.failure_type,
            }
            if args.expected_zone:
                item["expected_zone"] = args.expected_zone
            if args.expected_distance:
                item["expected_distance"] = args.expected_distance
            items.append(item)

            saved += 1
            last_saved_at = now
    finally:
        cap.release()

    args.labels_out.write_text(
        json.dumps(
            {
                "source": args.camera_url,
                "captured_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "duration_seconds": round(time.time() - started_at, 3),
                "items": items,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print(f"[OK] Saved {saved} frames to {args.output}")
    print(f"[OK] Wrote review labels to {args.labels_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
