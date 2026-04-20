"""
Video Streaming + Object Detection Server for ESP32-CAM
Optimized for low-power ESP32-CAM hardware

Features:
- MJPEG streaming on 0.0.0.0:5001
- Real-time object detection with overlay
- Web interface to view stream
- REST API for detection results
"""

import io
import threading
import time
from collections import deque
from typing import Optional

import cv2
import numpy as np
from flask import Flask, render_template, Response, jsonify
from PIL import Image, ImageDraw, ImageFont

from config import FRAME_HEIGHT, FRAME_WIDTH, SCORE_THRESHOLD, MAX_RESULTS
from decision_engine import DecisionEngine
from detector import ObstacleDetector
from model_utils import ensure_model

app = Flask(__name__)

# ==================== CONFIGURATION ====================
# ESP32-CAM Configuration
ESP32_CAM_RESOLUTION = (640, 480)  # 640x480 for balance between speed and accuracy
ESP32_STREAM_PORT = 8081           # ESP32-CAM MJPEG server port
ESP32_STREAM_URL = "http://192.168.1.100:8081/stream"  # Will be configured

# Server Configuration
SERVER_HOST = "0.0.0.0"
SERVER_PORT = 5001
WEB_PORT = 5000

# Performance Configuration for ESP32-CAM
INFERENCE_EVERY_N_FRAMES = 3       # Skip frames for faster processing
JPEG_QUALITY = 70                  # Lower = faster, smaller
MAX_QUEUE_SIZE = 30
INFERENCE_TIMEOUT = 10             # seconds

# ==================== GLOBAL STATE ====================
frame_buffer = deque(maxlen=1)
lock = threading.Lock()

detector: Optional[ObstacleDetector] = None
decision_engine: Optional[DecisionEngine] = None

frame_count = 0
inference_count = 0
fps_counter = 0.0
last_inference_time = time.time()
last_detection_result = None
inference_stats = {
    "total_frames": 0,
    "total_inferences": 0,
    "avg_inference_time_ms": 0.0,
    "current_fps": 0.0,
    "last_alert": None,
}


# ==================== INITIALIZATION ====================
def init_models():
    """Initialize detection models"""
    global detector, decision_engine
    print("[INFO] Loading EfficientDet-Lite0 model...")
    ensure_model()
    detector = ObstacleDetector()
    decision_engine = DecisionEngine(FRAME_WIDTH, FRAME_HEIGHT)
    print("[INFO] Models loaded successfully")


# ==================== FRAME CAPTURE & PROCESSING ====================
def capture_stream():
    """
    Capture frames from ESP32-CAM MJPEG stream and process for detection
    Runs in background thread
    """
    global frame_count, inference_count, fps_counter, last_inference_time, last_detection_result
    global inference_stats

    import urllib.request

    stream_url = app.config.get("ESP32_STREAM_URL", ESP32_STREAM_URL)
    frame_times = deque(maxlen=30)

    while True:
        try:
            print(f"[INFO] Connecting to ESP32-CAM stream at {stream_url}")
            stream = urllib.request.urlopen(stream_url, timeout=INFERENCE_TIMEOUT)
            buffer = b""

            while True:
                chunk = stream.read(32768)
                if not chunk:
                    raise RuntimeError("Stream ended")

                buffer += chunk

                # Extract JPEG frames by SOI/EOI markers. Works across different MJPEG boundaries.
                while True:
                    start_idx = buffer.find(b"\xff\xd8")
                    end_idx = buffer.find(b"\xff\xd9", start_idx + 2)

                    if start_idx == -1 or end_idx == -1:
                        # Keep a bounded buffer to avoid unbounded growth.
                        if len(buffer) > 2_000_000:
                            buffer = buffer[-500_000:]
                        break

                    jpeg_data = buffer[start_idx : end_idx + 2]
                    buffer = buffer[end_idx + 2 :]

                    nparr = np.frombuffer(jpeg_data, np.uint8)
                    frame_bgr = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                    if frame_bgr is None:
                        continue

                    frame_count += 1
                    frame_times.append(time.time())
                    inference_stats["total_frames"] = frame_count

                    if frame_count % INFERENCE_EVERY_N_FRAMES == 0:
                        try:
                            inf_start = time.time()
                            detections = detector.detect(frame_bgr)
                            alert = decision_engine.choose_alert(detections)
                            inf_time = (time.time() - inf_start) * 1000

                            inference_count += 1
                            inference_stats["total_inferences"] = inference_count
                            inference_stats["avg_inference_time_ms"] = inf_time

                            if alert:
                                inference_stats["last_alert"] = {
                                    "label": alert.label_vi,
                                    "distance": alert.distance_level,
                                    "zone": alert.horizontal_zone,
                                    "priority": float(alert.priority),
                                    "timestamp": time.time(),
                                }
                                print(f"[ALERT] {alert.label_vi} ({alert.distance_level})")

                            last_detection_result = (frame_bgr, alert, detections)
                        except Exception as e:
                            print(f"[ERROR] Inference failed: {e}")

                    with lock:
                        frame_buffer.clear()
                        frame_buffer.append(
                            {
                                "frame": frame_bgr,
                                "alert": last_detection_result[1] if last_detection_result else None,
                                "detections": last_detection_result[2] if last_detection_result else [],
                            }
                        )

                    if len(frame_times) > 1:
                        fps = len(frame_times) / max(frame_times[-1] - frame_times[0], 1e-6)
                        inference_stats["current_fps"] = fps

        except Exception as e:
            print(f"[ERROR] Stream connection failed: {e}")
            print(f"[INFO] Retry after 2s. Check ESP32 URL: {stream_url}")
            time.sleep(2)


