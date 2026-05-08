#!/usr/bin/env python3
"""
Auto-detect an ESP32-CAM stream and expose it through ngrok.

Default mode scans local networks for an ESP32-CAM MJPEG server on port 8081.
Laptop webcam support is opt-in with: --source laptop
"""

from __future__ import annotations

import argparse
import concurrent.futures
import ipaddress
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Iterable, Optional


STREAM_PATH = "/stream"
DEFAULT_STREAM_PORT = 8081
DEFAULT_URL_FILE = Path(__file__).resolve().parent / ".esp32-ngrok-url"
DEFAULT_STATE_FILE = Path(__file__).resolve().parent / ".auto-camera-ngrok.json"


@dataclass(frozen=True)
class InterfaceNetwork:
    label: str
    ip: str
    network: ipaddress.IPv4Network


@dataclass(frozen=True)
class CameraCandidate:
    host: str
    base_url: str
    stream_url: str
    elapsed_ms: float
    reason: str


@dataclass
class NgrokTunnel:
    pid: int
    upstream: str
    public_base_url: str
    process: Optional[subprocess.Popen] = None
    managed: bool = True

    def is_running(self) -> bool:
        if not self.managed:
            return True
        if self.process is not None:
            return self.process.poll() is None
        return is_process_running(self.pid)


def normalize_base_url(value: str) -> str:
    url = value.strip().rstrip("/")
    if not url:
        raise ValueError("Camera URL is empty")
    if not url.startswith(("http://", "https://")):
        url = "http://" + url
    return url[: -len(STREAM_PATH)] if url.endswith(STREAM_PATH) else url


def public_stream_url(public_base_url: str) -> str:
    return normalize_base_url(public_base_url).rstrip("/") + STREAM_PATH


def is_process_running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        if os.name == "nt":
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}"],
                capture_output=True,
                text=True,
                check=False,
            )
            return str(pid) in result.stdout
        return False


def stop_process(pid: int) -> None:
    if not is_process_running(pid):
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], check=False)
        return
    try:
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


def run_text(command: list[str], timeout: float = 4.0) -> str:
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except Exception:
        return ""
    return (result.stdout or "") + "\n" + (result.stderr or "")


