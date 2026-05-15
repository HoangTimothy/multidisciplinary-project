#!/usr/bin/env python3
"""
Run the DADN web dashboard and expose it through ngrok.

Use this on the Raspberry Pi where the DADN model/inference server runs.
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
from typing import Optional


DADN_DIR = Path(__file__).resolve().parent.parent
DEFAULT_URL_FILE = DADN_DIR / ".dadn-dashboard-url"
DEFAULT_STATE_FILE = DADN_DIR / ".dadn-dashboard-ngrok.json"


def normalize_stream_url(value: str) -> str:
    url = value.strip().rstrip("/")
    if not url:
        raise ValueError("Camera stream URL is empty")
    if not url.startswith(("http://", "https://")):
        scheme = "http" if url.startswith(("localhost", "127.0.0.1")) else "https"
        url = f"{scheme}://{url}"
    return url if url.endswith("/stream") else url + "/stream"


def read_url_file(path: Path) -> Optional[str]:
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            value = line.strip()
            if value and not value.startswith("#"):
                return value
    except FileNotFoundError:
        return None
    return None


def is_process_running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        import os

        os.kill(pid, 0)
        return True
    except OSError:
        return False


def stop_process(pid: int) -> None:
    if not is_process_running(pid):
        return
    try:
        import os

        os.kill(pid, signal.SIGTERM)
    except OSError:
        return
    deadline = time.time() + 5
    while time.time() < deadline:
        if not is_process_running(pid):
            return
        time.sleep(0.2)
    try:
        os.kill(pid, signal.SIGKILL)
    except OSError:
        pass


def read_state(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def write_state(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def wait_for_dashboard(port: int, timeout_seconds: int = 180) -> None:
    deadline = time.time() + timeout_seconds
    url = f"http://127.0.0.1:{port}/health"
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status == 200:
                    return
        except Exception:
            time.sleep(1)
    raise RuntimeError(f"DADN dashboard did not become healthy at {url}")


def ngrok_api_url(api_base: str) -> str:
    return api_base.rstrip("/") + "/api/tunnels"


def get_ngrok_tunnels(api_base: str) -> list[dict]:
    try:
        with urllib.request.urlopen(ngrok_api_url(api_base), timeout=2) as response:
            payload = json.load(response)
    except Exception:
        return []
    return payload.get("tunnels", [])


def find_public_url(api_base: str, upstreams: set[str]) -> Optional[str]:
    for tunnel in get_ngrok_tunnels(api_base):
        addr = tunnel.get("config", {}).get("addr", "").rstrip("/")
        public_url = tunnel.get("public_url", "")
        if public_url.startswith("https://") and addr in upstreams:
            return public_url
    return None


def ensure_ngrok(port: int, api_base: str, state_file: Path, ngrok_url: Optional[str]) -> tuple[Optional[subprocess.Popen], str]:
    upstreams = {f"http://127.0.0.1:{port}", f"http://localhost:{port}", str(port)}
    state = read_state(state_file)
    old_pid = int(state.get("pid", 0) or 0)
    old_port = int(state.get("port", 0) or 0)

    if old_pid and old_port and old_port != port and is_process_running(old_pid):
        print(f"[INFO] Stopping old dashboard ngrok tunnel on port {old_port}")
        stop_process(old_pid)
        time.sleep(0.8)

    existing_url = find_public_url(api_base, upstreams)
    if existing_url:
        print(f"[INFO] Reusing existing dashboard ngrok tunnel: {existing_url}")
        return None, existing_url

    if not shutil.which("ngrok"):
        raise RuntimeError("ngrok CLI is not installed or not in PATH. Run: ngrok config add-authtoken <YOUR_TOKEN>")

    command = ["ngrok", "http", str(port)]
    if ngrok_url:
        command.extend(["--url", ngrok_url])
    print(f"[INFO] Starting ngrok dashboard tunnel -> http://127.0.0.1:{port}")
    process = subprocess.Popen(command)

    deadline = time.time() + 30
    while time.time() < deadline:
        public_url = find_public_url(api_base, upstreams)
        if public_url:
            write_state(
                state_file,
                {
                    "pid": process.pid,
                    "port": port,
                    "public_url": public_url,
                    "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                },
            )
            return process, public_url
        if process.poll() is not None:
            raise RuntimeError("ngrok exited before publishing a dashboard tunnel")
        time.sleep(1)
    raise RuntimeError("Timed out waiting for dashboard ngrok public URL")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run DADN dashboard and expose it through ngrok")
    parser.add_argument("--camera-url", default=None, help="ESP32-CAM/ngrok stream URL ending in /stream")
    parser.add_argument("--camera-url-file", type=Path, default=DADN_DIR / ".camera-ngrok-url")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--no-server", action="store_true", help="Only expose an already-running DADN server")
    parser.add_argument("--startup-timeout", type=int, default=180, help="Seconds to wait for DADN /health")
    parser.add_argument("--ngrok-api", default="http://127.0.0.1:4040")
    parser.add_argument("--ngrok-url", default=None, help="Reserved ngrok URL/domain, if available")
    parser.add_argument("--url-file", type=Path, default=DEFAULT_URL_FILE)
    parser.add_argument("--state-file", type=Path, default=DEFAULT_STATE_FILE)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    server_process: Optional[subprocess.Popen] = None
    ngrok_process: Optional[subprocess.Popen] = None

    camera_url = args.camera_url or read_url_file(args.camera_url_file)
    if not args.no_server and not camera_url:
        raise RuntimeError("Provide --camera-url or --camera-url-file when starting the DADN server")

    try:
        if not args.no_server:
            assert camera_url is not None
            camera_url = normalize_stream_url(camera_url)
            command = [
                sys.executable,
                str(DADN_DIR / "run_stream_server.py"),
                "--camera-url",
                camera_url,
                "--port",
                str(args.port),
                "--no-browser",
            ]
            print(f"[INFO] Starting DADN dashboard on port {args.port}")
            print(f"[INFO] Camera stream: {camera_url}")
            server_process = subprocess.Popen(command, cwd=DADN_DIR)

        wait_for_dashboard(args.port, args.startup_timeout)
        ngrok_process, public_url = ensure_ngrok(args.port, args.ngrok_api, args.state_file, args.ngrok_url)
        args.url_file.write_text(public_url.rstrip("/") + "\n", encoding="utf-8")

        print("\n[SUCCESS] DADN dashboard:")
        print(f"  local:  http://127.0.0.1:{args.port}")
        print(f"  public: {public_url}")
        print("[SUCCESS] Wrote URL file:")
        print(f"  {args.url_file}")
        print("\nPress Ctrl+C to stop the dashboard launcher.")

        while True:
            time.sleep(1)
            if server_process and server_process.poll() is not None:
                raise RuntimeError("DADN server stopped")
            if ngrok_process and ngrok_process.poll() is not None:
                raise RuntimeError("ngrok stopped")
    except KeyboardInterrupt:
        print("\n[INFO] Stopping DADN dashboard launcher...")
    finally:
        if ngrok_process and ngrok_process.poll() is None:
            stop_process(ngrok_process.pid)
        if server_process and server_process.poll() is None:
            stop_process(server_process.pid)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"[ERROR] {exc}")
        sys.exit(1)