def put_text_utf8(frame, text: str, xy, fontsize=20, color=(0, 255, 0)):
    """Draw UTF-8 text on frame"""
    pil_image = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(pil_image)
    try:
        font = ImageFont.truetype("arial.ttf", fontsize)
    except:
        font = ImageFont.load_default()
    draw.text(xy, text, font=font, fill=color)
    return cv2.cvtColor(np.array(pil_image), cv2.COLOR_RGB2BGR)


def draw_detections(frame, alert, detections, fps):
    """Draw detection boxes and alert on frame"""
    # FPS counter
    frame = put_text_utf8(frame, f"FPS: {fps:.1f}", (10, 30), fontsize=16, color=(0, 255, 255))
    
    # Draw all detections
    for det in detections:
        cv2.rectangle(frame, (det.x, det.y), (det.x + det.w, det.y + det.h), (100, 100, 255), 1)
        label = f"{det.label} {det.score:.2f}"
        frame = put_text_utf8(frame, label, (det.x, det.y - 5), fontsize=12, color=(100, 100, 255))
    
    # Highlight primary alert
    if alert:
        cv2.rectangle(
            frame,
            (alert.x, alert.y),
            (alert.x + alert.w, alert.y + alert.h),
            (0, 0, 255),
            3,
        )
        text = f"⚠ {alert.label_vi} | {alert.distance_level} | {alert.horizontal_zone}"
        frame = put_text_utf8(frame, text, (alert.x, max(50, alert.y - 15)), fontsize=14, color=(0, 0, 255))
        frame = put_text_utf8(frame, alert.spoken_text, (10, FRAME_HEIGHT - 20), fontsize=14, color=(0, 255, 0))
    
    return frame


# ==================== WEB ROUTES ====================
@app.route("/")
def index():
    """Serve web interface"""
    return render_template("stream.html", 
                         esp32_stream_url=app.config.get("ESP32_STREAM_URL", ESP32_STREAM_URL),
                         web_port=WEB_PORT)


@app.route("/video_feed")
def video_feed():
    """Stream processed video with detections"""
    def generate():
        while True:
            with lock:
                if frame_buffer:
                    data = frame_buffer[0]
                    frame = data["frame"]
                    alert = data["alert"]
                    detections = data["detections"]
                else:
                    continue
            
            try:
                # Draw detections
                frame_with_overlay = draw_detections(
                    frame.copy(),
                    alert,
                    detections,
                    inference_stats["current_fps"]
                )
                
                # Encode to JPEG
                _, jpeg = cv2.imencode(".jpg", frame_with_overlay, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
                
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n'
                       b'Content-Length: ' + str(len(jpeg)).encode() + b'\r\n\r\n'
                       + jpeg.tobytes() + b'\r\n')
                
                time.sleep(0.01)
                
            except Exception as e:
                print(f"[ERROR] Video feed error: {e}")
                continue
    
    return Response(generate(), mimetype="multipart/x-mixed-replace; boundary=frame")


@app.route("/health")
def health():
    """Health check endpoint"""
    return jsonify({
        "status": "ok",
        "fps": round(inference_stats["current_fps"], 1),
        "frames": inference_stats["total_frames"],
        "inferences": inference_stats["total_inferences"],
    }), 200


@app.route("/api/stats")
def api_stats():
    """Get inference statistics"""
    return jsonify({
        "frame_count": frame_count,
        "inference_count": inference_count,
        "current_fps": round(inference_stats["current_fps"], 1),
        "avg_inference_time_ms": round(inference_stats["avg_inference_time_ms"], 1),
        "last_alert": inference_stats["last_alert"],
        "config": {
            "frame_size": ESP32_CAM_RESOLUTION,
            "inference_every_n_frames": INFERENCE_EVERY_N_FRAMES,
            "jpeg_quality": JPEG_QUALITY,
            "score_threshold": SCORE_THRESHOLD,
            "max_results": MAX_RESULTS,
        }
    }), 200


@app.route("/api/config", methods=["GET"])
def get_config():
    """Get current configuration"""
    return jsonify({
        "esp32_stream_url": app.config.get("ESP32_STREAM_URL", ESP32_STREAM_URL),
        "inference_every_n_frames": INFERENCE_EVERY_N_FRAMES,
        "jpeg_quality": JPEG_QUALITY,
        "frame_resolution": ESP32_CAM_RESOLUTION,
        "score_threshold": SCORE_THRESHOLD,
        "max_results": MAX_RESULTS,
    }), 200


# ==================== MAIN ====================
if __name__ == "__main__":
    import sys
    
    # Get ESP32 stream URL from command line or config
    if len(sys.argv) > 1:
        esp32_url = sys.argv[1]
        app.config["ESP32_STREAM_URL"] = esp32_url
        print(f"[INFO] Using ESP32 stream URL: {esp32_url}")
    
    # Initialize models
    init_models()
    
    # Start background thread for frame capture
    capture_thread = threading.Thread(target=capture_stream, daemon=True)
    capture_thread.start()
    print(f"[INFO] Capture thread started")
    
    # Start Flask server
    print(f"[INFO] Starting web server on http://{SERVER_HOST}:{WEB_PORT}")
    print(f"[INFO] Video feed available at http://localhost:{WEB_PORT}/video_feed")
    
    try:
        app.run(host=SERVER_HOST, port=WEB_PORT, debug=False, threaded=True)
    except KeyboardInterrupt:
        print("\n[INFO] Shutting down...")