def parse_hosts_from_text(text: str) -> list[str]:
    hosts: list[str] = []
    seen: set[str] = set()
    for value in re.findall(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", text):
        try:
            ip = ipaddress.IPv4Address(value)
        except ValueError:
            continue
        if ip.is_loopback or ip.is_link_local or ip.is_multicast or str(ip).endswith(".255"):
            continue
        host = str(ip)
        if host not in seen:
            seen.add(host)
            hosts.append(host)
    return hosts


def discover_hint_hosts(state_file: Path, url_file: Path, ngrok_api: str) -> list[str]:
    hosts: list[str] = []
    seen: set[str] = set()

    def add_host(value: str) -> None:
        try:
            host = urllib.parse.urlparse(normalize_base_url(value)).hostname or value
            ipaddress.IPv4Address(host)
        except Exception:
            return
        if host not in seen:
            seen.add(host)
            hosts.append(host)

    state = read_state(state_file)
    for value in (state.get("upstream"), state.get("public_url")):
        if isinstance(value, str):
            add_host(value)

    try:
        for line in url_file.read_text(encoding="utf-8").splitlines():
            value = line.strip()
            if value and not value.startswith("#"):
                add_host(value)
    except Exception:
        pass

    for tunnel in get_ngrok_tunnels(ngrok_api):
        addr = tunnel.get("config", {}).get("addr", "")
        if isinstance(addr, str):
            add_host(addr)

    neighbor_commands = [
        ["arp", "-an"],
        ["ip", "neigh"],
        ["cmd.exe", "/c", "arp -a"],
    ]
    if os.name == "nt":
        neighbor_commands = [["arp", "-a"]]
    for command in neighbor_commands:
        hosts.extend(host for host in parse_hosts_from_text(run_text(command)) if host not in seen and not seen.add(host))

    return hosts


def parse_windows_ipconfig(text: str, *, include_virtual: bool) -> list[InterfaceNetwork]:
    networks: list[InterfaceNetwork] = []
    current_adapter = ""
    ip_addr: Optional[str] = None
    mask: Optional[str] = None

    def flush() -> None:
        nonlocal ip_addr, mask
        if not ip_addr or not mask:
            ip_addr = None
            mask = None
            return
        try:
            network = ipaddress.IPv4Network(f"{ip_addr}/{mask}", strict=False)
            if should_scan_network(network, current_adapter, include_virtual=include_virtual):
                networks.append(InterfaceNetwork(label=current_adapter, ip=ip_addr, network=network))
        except ValueError:
            pass
        ip_addr = None
        mask = None

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.endswith(":") and "adapter" in line.lower():
            flush()
            current_adapter = line[:-1]
            continue
        if "IPv4 Address" in line:
            match = re.search(r"(\d+\.\d+\.\d+\.\d+)", line)
            if match:
                ip_addr = match.group(1)
        elif "Subnet Mask" in line:
            match = re.search(r"(\d+\.\d+\.\d+\.\d+)", line)
            if match:
                mask = match.group(1)
    flush()
    return networks


def parse_linux_ip_addr(text: str, *, include_virtual: bool) -> list[InterfaceNetwork]:
    networks: list[InterfaceNetwork] = []
    current_iface = ""
    for raw in text.splitlines():
        iface_match = re.match(r"\d+:\s+([^:]+):", raw)
        if iface_match:
            current_iface = iface_match.group(1)
            continue
        match = re.search(r"inet\s+(\d+\.\d+\.\d+\.\d+)/(\d+)", raw)
        if not match:
            continue
        try:
            network = ipaddress.IPv4Network(f"{match.group(1)}/{match.group(2)}", strict=False)
        except ValueError:
            continue
        if should_scan_network(network, current_iface, include_virtual=include_virtual):
            networks.append(InterfaceNetwork(label=current_iface, ip=match.group(1), network=network))
    return networks


def should_scan_network(network: ipaddress.IPv4Network, label: str, *, include_virtual: bool) -> bool:
    label_lower = label.lower()
    if network.is_loopback or network.is_link_local:
        return False
    if include_virtual:
        return True
    if any(token in label_lower for token in ("docker", "vmware", "virtualbox", "veth")):
        return False
    if "wsl" in label_lower:
        return False
    return True


def is_wsl() -> bool:
    if os.name == "nt":
        return False
    try:
        return "microsoft" in Path("/proc/version").read_text(encoding="utf-8", errors="ignore").lower()
    except Exception:
        return False


def discover_networks(extra_subnets: Iterable[str], *, include_virtual: bool) -> list[InterfaceNetwork]:
    networks: list[InterfaceNetwork] = []

    running_wsl = is_wsl()
    if shutil.which("ip") and (not running_wsl or include_virtual):
        networks.extend(parse_linux_ip_addr(run_text(["ip", "-4", "addr", "show"]), include_virtual=include_virtual))

    if os.name == "nt":
        networks.extend(parse_windows_ipconfig(run_text(["ipconfig"]), include_virtual=include_virtual))
    elif running_wsl and shutil.which("cmd.exe"):
        # From WSL2, pull Windows host adapters as well, so we can scan the actual LAN subnet.
        networks.extend(parse_windows_ipconfig(run_text(["cmd.exe", "/c", "ipconfig"]), include_virtual=include_virtual))

    for subnet in extra_subnets:
        try:
            network = ipaddress.IPv4Network(subnet, strict=False)
            if should_scan_network(network, f"extra:{subnet}", include_virtual=include_virtual):
                networks.append(InterfaceNetwork(label=f"extra:{subnet}", ip=str(network.network_address + 1), network=network))
        except ValueError:
            print(f"[WARN] Ignoring invalid subnet: {subnet}")

    unique: dict[str, InterfaceNetwork] = {}
    for item in networks:
        unique_key = f"{item.label}:{item.network}"
        unique[unique_key] = item
    return sorted(unique.values(), key=lambda item: (item.network.num_addresses, str(item.network)))


def hosts_for_scan(
    networks: Iterable[InterfaceNetwork],
    max_hosts_per_network: int,
    scan_prefix: int,
) -> list[str]:
    hosts: list[str] = []
    seen: set[str] = set()

    for item in networks:
        network = item.network
        effective_network = network
        if network.prefixlen < scan_prefix:
            try:
                effective_network = ipaddress.IPv4Network(f"{item.ip}/{scan_prefix}", strict=False)
            except ValueError:
                effective_network = network

        if effective_network.num_addresses > max_hosts_per_network + 2:
            print(
                f"[WARN] Skipping large subnet {effective_network} ({item.label}); "
                f"pass --max-hosts-per-network {effective_network.num_addresses} to scan it."
            )
            continue
        print(f"[INFO] Scanning subnet: {effective_network} ({item.label})")
        for host in effective_network.hosts():
            value = str(host)
            if value not in seen:
                seen.add(value)
                hosts.append(value)
    return hosts


def merge_hosts(preferred_hosts: Iterable[str], scanned_hosts: Iterable[str]) -> list[str]:
    hosts: list[str] = []
    seen: set[str] = set()
    for host in list(preferred_hosts) + list(scanned_hosts):
        if host not in seen:
            seen.add(host)
            hosts.append(host)
    return hosts


def try_read_url(url: str, timeout: float, read_bytes: int = 256) -> tuple[Optional[str], bytes]:
    request = urllib.request.Request(url, headers={"User-Agent": "auto-camera-ngrok"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        content_type = response.headers.get("content-type", "")
        body = response.read(read_bytes)
        return content_type, body


def validate_esp32_host(host: str, port: int, timeout: float) -> Optional[CameraCandidate]:
    base_url = f"http://{host}:{port}"
    start = time.perf_counter()

    try:
        content_type, body = try_read_url(base_url + "/", timeout)
        text = body.decode("utf-8", errors="ignore")
        if "ESP32-CAM" in text or STREAM_PATH in text:
            elapsed_ms = (time.perf_counter() - start) * 1000
            return CameraCandidate(host, base_url, base_url + STREAM_PATH, elapsed_ms, "root page")
    except Exception:
        pass

    try:
        content_type, _body = try_read_url(base_url + STREAM_PATH, timeout, read_bytes=96)
        if content_type and "multipart/x-mixed-replace" in content_type.lower():
            elapsed_ms = (time.perf_counter() - start) * 1000
            return CameraCandidate(host, base_url, base_url + STREAM_PATH, elapsed_ms, "mjpeg stream")
    except Exception:
        return None

    return None


def find_esp32_candidates(hosts: list[str], port: int, timeout: float, workers: int) -> list[CameraCandidate]:
    candidates: list[CameraCandidate] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(validate_esp32_host, host, port, timeout) for host in hosts]
        for future in concurrent.futures.as_completed(futures):
            candidate = future.result()
            if candidate:
                print(f"[FOUND] {candidate.stream_url} ({candidate.elapsed_ms:.0f} ms, {candidate.reason})")
                candidates.append(candidate)
    return sorted(candidates, key=lambda item: item.elapsed_ms)


class LaptopCameraServer:
    def __init__(self, camera_index: int, host: str, port: int, width: int, height: int, jpeg_quality: int):
        self.camera_index = camera_index
        self.host = host
        self.port = port
        self.width = width
        self.height = height
        self.jpeg_quality = jpeg_quality
        self.latest_jpeg: Optional[bytes] = None
        self.frame_count = 0
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.httpd: Optional[ThreadingHTTPServer] = None

    def start(self) -> None:
        try:
            import cv2
        except ImportError as exc:
            raise RuntimeError("Laptop camera mode requires opencv-python. Install DADN requirements first.") from exc

        def capture_loop() -> None:
            cap = cv2.VideoCapture(self.camera_index)
            if not cap.isOpened():
                print(f"[ERROR] Could not open laptop camera index {self.camera_index}")
                self.stop_event.set()
                return
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
            while not self.stop_event.is_set():
                ok, frame = cap.read()
                if not ok:
                    time.sleep(0.05)
                    continue
                frame = cv2.resize(frame, (self.width, self.height))
                ok, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, self.jpeg_quality])
                if not ok:
                    continue
                with self.lock:
                    self.latest_jpeg = encoded.tobytes()
                    self.frame_count += 1
                time.sleep(0.03)
            cap.release()

        server_ref = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, _format: str, *args: object) -> None:
                return

            def do_GET(self) -> None:
                if self.path == "/health":
                    with server_ref.lock:
                        payload = json.dumps(
                            {"status": "ok", "frames": server_ref.frame_count, "has_frame": server_ref.latest_jpeg is not None}
                        ).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                    return
                if self.path == STREAM_PATH:
                    self.send_response(200)
                    self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
                    self.end_headers()
                    while not server_ref.stop_event.is_set():
                        with server_ref.lock:
                            frame = server_ref.latest_jpeg
                        if frame is None:
                            time.sleep(0.05)
                            continue
                        try:
                            self.wfile.write(b"--frame\r\n")
                            self.wfile.write(b"Content-Type: image/jpeg\r\n")
                            self.wfile.write(b"Content-Length: " + str(len(frame)).encode("ascii") + b"\r\n\r\n")
                            self.wfile.write(frame + b"\r\n")
                        except OSError:
                            break
                        time.sleep(0.1)
                    return
                body = b"<html><body><h2>Laptop Camera Stream</h2><img src='/stream'/></body></html>"
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.httpd = ThreadingHTTPServer((self.host, self.port), Handler)
        threading.Thread(target=capture_loop, daemon=True).start()
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

        deadline = time.time() + 8
        while time.time() < deadline:
            with self.lock:
                if self.latest_jpeg is not None:
                    print(f"[INFO] Laptop camera stream: http://{self.host}:{self.port}{STREAM_PATH}")
                    return
            if self.stop_event.is_set():
                break
            time.sleep(0.2)
        raise RuntimeError("Laptop camera did not produce frames")

    def stop(self) -> None:
        self.stop_event.set()
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()


