#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Optional


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TOOLS_DIR = PROJECT_ROOT / ".tools"
STREAM_PATH = "/stream"


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


def parse_stream_url(text: str, port: int) -> Optional[str]:
    match = re.search(r"https?://(?:\d{1,3}\.){3}\d{1,3}(?::\d+)?/stream\b", text)
    if match:
        return match.group(0)
    match = re.search(r"(?:Local IP|IP Address|IP)\s*:\s*((?:\d{1,3}\.){3}\d{1,3})", text, re.IGNORECASE)
    if match:
        return f"http://{match.group(1)}:{port}{STREAM_PATH}"
    return None


def validate_stream_url(url: str, timeout: float) -> bool:
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "dadn-esp32-one-run"})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            content_type = response.headers.get("content-type", "").lower()
            return "multipart" in content_type or "image/jpeg" in content_type
    except Exception:
        return False


def serial_ports_from_pyserial() -> list[str]:
    try:
        from serial.tools import list_ports
    except Exception:
        return []

    preferred: list[str] = []
    fallback: list[str] = []
    markers = ("ch340", "cp210", "usb", "uart", "serial", "silicon labs", "wch")
    for port in list_ports.comports():
        text = " ".join(
            str(value or "")
            for value in (port.device, port.description, port.manufacturer, port.hwid)
        ).lower()
        if any(marker in text for marker in markers):
            preferred.append(port.device)
        else:
            fallback.append(port.device)
    return preferred + [item for item in fallback if item not in preferred]


def read_serial_for_stream_url(port_name: str, baud: int, seconds: float, stream_port: int) -> Optional[str]:
    try:
        import serial
    except Exception as exc:
        print("[WARN] pyserial is not installed; cannot read ESP32 Serial Monitor automatically.")
        print("[WARN] Install with: python -m pip install pyserial")
        return None

    print(f"[INFO] Reading ESP32 serial log from {port_name} at {baud} baud...")
    deadline = time.time() + seconds
    seen: list[str] = []
    try:
        with serial.Serial(port_name, baudrate=baud, timeout=0.5) as ser:
            # Pulse RTS to reset many ESP32-CAM USB-UART adapters and catch boot logs.
            try:
                ser.rts = True
                time.sleep(0.15)
                ser.rts = False
            except Exception:
                pass
            while time.time() < deadline:
                raw = ser.readline()
                if not raw:
                    continue
                line = raw.decode("utf-8", errors="ignore").strip()
                if line:
                    print(f"[SERIAL:{port_name}] {line}")
                    seen.append(line)
                    stream_url = parse_stream_url("\n".join(seen[-30:]), stream_port)
                    if stream_url:
                        return stream_url
    except Exception as exc:
        print(f"[WARN] Could not read serial port {port_name}: {exc}")
    return None


def discover_stream_from_serial(args: argparse.Namespace) -> Optional[str]:
    ports = [args.serial_port] if args.serial_port else serial_ports_from_pyserial()
    ports = [port for port in ports if port]
    if not ports:
        print("[WARN] No serial ports found for ESP32 fallback.")
        return None
    for port_name in ports:
        stream_url = read_serial_for_stream_url(port_name, args.serial_baud, args.serial_timeout, args.port)
        if stream_url:
            print(f"[INFO] Serial fallback found ESP32 stream URL: {stream_url}")
            if validate_stream_url(stream_url, args.timeout):
                return stream_url
            print(f"[WARN] Serial URL did not validate as MJPEG stream: {stream_url}")
    return None


def expose_known_stream_url(stream_url: str, env: dict[str, str], args: argparse.Namespace) -> int:
    command = [
        sys.executable,
        str(Path(__file__).resolve().parent / "expose_esp32_ngrok.py"),
        "--esp32-url",
        stream_url,
    ]
    if args.ngrok_url:
        command.extend(["--ngrok-url", args.ngrok_url])
    print("[INFO] Exposing ESP32 stream discovered from serial...")
    return subprocess.call(command, cwd=Path(__file__).resolve().parent, env=env)


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
    parser.add_argument("--serial-fallback", action="store_true", default=True)
    parser.add_argument("--serial-port", default=None, help="Explicit ESP32 serial port, e.g. COM13 or /dev/ttyUSB0")
    parser.add_argument("--serial-baud", type=int, default=115200)
    parser.add_argument("--serial-timeout", type=float, default=18.0)
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
    result = subprocess.run(command, cwd=PROJECT_ROOT, env=env, text=True, capture_output=True)
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    if result.returncode == 0:
        return 0

    if not args.serial_fallback:
        return result.returncode

    print("[INFO] LAN scan failed; trying ESP32 Serial Monitor fallback...")
    stream_url = discover_stream_from_serial(args)
    if not stream_url:
        print("[ERROR] Could not discover ESP32 stream from LAN scan or serial fallback.")
        return result.returncode
    return expose_known_stream_url(stream_url, env, args)


if __name__ == "__main__":
    raise SystemExit(main())
