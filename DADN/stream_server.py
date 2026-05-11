"""
Video Streaming + Object Detection Server for ESP32-CAM or camera bridges.

The capture path is intentionally decoupled from model inference:
- capture_stream reads and decodes MJPEG frames as fast as the camera provides them
- video_feed streams the latest frame immediately with the latest known overlay
- inference_worker runs EfficientDet on a small latest-frame queue so slow inference
  cannot stall the live video
"""

from __future__ import annotations

import hashlib
import os
import queue
import statistics
import tempfile
import threading
import time
from collections import deque
from typing import Optional

import cv2
import numpy as np
from flask import Flask, Response, jsonify, render_template, request, send_file
from PIL import Image, ImageDraw, ImageFont

from config import (
    ALERT_PRIORITY_THRESHOLD,
    FRAME_HEIGHT,
    FRAME_WIDTH,
    INFERENCE_PREPROCESSING_ENABLED,
    MAX_RESULTS,
    PREPROCESS_DENOISE_ENABLED,
    PREPROCESS_LOW_LIGHT_ENABLED,
    SCORE_THRESHOLD,
    TEMPORAL_ALERT_HOLD_FRAMES,
    TEMPORAL_ALERT_HOLD_SECONDS,
    TEMPORAL_ALERT_SMOOTHING_ENABLED,
)
from decision_engine import DecisionEngine
from detector import ObstacleDetector
from frame_preprocessing import preprocess_for_inference
from model_utils import ensure_model
from risk_smoothing import AlertSmoother

app = Flask(__name__)

# ==================== CONFIGURATION ====================
# Camera configuration
ESP32_CAM_RESOLUTION = (FRAME_WIDTH, FRAME_HEIGHT)
ESP32_STREAM_PORT = 8081
ESP32_STREAM_URL = "http://192.168.1.100:8081/stream"

# Server configuration
SERVER_HOST = "0.0.0.0"
WEB_PORT = 5000

# Performance configuration
INFERENCE_EVERY_N_FRAMES = int(os.getenv("DADN_INFER_EVERY_N_FRAMES", "5"))
JPEG_QUALITY = int(os.getenv("DADN_JPEG_QUALITY", "60"))
INFERENCE_TIMEOUT = 10
INFERENCE_QUEUE_SIZE = int(os.getenv("DADN_INFERENCE_QUEUE_SIZE", "1"))
TTS_CACHE_DIR = os.path.join(tempfile.gettempdir(), "dadn_tts_cache")
os.makedirs(TTS_CACHE_DIR, exist_ok=True)

# ==================== GLOBAL STATE ====================
frame_buffer = deque(maxlen=1)
frame_cond = threading.Condition()
lock = threading.Lock()
inference_queue: "queue.Queue[tuple[int, float, np.ndarray]]" = queue.Queue(maxsize=INFERENCE_QUEUE_SIZE)

detector: Optional[ObstacleDetector] = None
decision_engine: Optional[DecisionEngine] = None
alert_smoother = AlertSmoother(
    hold_frames=TEMPORAL_ALERT_HOLD_FRAMES,
    hold_seconds=TEMPORAL_ALERT_HOLD_SECONDS,
)

frame_count = 0
inference_count = 0
inference_frame_count = 0
queue_drop_count = 0
last_detection_result = None
inference_times_ms = deque(maxlen=120)
inference_complete_times = deque(maxlen=30)
inference_stats = {
    "total_frames": 0,
    "total_inferences": 0,
    "avg_inference_time_ms": 0.0,
    "p95_inference_time_ms": 0.0,
    "current_fps": 0.0,
    "inference_fps": 0.0,
    "queue_drops": 0,
    "last_alert_latency_ms": None,
    "last_alert": None,
    "camera_connected": False,
}


# ==================== INITIALIZATION ====================
def init_models():
    """Initialize detection models."""
    global detector, decision_engine
    print("[INFO] Loading EfficientDet-Lite0 model...")
    ensure_model()
    detector = ObstacleDetector()
    decision_engine = DecisionEngine(FRAME_WIDTH, FRAME_HEIGHT)
    print("[INFO] Models loaded successfully")


# ==================== FRAME CAPTURE & PROCESSING ====================
def enqueue_latest_for_inference(seq: int, frame_bgr: np.ndarray) -> None:
    """Keep only the newest frame for inference to prevent latency buildup."""
    global queue_drop_count
    try:
        while True:
            inference_queue.get_nowait()
            queue_drop_count += 1
    except queue.Empty:
        pass

    try:
        inference_queue.put_nowait((seq, time.perf_counter(), frame_bgr.copy()))
    except queue.Full:
        queue_drop_count += 1
    inference_stats["queue_drops"] = queue_drop_count


