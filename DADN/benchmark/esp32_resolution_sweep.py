#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Optional


REPO_ROOT = Path(__file__).resolve().parents[2]
DADN_DIR = REPO_ROOT / "DADN"
ESP32_DIR = REPO_ROOT / "ESP32_CAM_Project"
CONFIGURE_SCRIPT = ESP32_DIR / "configure_esp32_wifi.py"
RUN_STREAM_SERVER = DADN_DIR / "run_stream_server.py"
RECORD_METRICS = DADN_DIR / "benchmark" / "record_metrics.py"
DEFAULT_RESOLUTIONS = ["QVGA", "VGA", "SVGA", "XGA", "SXGA", "UXGA"]

sys.path.insert(0, str(ESP32_DIR))
import run_esp32_all as esp32_tools  # type: ignore  # noqa: E402
from camera_profiles import frame_size_dimensions, frame_size_label, normalize_frame_size  # type: ignore  # noqa: E402


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def run_command(cmd: list[str], cwd: Path, *, env: dict[str, str] | None = None) -> dict[str, Any]:
    start = time.time()
    completed = subprocess.run(cmd, cwd=cwd, env=env, text=True, capture_output=True)
    return {
        "cmd": cmd,
        "returncode": completed.returncode,
        "duration_seconds": time.time() - start,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def fetch_json(url: str, timeout: float) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.load(response)


def wait_for_json(url: str, timeout: float, deadline_seconds: float) -> dict[str, Any]:
    deadline = time.time() + deadline_seconds
    last_error: str | None = None
    while time.time() < deadline:
        try:
            return fetch_json(url, timeout)
        except Exception as exc:
            last_error = str(exc)
            time.sleep(1.0)
    raise RuntimeError(f"Timed out waiting for {url}: {last_error or 'no response'}")


def wait_for_camera_connected(server_url: str, timeout: float, deadline_seconds: float) -> dict[str, Any]:
    stats_url = server_url.rstrip("/") + "/api/stats"
    deadline = time.time() + deadline_seconds
    last_stats: dict[str, Any] | None = None
    while time.time() < deadline:
        try:
            last_stats = fetch_json(stats_url, timeout)
            if last_stats.get("camera_connected") and float(last_stats.get("current_fps") or 0.0) > 0.0:
                return last_stats
        except Exception:
            pass
        time.sleep(1.0)
    raise RuntimeError(f"Timed out waiting for camera connection at {stats_url}. Last stats: {last_stats}")


def discover_stream_url_from_serial(
    ports: list[str],
    *,
    baud: int,
    timeout_seconds: float,
    stream_ready_timeout: float,
    request_timeout: float,
) -> tuple[Optional[str], dict[str, Any]]:
    info: dict[str, Any] = {"mode": "serial"}
    if not ports:
        info["error"] = "No serial ports provided or detected."
        return None, info

    for port_name in ports:
        stream_url = esp32_tools.read_serial_for_stream_url(
            port_name,
            baud,
            timeout_seconds,
            esp32_tools.DEFAULT_PORTS,
            request_timeout,
            stream_ready_timeout,
        )
        if stream_url:
            info["port"] = port_name
            info["stream_url"] = stream_url
            return stream_url, info

    info["error"] = "Could not discover a reachable stream URL from serial logs."
    return None, info


def validate_known_stream_url(stream_url: str, request_timeout: float) -> tuple[str, dict[str, Any]]:
    normalized = esp32_tools.normalize_stream_url(stream_url)
    if not esp32_tools.validate_esp32_stream_candidate(normalized, request_timeout):
        raise RuntimeError(f"Known ESP32 stream URL did not respond: {normalized}")
    return normalized, {"mode": "explicit", "stream_url": normalized}


def flash_firmware(
    *,
    ssid: str,
    password: str,
    server_ip: str,
    frame_size: str,
    upload_port: str,
    vflip: bool,
    hmirror: bool,
    stream_timeout_ms: int,
    jpeg_quality: int,
    frame_delay_ms: int,
    enable_health_check: bool,
) -> dict[str, Any]:
    cmd = [
        sys.executable,
        str(CONFIGURE_SCRIPT),
        "--ssid",
        ssid,
        "--password",
        password,
        "--server-ip",
        server_ip,
        "--frame-size",
        frame_size,
        "--stream-timeout-ms",
        str(stream_timeout_ms),
        "--jpeg-quality",
        str(jpeg_quality),
        "--frame-delay-ms",
        str(frame_delay_ms),
        "--upload",
        "--upload-port",
        upload_port,
    ]
    if vflip:
        cmd.append("--vflip")
    if hmirror:
        cmd.append("--hmirror")
    if enable_health_check:
        cmd.append("--enable-health-check")
    return run_command(cmd, ESP32_DIR)


def start_dadn_server(camera_url: str, server_port: int, log_path: Path) -> subprocess.Popen[str]:
    command = [
        sys.executable,
        str(RUN_STREAM_SERVER),
        "--camera-url",
        camera_url,
        "--port",
        str(server_port),
        "--no-browser",
    ]
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_file = log_path.open("w", encoding="utf-8")
    env = dict(os.environ)
    env["PYTHONUNBUFFERED"] = "1"
    process = subprocess.Popen(
        command,
        cwd=DADN_DIR,
        env=env,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        text=True,
    )
    setattr(process, "_dadn_log_file", log_file)
    return process


def stop_process(process: subprocess.Popen[Any] | None) -> None:
    if process is None:
        return
    try:
        process.terminate()
        process.wait(timeout=10)
    except Exception:
        try:
            process.kill()
        except Exception:
            pass
    log_file = getattr(process, "_dadn_log_file", None)
    if log_file:
        try:
            log_file.close()
        except Exception:
            pass


def run_runtime_metrics(
    *,
    server_url: str,
    output_dir: Path,
    runs: int,
    warmup: float,
    duration: float,
    interval: float,
    timeout: float,
) -> tuple[dict[str, Any], dict[str, Any]]:
    cmd = [
        sys.executable,
        str(RECORD_METRICS),
        "--skip-offline",
        "--server-url",
        server_url,
        "--runs",
        str(runs),
        "--warmup",
        str(warmup),
        "--duration",
        str(duration),
        "--interval",
        str(interval),
        "--timeout",
        str(timeout),
        "--output-dir",
        str(output_dir),
    ]
    completed = run_command(cmd, DADN_DIR)
    output_dir.mkdir(parents=True, exist_ok=True)
    write_text(output_dir / "record_metrics_stdout.log", completed["stdout"])
    write_text(output_dir / "record_metrics_stderr.log", completed["stderr"])

    summary_candidates = sorted(
        output_dir.rglob("metrics_summary.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    summary: dict[str, Any] = {}
    if summary_candidates:
        summary = load_json(summary_candidates[0])

    return completed, summary


def latest_stream_summary(runtime_dir: Path) -> Path | None:
    candidates = sorted(runtime_dir.rglob("metrics_summary.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    return candidates[0] if candidates else None


def summarize_resolution(
    *,
    resolution: str,
    flash_result: dict[str, Any],
    discovery: dict[str, Any],
    runtime_result: dict[str, Any] | None,
    runtime_summary: dict[str, Any] | None,
    server_url: str | None,
) -> dict[str, Any]:
    runtime = (runtime_summary or {}).get("runtime") or {}
    offline = (runtime_summary or {}).get("offline") or {}
    return {
        "resolution": resolution,
        "resolution_label": frame_size_label(resolution),
        "dimensions": frame_size_dimensions(resolution),
        "flash": {
            "command": flash_result.get("cmd"),
            "returncode": flash_result.get("returncode"),
            "duration_seconds": flash_result.get("duration_seconds"),
        },
        "discovery": discovery,
        "server_url": server_url,
        "runtime": {
            "command": None if runtime_result is None else runtime_result.get("cmd"),
            "returncode": None if runtime_result is None else runtime_result.get("returncode"),
            "duration_seconds": None if runtime_result is None else runtime_result.get("duration_seconds"),
            "status": runtime.get("status"),
            "runs": runtime.get("runs"),
            "warmup_seconds": runtime.get("warmup_seconds"),
            "duration_seconds_reported": runtime.get("duration_seconds"),
            "interval_seconds": runtime.get("interval_seconds"),
            "avg_capture_fps_mean": runtime.get("avg_capture_fps_mean"),
            "avg_capture_fps_std": runtime.get("avg_capture_fps_std"),
            "avg_inference_fps_mean": runtime.get("avg_inference_fps_mean"),
            "avg_inference_fps_std": runtime.get("avg_inference_fps_std"),
            "server_side_alert_latency_ms_mean": runtime.get("server_side_alert_latency_ms_mean"),
            "server_side_alert_latency_ms_p95": runtime.get("server_side_alert_latency_ms_p95"),
            "alert_events": runtime.get("alert_events"),
        },
        "notes": {
            "offline_status": offline.get("status"),
            "latency_note": (runtime_summary or {}).get("runtime", {}).get("latency_note"),
        },
    }


def write_markdown(path: Path, payload: dict[str, Any]) -> None:
    rows = []
    for item in payload["results"]:
        runtime = item.get("runtime") or {}
        rows.append(
            "| {resolution} | {dimensions} | {flash} | {capture} | {inference} | {latency} | {alerts} | {status} |".format(
                resolution=item["resolution"],
                dimensions=item["dimensions"],
                flash="OK" if item["flash"]["returncode"] == 0 else "FAIL",
                capture=f"{runtime.get('avg_capture_fps_mean') if runtime.get('avg_capture_fps_mean') is not None else 'N/A'}",
                inference=f"{runtime.get('avg_inference_fps_mean') if runtime.get('avg_inference_fps_mean') is not None else 'N/A'}",
                latency=f"{runtime.get('server_side_alert_latency_ms_mean') if runtime.get('server_side_alert_latency_ms_mean') is not None else 'N/A'}",
                alerts=f"{runtime.get('alert_events') if runtime.get('alert_events') is not None else 'N/A'}",
                status=runtime.get("status") or "N/A",
            )
        )

    lines = [
        "# ESP32-CAM Resolution Sweep Summary",
        "",
        f"- Generated at: `{payload['generated_at']}`",
        f"- Resolutions: `{', '.join(payload['resolutions'])}`",
        f"- Upload port: `{payload['upload_port']}`",
        f"- Serial port: `{payload['serial_port'] or 'auto-detect / fallback'}`",
        f"- Server URL: `{payload['server_url'] or 'launch per resolution'}`",
        f"- Runtime protocol: `{payload['protocol']['runs']}` runs, `{payload['protocol']['warmup_seconds']}s` warm-up, `{payload['protocol']['duration_seconds']}s` record, `{payload['protocol']['interval_seconds']}s` interval",
        "",
        "## Per-resolution results",
        "",
        "| Resolution | Size | Flash | Avg capture FPS | Avg inference FPS | Server-side alert latency mean | Alert events | Runtime status |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | --- |",
        *rows,
        "",
        "Notes:",
        "- `640x480` in the DADN server is the processing resolution; this sweep changes the ESP32-CAM capture size.",
        "- Flash failures, serial discovery failures, or runtime failures are preserved per resolution in the JSON summary.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Flash and benchmark ESP32-CAM capture resolutions")
    parser.add_argument("--ssid", required=True, help="2.4 GHz WiFi SSID reachable by ESP32-CAM")
    parser.add_argument("--password", required=True, help="WiFi password")
    parser.add_argument("--server-ip", default="192.168.1.100", help="DADN/API server IP used by ESP32 health checks")
    parser.add_argument("--upload-port", required=True, help="ESP32 upload port, e.g. COM13 or /dev/ttyUSB0")
    parser.add_argument("--serial-port", default=None, help="ESP32 serial port for boot log discovery; defaults to upload port")
    parser.add_argument(
        "--resolutions",
        default=",".join(DEFAULT_RESOLUTIONS),
        help="Comma-separated capture resolutions to sweep: QVGA,VGA,SVGA,XGA,SXGA,UXGA or dimensions like 640x480",
    )
    parser.add_argument("--server-url", default=None, help="Reuse an already running DADN server instead of launching per resolution")
    parser.add_argument("--server-port", type=int, default=5000, help="Port for launched DADN server")
    parser.add_argument("--server-start-timeout", type=float, default=45.0, help="Seconds to wait for the launched DADN server to answer /health")
    parser.add_argument("--camera-start-timeout", type=float, default=60.0, help="Seconds to wait for the DADN server to reconnect to the ESP32 stream")
    parser.add_argument("--warmup", type=float, default=10.0, help="Warm-up seconds for runtime metrics")
    parser.add_argument("--duration", type=float, default=45.0, help="Recording duration seconds for runtime metrics")
    parser.add_argument("--interval", type=float, default=1.0, help="Polling interval seconds for runtime metrics")
    parser.add_argument("--runs", type=int, default=1, help="Number of runtime runs per resolution")
    parser.add_argument("--timeout", type=float, default=5.0, help="HTTP timeout seconds for server health/stats")
    parser.add_argument("--stream-timeout-ms", type=int, default=300000, help="ESP32 stream timeout in ms")
    parser.add_argument("--jpeg-quality", type=int, default=24, help="ESP32 JPEG quality for the sweep")
    parser.add_argument("--frame-delay-ms", type=int, default=15, help="Delay between streamed frames on the ESP32")
    parser.add_argument("--post-upload-delay", type=float, default=2.0, help="Seconds to wait after flashing before reading serial")
    parser.add_argument("--serial-baud", type=int, default=115200, help="Serial baud rate for ESP32 logs")
    parser.add_argument("--serial-timeout", type=float, default=25.0, help="Seconds to wait for serial discovery per resolution")
    parser.add_argument("--stream-ready-timeout", type=float, default=20.0, help="Seconds to wait for a discovered stream URL to become reachable")
    parser.add_argument("--camera-url", default=None, help="Explicit ESP32 stream URL when serial discovery is not available")
    parser.add_argument("--esp32-ip", default=None, help="Known ESP32 IP address when the stream URL is stable")
    parser.add_argument("--vflip", action="store_true", help="Flip camera vertically")
    parser.add_argument("--hmirror", action="store_true", help="Mirror camera horizontally")
    parser.add_argument("--enable-health-check", action="store_true", help="Enable ESP32 health checks back to the DADN server")
    parser.add_argument("--output-dir", type=Path, default=DADN_DIR / "experiments" / "results")
    args = parser.parse_args()

    resolutions = [normalize_frame_size(item) for item in args.resolutions.split(",") if item.strip()]
    if not resolutions:
        parser.error("At least one resolution must be provided.")

    serial_port = args.serial_port or args.upload_port
    if args.camera_url and args.serial_port is None and args.esp32_ip is None:
        serial_port = None

    run_dir = args.output_dir / datetime.now().strftime("%Y%m%d-%H%M%S-esp32-resolution-sweep")
    run_dir.mkdir(parents=True, exist_ok=True)

    payload: dict[str, Any] = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "resolutions": resolutions,
        "upload_port": args.upload_port,
        "serial_port": serial_port,
        "server_url": args.server_url,
        "protocol": {
            "runs": args.runs,
            "warmup_seconds": args.warmup,
            "duration_seconds": args.duration,
            "interval_seconds": args.interval,
            "timeout_seconds": args.timeout,
        },
        "results": [],
    }

    launched_server: subprocess.Popen[str] | None = None
    try:
        for index, resolution in enumerate(resolutions, start=1):
            resolution_dir = run_dir / f"{index:02d}_{resolution.lower()}"
            resolution_dir.mkdir(parents=True, exist_ok=True)
            print(f"[INFO] === Resolution {index}/{len(resolutions)}: {frame_size_label(resolution)} ===")

            flash_result = flash_firmware(
                ssid=args.ssid,
                password=args.password,
                server_ip=args.server_ip,
                frame_size=resolution,
                upload_port=args.upload_port,
                vflip=args.vflip,
                hmirror=args.hmirror,
                stream_timeout_ms=args.stream_timeout_ms,
                jpeg_quality=args.jpeg_quality,
                frame_delay_ms=args.frame_delay_ms,
                enable_health_check=args.enable_health_check,
            )
            write_text(resolution_dir / "flash_stdout.log", flash_result["stdout"])
            write_text(resolution_dir / "flash_stderr.log", flash_result["stderr"])

            discovery: dict[str, Any] = {"mode": "unknown"}
            stream_url: str | None = None
            if flash_result["returncode"] == 0:
                time.sleep(args.post_upload_delay)
                if args.camera_url:
                    stream_url, discovery = validate_known_stream_url(args.camera_url, args.timeout)
                elif args.esp32_ip:
                    candidates = esp32_tools.stream_urls_for_ip(args.esp32_ip, esp32_tools.DEFAULT_PORTS)
                    for candidate in candidates:
                        if esp32_tools.validate_esp32_stream_candidate(candidate, args.timeout):
                            stream_url = candidate
                            discovery = {"mode": "ip", "stream_url": stream_url, "esp32_ip": args.esp32_ip}
                            break
                    if not stream_url:
                        discovery = {"mode": "ip", "esp32_ip": args.esp32_ip, "error": "No reachable stream candidate"}
                else:
                    ports = [serial_port] if serial_port else esp32_tools.serial_ports_from_pyserial()
                    stream_url, discovery = discover_stream_url_from_serial(
                        ports,
                        baud=args.serial_baud,
                        timeout_seconds=args.serial_timeout,
                        stream_ready_timeout=args.stream_ready_timeout,
                        request_timeout=args.timeout,
                    )
            else:
                discovery = {"mode": "flash_failed"}

            if not stream_url:
                result = summarize_resolution(
                    resolution=resolution,
                    flash_result=flash_result,
                    discovery=discovery,
                    runtime_result=None,
                    runtime_summary=None,
                    server_url=args.server_url,
                )
                result["status"] = "failed"
                result["error"] = discovery.get("error") or "Could not discover stream URL"
                payload["results"].append(result)
                write_json(resolution_dir / "resolution_summary.json", result)
                continue

            server_url = args.server_url
            if server_url is None:
                server_port = args.server_port
                launched_server = start_dadn_server(stream_url, server_port, resolution_dir / "server.log")
                server_url = f"http://127.0.0.1:{server_port}"
                wait_for_json(server_url.rstrip("/") + "/health", args.timeout, args.server_start_timeout)
                wait_for_camera_connected(server_url, args.timeout, args.camera_start_timeout)
            else:
                wait_for_json(server_url.rstrip("/") + "/health", args.timeout, args.server_start_timeout)
                wait_for_camera_connected(server_url, args.timeout, args.camera_start_timeout)

            runtime_output_dir = resolution_dir / "runtime"
            runtime_result, runtime_summary = run_runtime_metrics(
                server_url=server_url,
                output_dir=runtime_output_dir,
                runs=args.runs,
                warmup=args.warmup,
                duration=args.duration,
                interval=args.interval,
                timeout=args.timeout,
            )

            result = summarize_resolution(
                resolution=resolution,
                flash_result=flash_result,
                discovery=discovery,
                runtime_result=runtime_result,
                runtime_summary=runtime_summary,
                server_url=server_url,
            )
            result["status"] = "ok" if flash_result["returncode"] == 0 and runtime_result["returncode"] == 0 else "partial"
            result["stream_url"] = stream_url
            latest_summary_path = latest_stream_summary(runtime_output_dir)
            result["runtime_summary_path"] = str(latest_summary_path) if latest_summary_path else None
            payload["results"].append(result)
            write_json(resolution_dir / "resolution_summary.json", result)

            if launched_server is not None:
                stop_process(launched_server)
                launched_server = None

        payload["finished_at"] = datetime.now().isoformat(timespec="seconds")
        write_json(run_dir / "resolution_sweep_summary.json", payload)
        write_markdown(run_dir / "resolution_sweep_summary.md", payload)
        print(f"[OK] Wrote JSON summary: {run_dir / 'resolution_sweep_summary.json'}")
        print(f"[OK] Wrote Markdown summary: {run_dir / 'resolution_sweep_summary.md'}")
        return 0
    finally:
        stop_process(launched_server)


if __name__ == "__main__":
    raise SystemExit(main())
