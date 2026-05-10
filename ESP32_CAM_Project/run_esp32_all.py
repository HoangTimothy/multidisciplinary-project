#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TOOLS_DIR = PROJECT_ROOT / ".tools"


def ngrok_download_url() -> str:
    system = platform.system().lower()
    machine = platform.machine().lower()
    if system != "linux":
        raise RuntimeError("Auto-install ngrok currently supports Linux/WSL/Raspberry Pi only.")
    if machine in {"x86_64", "amd64"}:
        arch = "amd64"
    elif machine in {"aarch64", "arm64"}:
        arch = "arm64"
    elif machine.startswith("arm"):
        arch = "arm"
    else:
        raise RuntimeError(f"Unsupported CPU architecture for ngrok auto-install: {machine}")
    return f"https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-linux-{arch}.tgz"


def ensure_ngrok(auto_install: bool) -> Path:
    existing = shutil.which("ngrok")
    if existing:
        return Path(existing)
    local = TOOLS_DIR / "ngrok"
    if local.exists():
        return local
    if not auto_install:
        raise RuntimeError("ngrok is not in PATH. Re-run with --install-ngrok or install ngrok manually.")

    TOOLS_DIR.mkdir(parents=True, exist_ok=True)
    url = ngrok_download_url()
    print("[INFO] ngrok not found; downloading ngrok v3 agent...")
    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / "ngrok.tgz"
        urllib.request.urlretrieve(url, archive)
        with tarfile.open(archive) as handle:
            handle.extractall(tmp)
        extracted = Path(tmp) / "ngrok"
        if not extracted.exists():
            raise RuntimeError("Downloaded ngrok archive did not contain ngrok binary")
        shutil.copy2(extracted, local)
    local.chmod(0o755)
    return local


def configure_ngrok(ngrok_path: Path, token: str | None) -> None:
    if not token:
        return
    print("[INFO] Configuring ngrok authtoken from environment/argument...")
    result = subprocess.run(
        [str(ngrok_path), "config", "add-authtoken", token],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        stderr = result.stderr.replace(token, "***")
        stdout = result.stdout.replace(token, "***")
        raise RuntimeError(f"ngrok authtoken setup failed\n{stdout}\n{stderr}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="One-command ESP32-CAM detect + ngrok expose launcher"
    )
    parser.add_argument("--ngrok-token", default=os.getenv("NGROK_AUTHTOKEN"))
    parser.add_argument("--install-ngrok", action="store_true", default=True)
    parser.add_argument("--watch", action="store_true", help="Keep watching ESP32 IP changes instead of one-shot")
    parser.add_argument("--subnet", action="append", default=[], help="Extra subnet to scan, e.g. 192.168.1.0/24")
    parser.add_argument("--port", type=int, default=8081)
    parser.add_argument("--timeout", type=float, default=0.35)
    parser.add_argument("--workers", type=int, default=64)
    parser.add_argument("--ngrok-url", default=None)
    args = parser.parse_args()

    ngrok_path = ensure_ngrok(args.install_ngrok)
    configure_ngrok(ngrok_path, args.ngrok_token)

    env = dict(os.environ)
    env["PATH"] = str(ngrok_path.parent) + os.pathsep + env.get("PATH", "")

    command = [
        sys.executable,
        str(Path(__file__).resolve().parent / "auto_camera_ngrok.py"),
        "--port",
        str(args.port),
        "--timeout",
        str(args.timeout),
        "--workers",
        str(args.workers),
    ]
    if not args.watch:
        command.append("--once")
    for subnet in args.subnet:
        command.extend(["--subnet", subnet])
    if args.ngrok_url:
        command.extend(["--ngrok-url", args.ngrok_url])

    print("[INFO] Starting ESP32-CAM auto-detect + ngrok expose...")
    return subprocess.call(command, cwd=PROJECT_ROOT, env=env)


if __name__ == "__main__":
    raise SystemExit(main())