def capture_stream():
    """
    Capture frames from the camera MJPEG stream.

    This function never waits for the detector. It updates the video buffer and
    wakes connected clients on every decoded frame, then drops old inference work
    in favor of the latest frame.
    """
    global frame_count, inference_stats

    import urllib.request

    stream_url = app.config.get("ESP32_STREAM_URL", ESP32_STREAM_URL)
    frame_times = deque(maxlen=30)

    while True:
        stream = None
        try:
            print(f"[INFO] Connecting to camera stream at {stream_url}")
            request = urllib.request.Request(
                stream_url,
                headers={
                    "User-Agent": "dadn-stream-server",
                    "ngrok-skip-browser-warning": "true",
                },
            )
            stream = urllib.request.urlopen(request, timeout=INFERENCE_TIMEOUT)
            inference_stats["camera_connected"] = True
            buffer = b""

            while True:
                chunk = stream.read(32768)
                if not chunk:
                    raise RuntimeError("Stream ended")

                buffer += chunk

                while True:
                    start_idx = buffer.find(b"\xff\xd8")
                    end_idx = buffer.find(b"\xff\xd9", start_idx + 2)

                    if start_idx == -1 or end_idx == -1:
                        if len(buffer) > 2_000_000:
                            buffer = buffer[-500_000:]
                        break

                    jpeg_data = buffer[start_idx : end_idx + 2]
                    buffer = buffer[end_idx + 2 :]

                    frame_bgr = cv2.imdecode(np.frombuffer(jpeg_data, np.uint8), cv2.IMREAD_COLOR)
                    if frame_bgr is None:
                        continue
                    if frame_bgr.shape[1] != FRAME_WIDTH or frame_bgr.shape[0] != FRAME_HEIGHT:
                        frame_bgr = cv2.resize(frame_bgr, (FRAME_WIDTH, FRAME_HEIGHT))

                    frame_count += 1
                    frame_times.append(time.time())

                    alert = last_detection_result[1] if last_detection_result else None
                    detections = last_detection_result[2] if last_detection_result else []

                    with lock:
                        frame_buffer.clear()
                        frame_buffer.append(
                            {
                                "seq": frame_count,
                                "frame": frame_bgr,
                                "alert": alert,
                                "detections": detections,
                            }
                        )

                    with frame_cond:
                        frame_cond.notify_all()

                    if frame_count % INFERENCE_EVERY_N_FRAMES == 0:
                        enqueue_latest_for_inference(frame_count, frame_bgr)

                    if len(frame_times) > 1:
                        fps = len(frame_times) / max(frame_times[-1] - frame_times[0], 1e-6)
                        inference_stats["current_fps"] = fps
                    inference_stats["total_frames"] = frame_count

        except Exception as e:
            inference_stats["camera_connected"] = False
            print(f"[ERROR] Stream connection failed: {e}")
            print(f"[INFO] Retry after 2s. Check camera URL: {stream_url}")
            try:
                if stream is not None:
                    stream.close()
            except Exception:
                pass
            time.sleep(2)


def inference_worker():
    """Run object detection in the background without blocking capture/video."""
    global inference_count, inference_frame_count, last_detection_result, inference_stats

    while True:
        seq, queued_at, frame_bgr = inference_queue.get()
        inference_frame_count += 1

        try:
            if detector is None or decision_engine is None:
                continue

            inf_start = time.time()
            inference_frame = frame_bgr
            if INFERENCE_PREPROCESSING_ENABLED:
                inference_frame = preprocess_for_inference(
                    frame_bgr,
                    denoise_enabled=PREPROCESS_DENOISE_ENABLED,
                    low_light_enabled=PREPROCESS_LOW_LIGHT_ENABLED,
                )
            detections = detector.detect(inference_frame)
            raw_alert = decision_engine.choose_alert(detections)
            alert = (
                alert_smoother.update(
                    raw_alert,
                    frame_index=seq,
                    now_seconds=time.time(),
                )
                if TEMPORAL_ALERT_SMOOTHING_ENABLED
                else raw_alert
            )
            inf_time = (time.time() - inf_start) * 1000
            completed_at = time.perf_counter()
            alert_latency_ms = (completed_at - queued_at) * 1000

            inference_count += 1
            inference_times_ms.append(inf_time)
            inference_complete_times.append(time.time())
            inference_stats["total_inferences"] = inference_count
            inference_stats["avg_inference_time_ms"] = statistics.fmean(inference_times_ms)
            if len(inference_times_ms) >= 2:
                inference_stats["p95_inference_time_ms"] = statistics.quantiles(
                    inference_times_ms, n=20, method="inclusive"
                )[18]
            else:
                inference_stats["p95_inference_time_ms"] = inf_time
            if len(inference_complete_times) > 1:
                span = max(inference_complete_times[-1] - inference_complete_times[0], 1e-6)
                inference_stats["inference_fps"] = len(inference_complete_times) / span
            inference_stats["last_alert_latency_ms"] = alert_latency_ms

            if alert:
                inference_stats["last_alert"] = {
                    "label": alert.label_vi,
                    "raw_label": alert.raw_label_vi,
                    "distance": alert.distance_level,
                    "zone": alert.horizontal_zone,
                    "priority": float(alert.priority),
                    "semantic_priority": float(alert.semantic_priority),
                    "collision_risk_priority": float(alert.collision_risk_priority),
                    "alert_kind": alert.alert_kind,
                    "is_smoothed": raw_alert is None,
                    "spoken_text": alert.spoken_text,
                    "latency_ms": alert_latency_ms,
                    "timestamp": time.time(),
                }
                print(f"[ALERT] {alert.label_vi} ({alert.distance_level})")
            else:
                inference_stats["last_alert"] = None

            last_detection_result = (frame_bgr, alert, detections)

            with lock:
                if frame_buffer:
                    frame_buffer[0]["alert"] = alert
                    frame_buffer[0]["detections"] = detections
                    frame_buffer[0]["inference_seq"] = seq

        except Exception as e:
            print(f"[ERROR] Inference failed: {e}")


