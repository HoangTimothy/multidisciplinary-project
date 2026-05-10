#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ipaddress
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
from urllib.parse import urlparse, urlunparse
from typing import Optional


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TOOLS_DIR = PROJECT_ROOT / ".tools"
STREAM_PATH = "/stream"
DEFAULT_PORTS = [8081, 80, 81, 8080]
DOWNLOAD_MODE_MARKERS = ("DOWNLOAD_BOOT", "waiting for download")
FIRMWARE_READY_MARKERS = ("ESP32-CAM PlatformIO Stream", "Stream URL:", "Local IP:")
WIFI_FAILURE_MARKERS = ("WiFi connection failed", "Stream URL: http://0.0.0.0")


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


def parse_ports(value: str) -> list[int]:
    ports: list[int] = []
    for item in value.split(","):
        item = item.strip()
        if not item:
            continue
        port = int(item)
        if port not in ports:
            ports.append(port)
    return ports


def parse_stream_url(text: str) -> Optional[str]:
    match = re.search(r"https?://(?:\d{1,3}\.){3}\d{1,3}(?::\d+)?/stream\b", text)
    if match:
        url = match.group(0)
        host_match = re.search(r"https?://((?:\d{1,3}\.){3}\d{1,3})", url)
        if host_match and is_usable_camera_ip(host_match.group(1)):
            return url
    return None


def parse_ip(text: str) -> Optional[str]:
    match = re.search(r"(?:Local IP|IP Address|IP)\s*:\s*((?:\d{1,3}\.){3}\d{1,3})", text, re.IGNORECASE)
    if match and is_usable_camera_ip(match.group(1)):
        return match.group(1)
    return None


def is_usable_camera_ip(value: str) -> bool:
    try:
        ip = ipaddress.IPv4Address(value)
    except ValueError:
        return False
    return not (ip.is_unspecified or ip.is_loopback or ip.is_multicast or ip.is_reserved)


def validate_stream_url(url: str, timeout: float) -> bool:
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "dadn-esp32-one-run"})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            content_type = response.headers.get("content-type", "").lower()
            return "multipart" in content_type or "image/jpeg" in content_type
    except Exception:
        return False


def stream_base_url(url: str) -> str:
    normalized = normalize_stream_url(url)
    parsed = urlparse(normalized)
    return urlunparse((parsed.scheme, parsed.netloc, "", "", "", "")).rstrip("/")


def validate_esp32_root(url: str, timeout: float) -> bool:
    base_url = stream_base_url(url)
    try:
        request = urllib.request.Request(base_url + "/", headers={"User-Agent": "dadn-esp32-one-run"})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            content_type = response.headers.get("content-type", "").lower()
            body = response.read(512).decode("utf-8", errors="ignore")
            return response.status < 400 and ("text/html" in content_type or "ESP32-CAM" in body or STREAM_PATH in body)
    except Exception:
        return False


def validate_esp32_stream_candidate(url: str, timeout: float) -> bool:
    # Prefer the root page. Opening /stream as a probe can tie up the ESP32
    # single-threaded WebServer until its stream timeout expires.
    root_timeout = max(timeout, 2.0)
    return validate_esp32_root(url, root_timeout) or validate_stream_url(url, root_timeout)


def normalize_stream_url(value: str) -> str:
    url = value.strip().rstrip("/")
    if not url:
        raise ValueError("ESP32 URL is empty")
    if not url.startswith(("http://", "https://")):
        url = "http://" + url
    return url if url.endswith(STREAM_PATH) else url + STREAM_PATH


def stream_urls_for_ip(ip: str, ports: list[int]) -> list[str]:
    return [f"http://{ip}:{port}{STREAM_PATH}" if port != 80 else f"http://{ip}{STREAM_PATH}" for port in ports]


def validate_first_stream_url(urls: list[str], timeout: float) -> Optional[str]:
    for url in urls:
        print(f"[INFO] Checking stream candidate: {url}")
        if validate_esp32_stream_candidate(url, timeout):
            return url
    return None


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


def saw_download_mode(lines: list[str]) -> bool:
    text = "\n".join(lines)
    return any(marker in text for marker in DOWNLOAD_MODE_MARKERS)


def saw_firmware_ready(lines: list[str]) -> bool:
    text = "\n".join(lines)
    return any(marker in text for marker in FIRMWARE_READY_MARKERS)