def ngrok_api_url(base: str) -> str:
    return base.rstrip("/") + "/api/tunnels"


def get_ngrok_tunnels(api_base: str) -> list[dict]:
    try:
        with urllib.request.urlopen(ngrok_api_url(api_base), timeout=2) as response:
            payload = json.load(response)
    except Exception:
        return []
    return payload.get("tunnels", [])


def find_ngrok_public_url(api_base: str, upstream: str) -> Optional[str]:
    upstream = upstream.rstrip("/")
    tunnels = get_ngrok_tunnels(api_base)
    for tunnel in tunnels:
        addr = tunnel.get("config", {}).get("addr", "").rstrip("/")
        public_url = tunnel.get("public_url", "")
        if public_url.startswith("https://") and addr == upstream:
            return public_url
    return None


def ensure_ngrok(upstream: str, api_base: str, state_file: Path, ngrok_url: Optional[str]) -> NgrokTunnel:
    upstream = upstream.rstrip("/")
    state = read_state(state_file)
    old_pid = int(state.get("pid", 0) or 0)
    old_upstream = str(state.get("upstream", "")).rstrip("/")

    # If we already own a running tunnel for the same upstream, reuse it.
    if old_pid and old_upstream == upstream and is_process_running(old_pid):
        existing_url = find_ngrok_public_url(api_base, upstream)
        if existing_url:
            print(f"[INFO] Reusing managed ngrok tunnel: {existing_url}")
            return NgrokTunnel(pid=old_pid, upstream=upstream, public_base_url=existing_url)

    # If upstream changed, stop the old managed tunnel.
    if old_pid and old_upstream and old_upstream != upstream and is_process_running(old_pid):
        print(f"[INFO] Stopping old managed ngrok tunnel: {old_upstream}")
        stop_process(old_pid)
        time.sleep(0.8)

    existing_url = find_ngrok_public_url(api_base, upstream)
    if existing_url:
        print(f"[INFO] Reusing existing ngrok tunnel: {existing_url}")
        return NgrokTunnel(pid=0, upstream=upstream, public_base_url=existing_url, managed=False)

    if not shutil.which("ngrok"):
        raise RuntimeError("ngrok CLI is not installed or not in PATH. Run: ngrok config add-authtoken <YOUR_TOKEN>")

    command = ["ngrok", "http", upstream]
    if ngrok_url:
        command.extend(["--url", ngrok_url])
    print(f"[INFO] Starting ngrok -> {upstream}")
    process = subprocess.Popen(command)

    deadline = time.time() + 30
    while time.time() < deadline:
        public_url = find_ngrok_public_url(api_base, upstream)
        if public_url:
            write_state(
                state_file,
                {
                    "pid": process.pid,
                    "upstream": upstream,
                    "public_url": public_url,
                    "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                },
            )
            return NgrokTunnel(pid=process.pid, upstream=upstream, public_base_url=public_url, process=process)
        if process.poll() is not None:
            raise RuntimeError("ngrok exited before publishing a tunnel")
        time.sleep(1)

    raise RuntimeError("Timed out waiting for ngrok public URL")


def select_esp32(args: argparse.Namespace) -> CameraCandidate:
    hint_hosts = discover_hint_hosts(args.state_file, args.url_file, args.ngrok_api)
    if hint_hosts:
        print(f"[INFO] Trying hinted hosts first: {', '.join(hint_hosts)}")
        candidates = find_esp32_candidates(hint_hosts, args.port, args.timeout, args.workers)
        if candidates:
            print("[INFO] ESP32 candidates:")
            for candidate in candidates:
                print(f"  - {candidate.stream_url} ({candidate.elapsed_ms:.0f} ms, {candidate.reason})")
            return candidates[0]

    networks = discover_networks(args.subnet, include_virtual=args.include_virtual)
    if not networks:
        raise RuntimeError("No scannable local subnet found")
    hosts = merge_hosts(hint_hosts, hosts_for_scan(networks, args.max_hosts_per_network, args.scan_prefix))
    if not hosts:
        raise RuntimeError("No hosts to scan")
    print(f"[INFO] Scanning {len(hosts)} hosts on port {args.port}")
    candidates = find_esp32_candidates(hosts, args.port, args.timeout, args.workers)
    if not candidates:
        raise RuntimeError("No ESP32-CAM found. Check WiFi, power, or use --source laptop.")
    print("[INFO] ESP32 candidates:")
    for candidate in candidates:
        print(f"  - {candidate.stream_url} ({candidate.elapsed_ms:.0f} ms, {candidate.reason})")
    return candidates[0]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Auto-detect camera source and expose it through ngrok")
    parser.add_argument("--source", choices=["esp32", "laptop"], default="esp32")
    parser.add_argument("--port", type=int, default=DEFAULT_STREAM_PORT)
    parser.add_argument("--timeout", type=float, default=0.35)
    parser.add_argument("--workers", type=int, default=512)
    parser.add_argument("--scan-prefix", type=int, default=24, help="If your LAN is /16, scan only your /24 by default")
    parser.add_argument("--max-hosts-per-network", type=int, default=1024)
    parser.add_argument("--include-virtual", action="store_true", help="Include Docker/WSL/virtual adapters")
    parser.add_argument("--subnet", action="append", default=[], help="Extra subnet to scan, e.g. 10.130.0.0/16")
    parser.add_argument("--url-file", type=Path, default=DEFAULT_URL_FILE)
    parser.add_argument("--state-file", type=Path, default=DEFAULT_STATE_FILE)
    parser.add_argument("--ngrok-api", default="http://127.0.0.1:4040")
    parser.add_argument("--ngrok-url", default=None, help="Reserved ngrok URL/domain, if available")
    parser.add_argument("--rescan-interval", type=float, default=15.0, help="Seconds between ESP32 re-detection")
    parser.add_argument("--once", action="store_true", help="Start ngrok and exit (do not watch for IP changes)")
    parser.add_argument("--camera-index", type=int, default=0)
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=480)
    parser.add_argument("--jpeg-quality", type=int, default=70)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    laptop_server: Optional[LaptopCameraServer] = None

    esp32_host: Optional[str] = None

    if args.source == "laptop":
        laptop_server = LaptopCameraServer(
            camera_index=args.camera_index,
            host="127.0.0.1",
            port=args.port,
            width=args.width,
            height=args.height,
            jpeg_quality=args.jpeg_quality,
        )
        laptop_server.start()
        upstream = f"http://127.0.0.1:{args.port}"
        local_stream = upstream + STREAM_PATH
    else:
        candidate = select_esp32(args)
        upstream = candidate.base_url
        local_stream = candidate.stream_url
        esp32_host = candidate.host

    tunnel: Optional[NgrokTunnel] = None
    keep_tunnel_after_exit = False
    try:
        tunnel = ensure_ngrok(upstream, args.ngrok_api, args.state_file, args.ngrok_url)

        def publish_urls(public_base: str) -> str:
            stream_url = public_stream_url(public_base)
            args.url_file.write_text(stream_url + "\n", encoding="utf-8")

            print("\n[SUCCESS] Local stream:")
            print(f"  {local_stream}")
            print("[SUCCESS] Public stream:")
            print(f"  {stream_url}")
            print("[SUCCESS] Wrote URL file:")
            print(f"  {args.url_file}")
            print("\nRun this on Raspberry Pi DADN:")
            print(f"  python run_stream_server.py --camera-url {stream_url}")
            return stream_url

        _current_stream_url = publish_urls(tunnel.public_base_url)

        if args.once:
            if args.source == "laptop":
                print("[WARN] --once is ignored for laptop mode because the MJPEG server lives in this process.")
            else:
                keep_tunnel_after_exit = True
                print("[INFO] Leaving ngrok running in the background.")
                return

        if args.source == "laptop":
            while True:
                time.sleep(1)
                if tunnel and not tunnel.is_running():
                    raise RuntimeError("ngrok stopped")

        while True:
            time.sleep(max(1.0, args.rescan_interval))

            if tunnel and not tunnel.is_running():
                raise RuntimeError("ngrok stopped")

            # ESP32 watch mode: only rescan when the current ESP32 host stops responding.
            if esp32_host and validate_esp32_host(esp32_host, args.port, args.timeout):
                continue

            try:
                new_candidate = select_esp32(args)
            except Exception as exc:
                print(f"[WARN] ESP32 not found during rescan: {exc}")
                continue

            esp32_host = new_candidate.host
            new_upstream = new_candidate.base_url.rstrip("/")
            if tunnel and new_upstream != tunnel.upstream.rstrip("/"):
                print(f"[INFO] ESP32 upstream changed: {tunnel.upstream} -> {new_upstream}")
                stop_process(tunnel.pid)
                tunnel = ensure_ngrok(new_upstream, args.ngrok_api, args.state_file, args.ngrok_url)
            local_stream = new_candidate.stream_url
            _current_stream_url = publish_urls(tunnel.public_base_url)
    except KeyboardInterrupt:
        print("\n[INFO] Stopping camera launcher...")
    finally:
        if tunnel and tunnel.managed and tunnel.is_running() and not keep_tunnel_after_exit:
            stop_process(tunnel.pid)
        if laptop_server:
            laptop_server.stop()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"[ERROR] {exc}")
        sys.exit(1)