def put_text_utf8(frame, text: str, xy, fontsize=20, color=(0, 255, 0)):
    """Draw UTF-8 text on a BGR frame."""
    pil_image = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(pil_image)
    for font_path in (
        "arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
    ):
        try:
            font = ImageFont.truetype(font_path, fontsize)
            break
        except Exception:
            font = None
    if font is None:
        font = ImageFont.load_default()
    draw.text(xy, text, font=font, fill=color)
    return cv2.cvtColor(np.array(pil_image), cv2.COLOR_RGB2BGR)


def draw_detections(frame, alert, detections, fps):
    """Draw detection boxes and alert on frame."""
    frame = put_text_utf8(frame, f"FPS: {fps:.1f}", (10, 30), fontsize=16, color=(0, 255, 255))

    for det in detections:
        cv2.rectangle(frame, (det.x, det.y), (det.x + det.w, det.y + det.h), (100, 100, 255), 1)
        label = f"{det.label} {det.score:.2f}"
        frame = put_text_utf8(frame, label, (det.x, max(12, det.y - 5)), fontsize=12, color=(100, 100, 255))

    if alert:
        cv2.rectangle(
            frame,
            (alert.x, alert.y),
            (alert.x + alert.w, alert.y + alert.h),
            (0, 0, 255),
            3,
        )
        text = f"! {alert.label_vi} | {alert.distance_level} | {alert.horizontal_zone}"
        frame = put_text_utf8(frame, text, (alert.x, max(50, alert.y - 15)), fontsize=14, color=(0, 0, 255))
        frame = put_text_utf8(frame, alert.spoken_text, (10, FRAME_HEIGHT - 22), fontsize=14, color=(0, 255, 0))

    return frame


# ==================== WEB ROUTES ====================
@app.route("/")
def index():
    """Serve web interface."""
    return render_template(
        "stream.html",
        esp32_stream_url=app.config.get("ESP32_STREAM_URL", ESP32_STREAM_URL),
        web_port=WEB_PORT,
    )


@app.route("/video_feed")
def video_feed():
    """Stream processed video with detections."""

    def generate():
        last_seq = 0
        while True:
            with frame_cond:
                frame_cond.wait(timeout=1.0)

            with lock:
                if not frame_buffer:
                    continue
                data = frame_buffer[0]
                seq = data["seq"]
                if seq == last_seq:
                    continue
                last_seq = seq
                frame = data["frame"].copy()
                alert = data["alert"]
                detections = list(data["detections"])

            try:
                frame_with_overlay = draw_detections(frame, alert, detections, inference_stats["current_fps"])
                ok, jpeg = cv2.imencode(".jpg", frame_with_overlay, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
                if not ok:
                    continue
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n"
                    b"Content-Length: " + str(len(jpeg)).encode() + b"\r\n\r\n" + jpeg.tobytes() + b"\r\n"
                )
            except Exception as e:
                print(f"[ERROR] Video feed error: {e}")

    return Response(generate(), mimetype="multipart/x-mixed-replace; boundary=frame")


