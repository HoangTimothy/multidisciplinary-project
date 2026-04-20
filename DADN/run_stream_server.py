#!/usr/bin/env python3
"""
Quick Start Script for ESP32-CAM Streaming + DADN Detection
Run this to start the server with automatic configuration
"""

import os
import sys
import argparse
from pathlib import Path

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
        "--esp32-url",
        type=str,
        default=None,
        help="ESP32-CAM MJPEG stream URL (e.g., http://192.168.1.50:8081/stream)"
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
        print("   Run: pip install -r requirements_api.txt")
        sys.exit(1)

    # Get ESP32-CAM URL
    esp32_url = args.esp32_url
    if not esp32_url:
        print("⚙️  ESP32-CAM Configuration")
        print("   Enter your ESP32-CAM stream URL")
        print("   Example: http://192.168.1.50:8081/stream")
        print("   Or press Enter to use default test URL")
        esp32_url = input("   URL: ").strip()
        if not esp32_url:
            local_ip = get_local_ip()
            esp32_url = f"http://192.168.1.50:8081/stream"
            print(f"   ℹ️  Using default: {esp32_url}")

    print(f"\n📡 Configuration:")
    print(f"   Server: http://0.0.0.0:{args.port}")
    print(f"   ESP32-CAM Stream: {esp32_url}")
    print(f"   Local IP: http://{get_local_ip()}:{args.port}")
    print()

    # Import and run server
    print("🔄 Initializing models...")
    try:
        from stream_server import app, init_models, capture_stream
        import threading
        
        init_models()
        print("✅ Models loaded successfully\n")
        
        # Configure app
        app.config["ESP32_STREAM_URL"] = esp32_url
        
        # Start capture thread
        capture_thread = threading.Thread(target=capture_stream, daemon=True)
        capture_thread.start()
        print("✅ Capture thread started\n")
        
        # Print access info
        print("="*60)
        print("🎉 Server is running!")
        print("="*60)
        print(f"\n📱 Access web interface:")
        print(f"   http://localhost:{args.port}")
        print(f"   http://{get_local_ip()}:{args.port}")
        print(f"\n📊 API endpoints:")
        print(f"   Health: http://localhost:{args.port}/health")
        print(f"   Stats: http://localhost:{args.port}/api/stats")
        print(f"   Config: http://localhost:{args.port}/api/config")
        print(f"\n📹 ESP32-CAM Stream:")
        print(f"   {esp32_url}")
        print(f"\n💡 Tips:")
        print(f"   - Open the web URL in your browser")
        print(f"   - Position objects in front of camera")
        print(f"   - Look for red boxes around detected obstacles")
        print(f"   - Press Ctrl+C to stop server")
        print("\n" + "="*60 + "\n")
        
        # Open browser if not disabled
        if not args.no_browser:
            try:
                import webbrowser
                print("🌐 Opening browser...\n")
                webbrowser.open(f"http://localhost:{args.port}")
            except:
                pass
        
        # Run Flask app
        app.run(
            host="0.0.0.0",
            port=args.port,
            debug=args.debug,
            threaded=True,
            use_reloader=False
        )
        
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