def saw_wifi_failure(lines: list[str]) -> bool:
    text = "\n".join(lines)
    return any(marker in text for marker in WIFI_FAILURE_MARKERS)


def connecting_ssids(lines: list[str]) -> list[str]:
    ssids: list[str] = []
    for line in lines:
        match = re.search(r"Connecting WiFi:\s*(.+)$", line)
        if match:
            ssid = match.group(1).strip()
            if ssid and ssid not in ssids:
                ssids.append(ssid)
    return ssids


def current_windows_wifi_ssid() -> Optional[str]:
    if not shutil.which("cmd.exe"):
        return None
    try:
        result = subprocess.run(
            ["cmd.exe", "/c", "netsh", "wlan", "show", "interfaces"],
            text=True,
            capture_output=True,
            timeout=4,
            check=False,
        )
    except Exception:
        return None
    for line in result.stdout.splitlines():
        stripped = line.strip()
        if stripped.startswith("SSID") and "BSSID" not in stripped:
            _, _, value = stripped.partition(":")
            ssid = value.strip()
            return ssid or None
    return None


def print_download_mode_help(port_name: str) -> None:
    print(f"[ERROR] {port_name} is in ESP32 download/flash mode, not running the camera firmware.")
    print("[ERROR] Fix on hardware, then rerun this command:")
    print("        1. Disconnect GPIO0 from GND / release BOOT or FLASH button.")
    print("        2. Press RESET, or unplug and plug the ESP32-CAM USB power again.")
    print("        3. Serial should print 'ESP32-CAM PlatformIO Stream' and 'Stream URL: http://<ip>:8081/stream'.")


def print_wifi_failure_help(lines: list[str]) -> None:
    ssids = connecting_ssids(lines)
    if ssids:
        print(f"[ERROR] ESP32 firmware tried WiFi SSID(s): {', '.join(ssids)}")
    current_ssid = current_windows_wifi_ssid()
    if current_ssid:
        print(f"[INFO] This Windows laptop is currently connected to WiFi SSID: {current_ssid}")
    print("[ERROR] ESP32-CAM booted and camera initialized, but WiFi did not connect.")
    print("[ERROR] Reflash/configure ESP32-CAM with a 2.4 GHz WiFi SSID/password reachable by this laptop.")
    print("[ERROR] Until Serial prints a real Local IP, LAN scan and ngrok cannot expose the stream.")


def read_serial_for_stream_url(port_name: str, baud: int, seconds: float, stream_ports: list[int], timeout: float) -> Optional[str]:
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
            # Keep auto-reset lines inactive while reading. Some USB-UART adapters
            # wire DTR/RTS to GPIO0/EN; asserting them can hold ESP32 in bootloader.
            try:
                ser.dtr = False
                ser.rts = False
                time.sleep(0.3)
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
                    recent = "\n".join(seen[-30:])
                    stream_url = parse_stream_url(recent)
                    if stream_url:
                        if validate_esp32_stream_candidate(stream_url, timeout):
                            return stream_url
                        print(f"[WARN] Serial printed a stream URL, but it is not reachable yet: {stream_url}")
                    ip = parse_ip(recent)
                    if ip:
                        stream_url = validate_first_stream_url(stream_urls_for_ip(ip, stream_ports), timeout)
                        if stream_url:
                            return stream_url
            if saw_download_mode(seen) and not saw_firmware_ready(seen):
                print_download_mode_help(port_name)
            elif saw_wifi_failure(seen):
                print_wifi_failure_help(seen)
    except Exception as exc:
        print(f"[WARN] Could not read serial port {port_name}: {exc}")
    return None


def discover_stream_from_serial(args: argparse.Namespace) -> Optional[str]:
    ports = [args.serial_port] if args.serial_port else serial_ports_from_pyserial()
    ports = [port for port in ports if port]
    if not ports:
        print("[WARN] No serial ports found for ESP32 fallback.")
        return None
    stream_ports = parse_ports(args.ports)
    for port_name in ports:
        stream_url = read_serial_for_stream_url(
            port_name,
            args.serial_baud,
            args.serial_timeout,
            stream_ports,
            args.timeout,
        )
        if stream_url:
            print(f"[INFO] Serial fallback found ESP32 stream URL: {stream_url}")
            return stream_url
    return None