@app.route("/health")
def health():
    """Health check endpoint."""
    return jsonify(
        {
            "status": "ok",
            "camera_connected": inference_stats["camera_connected"],
            "fps": round(inference_stats["current_fps"], 1),
            "frames": inference_stats["total_frames"],
            "inferences": inference_stats["total_inferences"],
        }
    ), 200


@app.route("/api/stats")
def api_stats():
    """Get inference statistics."""
    return jsonify(
        {
            "frame_count": frame_count,
            "inference_count": inference_count,
            "current_fps": round(inference_stats["current_fps"], 1),
            "avg_inference_time_ms": round(inference_stats["avg_inference_time_ms"], 1),
            "p95_inference_time_ms": round(inference_stats["p95_inference_time_ms"], 1),
            "inference_fps": round(inference_stats["inference_fps"], 1),
            "queue_drops": inference_stats["queue_drops"],
            "last_alert_latency_ms": (
                round(inference_stats["last_alert_latency_ms"], 1)
                if inference_stats["last_alert_latency_ms"] is not None
                else None
            ),
            "last_alert": inference_stats["last_alert"],
            "camera_connected": inference_stats["camera_connected"],
            "config": {
                "frame_size": ESP32_CAM_RESOLUTION,
                "inference_every_n_frames": INFERENCE_EVERY_N_FRAMES,
                "jpeg_quality": JPEG_QUALITY,
                "score_threshold": SCORE_THRESHOLD,
                "alert_priority_threshold": ALERT_PRIORITY_THRESHOLD,
                "max_results": MAX_RESULTS,
                "temporal_smoothing_enabled": TEMPORAL_ALERT_SMOOTHING_ENABLED,
                "temporal_hold_frames": TEMPORAL_ALERT_HOLD_FRAMES,
                "temporal_hold_seconds": TEMPORAL_ALERT_HOLD_SECONDS,
                "inference_preprocessing_enabled": INFERENCE_PREPROCESSING_ENABLED,
            },
        }
    ), 200


@app.route("/api/config", methods=["GET"])
def get_config():
    """Get current configuration."""
    return jsonify(
        {
            "esp32_stream_url": app.config.get("ESP32_STREAM_URL", ESP32_STREAM_URL),
            "inference_every_n_frames": INFERENCE_EVERY_N_FRAMES,
            "jpeg_quality": JPEG_QUALITY,
            "frame_resolution": ESP32_CAM_RESOLUTION,
            "score_threshold": SCORE_THRESHOLD,
            "alert_priority_threshold": ALERT_PRIORITY_THRESHOLD,
            "max_results": MAX_RESULTS,
            "temporal_smoothing_enabled": TEMPORAL_ALERT_SMOOTHING_ENABLED,
            "temporal_hold_frames": TEMPORAL_ALERT_HOLD_FRAMES,
            "temporal_hold_seconds": TEMPORAL_ALERT_HOLD_SECONDS,
            "inference_preprocessing_enabled": INFERENCE_PREPROCESSING_ENABLED,
        }
    ), 200


@app.route("/tts")
def tts_endpoint():
    """Generate cached Vietnamese TTS audio for dashboard alerts."""
    text = request.args.get("text", "").strip()
    if not text:
        return jsonify({"error": "text parameter required"}), 400

    text_hash = hashlib.md5(text.encode("utf-8")).hexdigest()
    cache_path = os.path.join(TTS_CACHE_DIR, f"{text_hash}.mp3")

    if not os.path.exists(cache_path):
        try:
            from gtts import gTTS

            fd, tmp_path = tempfile.mkstemp(dir=TTS_CACHE_DIR, suffix=".mp3")
            os.close(fd)
            gTTS(text, lang="vi", slow=False).save(tmp_path)
            os.replace(tmp_path, cache_path)
        except Exception as e:
            return jsonify({"error": f"TTS generation failed: {e}"}), 500

    return send_file(cache_path, mimetype="audio/mpeg")


# ==================== MAIN ====================
if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        camera_url = sys.argv[1]
        app.config["ESP32_STREAM_URL"] = camera_url
        print(f"[INFO] Using camera stream URL: {camera_url}")

    init_models()

    capture_thread = threading.Thread(target=capture_stream, daemon=True)
    capture_thread.start()
    inference_thread = threading.Thread(target=inference_worker, daemon=True)
    inference_thread.start()
    print("[INFO] Capture and inference threads started")

    print(f"[INFO] Starting web server on http://{SERVER_HOST}:{WEB_PORT}")
    print(f"[INFO] Video feed available at http://localhost:{WEB_PORT}/video_feed")

    try:
        app.run(host=SERVER_HOST, port=WEB_PORT, debug=False, threaded=True)
    except KeyboardInterrupt:
        print("\n[INFO] Shutting down...")
