#!/usr/bin/env python3
"""
Expose an ESP32-CAM MJPEG stream through ngrok.

Run this on the computer that can reach the ESP32-CAM stream URL, usually the
same computer used to flash/monitor the ESP32-CAM.
"""

from __future__ import annotations

import argparse
import json
import shutil
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path


DEFAULT_URL_FILE = Path(__file__).resolve().parent / ".esp32-ngrok-url"


def normalize_esp32_base(value: str) -> str:
    url = value.strip().rstrip("/")
    if not url:
        raise ValueError("ESP32-CAM URL is empty")

    if not url.startswith(("http://", "https://")):
        url = "http://" + url

    return url[:-7] if url.endswith("/stream") else url


def wait_for_ngrok_url(api_url: str, upstream: str, timeout_seconds: int = 30) -> str:
    deadline = time.time() + timeout_seconds
    upstream = upstream.rstrip("/")

    while time.time() < deadline:
        try:
            with urllib.request.urlopen(api_url, timeout=2) as response:
                payload = json.load(response)

            tunnels = payload.get("tunnels", [])
            for tunnel in tunnels:
                addr = tunnel.get("config", {}).get("addr", "").rstrip("/")
                public_url = tunnel.get("public_url", "")
                if public_url.startswith("https://") and addr == upstream:
                    return public_url

            for tunnel in tunnels:
                public_url = tunnel.get("public_url", "")
                if public_url.startswith("https://"):
                    return public_url
        except Exception:
            time.sleep(1)

    raise RuntimeError("Could not read ngrok public URL from local ngrok API")


def check_esp32(base_url: str) -> None:
    try:
        with urllib.request.urlopen(base_url + "/", timeout=5) as response:
            if response.status >= 400:
                raise RuntimeError(f"HTTP {response.status}")
    except Exception as exc:
        print(f"[WARN] Could not reach ESP32-CAM root page: {base_url}/")
        print(f"[WARN] {exc}")
        print("[WARN] Continuing anyway. Check the ESP32 local IP if ngrok connects but DADN gets no frames.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Expose ESP32-CAM stream through ngrok")
    parser.add_argument(
        "--esp32-url",
        required=True,
        help="ESP32-CAM base URL or stream URL, e.g. http://192.168.1.50:8081 or http://192.168.1.50:8081/stream",
    )
    parser.add_argument("--ngrok-url", default=None, help="Reserved ngrok URL/domain, if you have one")
    parser.add_argument("--url-file", type=Path, default=DEFAULT_URL_FILE)
    parser.add_argument("--ngrok-api-url", default="http://127.0.0.1:4040/api/tunnels")
    args = parser.parse_args()

    if not shutil.which("ngrok"):
        print("[ERROR] ngrok CLI is not installed or not in PATH.")
        print("Install ngrok, then run once: ngrok config add-authtoken <YOUR_NGROK_TOKEN>")
        sys.exit(1)

    esp32_base_url = normalize_esp32_base(args.esp32_url)
    check_esp32(esp32_base_url)

    ngrok_cmd = ["ngrok", "http", esp32_base_url]
    if args.ngrok_url:
        ngrok_cmd.extend(["--url", args.ngrok_url])

    print(f"[INFO] Starting ngrok -> {esp32_base_url}")
    ngrok_proc = subprocess.Popen(ngrok_cmd)

    try:
        public_url = wait_for_ngrok_url(args.ngrok_api_url, esp32_base_url)
        stream_url = public_url.rstrip("/") + "/stream"
        args.url_file.write_text(stream_url + "\n", encoding="utf-8")

        print("\n[SUCCESS] ESP32-CAM public stream URL:")
        print(f"  {stream_url}")
        print("[SUCCESS] Wrote URL file:")
        print(f"  {args.url_file}")
        print("\nRun this on Raspberry Pi DADN:")
        print(f"  python run_stream_server.py --camera-url {stream_url}")
        print("\nPress Ctrl+C to stop ngrok.")

        while True:
            time.sleep(1)
            if ngrok_proc.poll() is not None:
                raise RuntimeError("ngrok stopped")
    except KeyboardInterrupt:
        print("\n[INFO] Stopping ngrok...")
    finally:
        if ngrok_proc.poll() is None:
            ngrok_proc.send_signal(signal.SIGTERM)
            try:
                ngrok_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                ngrok_proc.kill()


if __name__ == "__main__":
    main()