def discover_stream_from_serial_if_enabled(args: argparse.Namespace) -> Optional[str]:
    if not args.serial_fallback:
        return None
    print("[INFO] Trying ESP32 Serial Monitor discovery...")
    return discover_stream_from_serial(args)


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
    parser.add_argument("--esp32-ip", default=None, help="Known ESP32-CAM LAN IP. Tries --ports and skips subnet scan.")
    parser.add_argument("--esp32-url", default=None, help="Known ESP32-CAM local base/stream URL. Skips subnet scan.")
    parser.add_argument("--subnet", action="append", default=[], help="Extra subnet to scan, e.g. 192.168.1.0/24")
    parser.add_argument("--port", type=int, default=None, help="Single port to scan. Overrides --ports.")
    parser.add_argument(
        "--ports",
        default=",".join(str(item) for item in DEFAULT_PORTS),
        help="Comma-separated ports to scan, default: 8081,80,81,8080",
    )
    parser.add_argument("--timeout", type=float, default=0.35)
    parser.add_argument("--workers", type=int, default=64)
    parser.add_argument("--ngrok-url", default=None)
    parser.add_argument("--serial-fallback", action="store_true", default=True)
    parser.add_argument("--serial-port", default=None, help="Explicit ESP32 serial port, e.g. COM13 or /dev/ttyUSB0")
    parser.add_argument("--serial-baud", type=int, default=115200)
    parser.add_argument("--serial-timeout", type=float, default=18.0)
    parser.add_argument(
        "--serial-first",
        action="store_true",
        default=False,
        help="Read Serial Monitor before subnet scanning. Defaults on when --serial-port is provided.",
    )
    args = parser.parse_args()

    ngrok_path = ensure_ngrok(args.install_ngrok)
    configure_ngrok(ngrok_path, args.ngrok_token)

    env = dict(os.environ)
    env["PATH"] = str(ngrok_path.parent) + os.pathsep + env.get("PATH", "")

    scan_ports = [args.port] if args.port else parse_ports(args.ports)

    if args.esp32_url:
        stream_url = normalize_stream_url(args.esp32_url)
        print(f"[INFO] Checking known ESP32 stream URL: {stream_url}")
        if not validate_esp32_stream_candidate(stream_url, args.timeout):
            print("[ERROR] Known ESP32 URL did not respond as an MJPEG/JPEG stream.")
            return 1
        return expose_known_stream_url(stream_url, env, args)

    if args.esp32_ip:
        print(f"[INFO] Checking known ESP32 IP across ports: {args.esp32_ip}")
        stream_url = validate_first_stream_url(stream_urls_for_ip(args.esp32_ip, scan_ports), args.timeout)
        if not stream_url:
            print(f"[ERROR] No ESP32-CAM stream found at {args.esp32_ip} on ports: {', '.join(map(str, scan_ports))}")
            return 1
        return expose_known_stream_url(stream_url, env, args)

    if args.serial_first or args.serial_port:
        stream_url = discover_stream_from_serial_if_enabled(args)
        if stream_url:
            return expose_known_stream_url(stream_url, env, args)
        print("[WARN] Serial discovery did not return a reachable stream; falling back to LAN scan.")

    result = None
    for port in scan_ports:
        command = [
            sys.executable,
            str(Path(__file__).resolve().parent / "auto_camera_ngrok.py"),
            "--port",
            str(port),
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

        print(f"[INFO] Starting ESP32-CAM auto-detect + ngrok expose on port {port}...")
        result = subprocess.run(command, cwd=PROJECT_ROOT, env=env, text=True, capture_output=True)
        if result.stdout:
            print(result.stdout, end="")
        if result.stderr:
            print(result.stderr, end="", file=sys.stderr)
        if result.returncode == 0:
            return 0
        print(f"[WARN] No ESP32-CAM found on port {port}.")

    if not args.serial_fallback or args.serial_first or args.serial_port:
        return result.returncode if result else 1

    print("[INFO] LAN scan failed; trying ESP32 Serial Monitor fallback...")
    stream_url = discover_stream_from_serial_if_enabled(args)
    if not stream_url:
        print("[ERROR] Could not discover ESP32 stream from LAN scan or serial fallback.")
        return result.returncode if result else 1
    return expose_known_stream_url(stream_url, env, args)


if __name__ == "__main__":
    raise SystemExit(main())
