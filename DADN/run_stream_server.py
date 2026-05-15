#!/usr/bin/env python3
"""
Quick Start Script for ESP32-CAM Streaming + DADN Detection
Run this to start the server with automatic configuration
"""

import os
import sys
import argparse
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse


DEFAULT_CAMERA_URL_FILE = Path(__file__).resolve().parent / ".camera-ngrok-url"


def normalize_stream_url(url: str) -> str:
    """Accept either a base camera URL or the full MJPEG /stream URL."""
    value = url.strip()
    if not value:
        raise ValueError("Camera stream URL is empty")

    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"}:
        host = value.split("/", 1)[0].split(":", 1)[0]
        scheme = "http" if host in {"localhost", "127.0.0.1"} or host.replace(".", "").isdigit() else "https"
        value = f"{scheme}://{value}"

    return value.rstrip("/") if value.rstrip("/").endswith("/stream") else value.rstrip("/") + "/stream"


def read_url_file(path: Path) -> Optional[str]:
    if not path.exists():
        return None

    for line in path.read_text(encoding="utf-8").splitlines():
        value = line.strip()
        if value and not value.startswith("#"):
            return value
    return None

def get_local_ip():
    """Get local IP address"""
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "127.0.0.1"

def print_banner():
    """Print startup banner"""
    print("\n" + "="*60)
    print("  🎥 ESP32-CAM Streaming + Object Detection Server")
    print("     Powered by EfficientDet-Lite0 + MediaPipe")
    print("="*60 + "\n")

def main():
    parser = argparse.ArgumentParser(
        description="Start ESP32-CAM streaming and detection server"
    )
    parser.add_argument(
        "--camera-url",
        type=str,
        default=None,
        help="Camera MJPEG stream URL or ngrok base URL (e.g., https://xxxx.ngrok-free.app)"
    )
    parser.add_argument(
        "--esp32-url",
        type=str,
        dest="camera_url",
        help="Alias for --camera-url"
    )
    parser.add_argument(
        "--esp32-url-file",
        type=Path,
        default=DEFAULT_CAMERA_URL_FILE,
        help=f"File containing camera/ngrok URL (default: {DEFAULT_CAMERA_URL_FILE})"
    )
    parser.add_argument(
        "--camera-url-file",
        type=Path,
        default=None,
        help="Alias for --esp32-url-file"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=5000,
        help="Server port (default: 5000)"
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Don't open browser automatically"
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug mode"
    )

    args = parser.parse_args()

    print_banner()

    # Check dependencies
    print("📦 Checking dependencies...")
    try:
        import cv2
        import flask
        import mediapipe
        import numpy
        print("   ✅ All dependencies found\n")
    except ImportError as e:
        print(f"   ❌ Missing package: {e}")
        print("   Run: pip install -r requirements.txt")
        sys.exit(1)

    # Get camera stream URL. ESP32_* names are kept for compatibility.
    url_file = args.camera_url_file or args.esp32_url_file
    camera_url = (
        args.camera_url
        or os.getenv("CAMERA_STREAM_URL")
        or os.getenv("CAMERA_NGROK_URL")
    )
    if not camera_url:
        camera_url = read_url_file(url_file)

    if not camera_url:
        print("⚙️  Camera Configuration")
        camera_url = input("   Enter camera URL (default: http://192.168.1.50:8081/stream): ").strip()
        if not camera_url:
            camera_url = "http://192.168.1.50:8081/stream"

    try:
        camera_url = normalize_stream_url(camera_url)
    except ValueError as e:
        print(f"   ❌ Invalid camera URL: {e}")
        sys.exit(1)

    local_ip = get_local_ip()
    print(f"\n📡 Configuration:")
    print(f"   Server: http://0.0.0.0:{args.port}")
    print(f"   Camera Stream: {camera_url}")
    print(f"   Local IP: http://{local_ip}:{args.port}")
    print()

    # Import and run server
    print("🔄 Initializing models...")
    try:
        from server.stream_server import app, init_models, capture_stream, inference_worker
        import threading
        
        init_models()
        print("✅ Models loaded successfully\n")
        
        # Configure app
        app.config["ESP32_STREAM_URL"] = camera_url
        
        # Start capture thread
        capture_thread = threading.Thread(target=capture_stream, daemon=True)
        capture_thread.start()
        print("✅ Capture thread started\n")

        inference_thread = threading.Thread(target=inference_worker, daemon=True)
        inference_thread.start()
        print("✅ Inference thread started\n")
        
        # Print access info
        print("="*60)
        print("🎉 Server is running!")
        print("="*60)
        print(f"\n📱 Access web interface:")
        print(f"   http://localhost:{args.port}")
        print(f"   http://{get_local_ip()}:{args.port}")
        print(f"\n📹 Camera Stream: {camera_url}")
        print(f"💡 Press Ctrl+C to stop server")
        print("\n" + "="*60 + "\n")
        
        # Open browser if not disabled
        if not args.no_browser:
            try:
                import webbrowser
                print("🌐 Opening browser...\n")
                webbrowser.open(f"http://localhost:{args.port}")
            except:
                pass
        
        if args.debug:
            app.run(
                host="0.0.0.0",
                port=args.port,
                debug=True,
                threaded=True,
                use_reloader=False,
            )
        else:
            from waitress import serve

            print(f"🚀 Starting production server on 0.0.0.0:{args.port}")
            serve(app, host="0.0.0.0", port=args.port, threads=8)
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n👋 Shutting down gracefully...")
        sys.exit(0)
