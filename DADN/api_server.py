"""
HTTP API Server for DADN inference
Receives images from ESP32, performs inference, returns detection results
"""
from __future__ import annotations

import io
import time
from typing import Optional

import cv2
import numpy as np
from flask import Flask, request, jsonify
from PIL import Image

from config import FRAME_HEIGHT, FRAME_WIDTH
from decision_engine import DecisionEngine
from detector import ObstacleDetector

app = Flask(__name__)

# Global instances
detector = None
decision_engine = None
last_inference_time = 0.0
inference_fps = 0.0


def init_models():
    """Initialize detector and decision engine"""
    global detector, decision_engine
    print("Loading models...")
    detector = ObstacleDetector()
    decision_engine = DecisionEngine(FRAME_WIDTH, FRAME_HEIGHT)
    print("Models loaded successfully")


def dict_from_obstacle(obstacle) -> dict:
    """Convert ScoredObstacle to dictionary for JSON serialization"""
    if obstacle is None:
        return None
    return {
        "label": obstacle.label,
        "label_vi": obstacle.label_vi,
        "confidence": float(obstacle.score),
        "bbox": {
            "x": obstacle.x,
            "y": obstacle.y,
            "width": obstacle.w,
            "height": obstacle.h,
        },
        "area_ratio": float(obstacle.area_ratio),
        "horizontal_zone": obstacle.horizontal_zone,
        "distance_level": obstacle.distance_level,
        "is_in_center_zone": obstacle.is_in_center_zone,
        "priority": float(obstacle.priority),
        "spoken_text": obstacle.spoken_text,
    }


@app.route("/health", methods=["GET"])
def health():
    """Health check endpoint"""
    return jsonify({"status": "ok", "fps": inference_fps}), 200


@app.route("/api/detect", methods=["POST"])
def detect():
    """
    Receive image from ESP32 and perform inference
    Expected: JPEG image in request.files['image']
    Returns: JSON with detections and primary alert
    """
    global last_inference_time, inference_fps

    try:
        if "image" not in request.files:
            return jsonify({"error": "No image provided"}), 400

        image_file = request.files["image"]
        
        # Read image
        img_bytes = image_file.read()
        img_pil = Image.open(io.BytesIO(img_bytes))
        img_bgr = cv2.cvtColor(np.array(img_pil), cv2.COLOR_RGB2BGR)
        
        # Resize to expected frame size
        img_bgr = cv2.resize(img_bgr, (FRAME_WIDTH, FRAME_HEIGHT))

        # Run detection
        start = time.time()
        detections = detector.detect(img_bgr)
        
        # Make decision (get best alert)
        alert = decision_engine.choose_alert(detections)
        
        inference_time = time.time() - start
        
        # Calculate FPS
        if last_inference_time > 0:
            inference_fps = 1.0 / (time.time() - last_inference_time)
        last_inference_time = time.time()

        # Build response
        response = {
            "success": True,
            "inference_time_ms": round(inference_time * 1000, 2),
            "fps": round(inference_fps, 1),
            "detections_count": len(detections),
            "detections": [
                {
                    "label": d.label,
                    "confidence": float(d.score),
                    "bbox": {"x": d.x, "y": d.y, "width": d.w, "height": d.h},
                }
                for d in detections
            ],
            "alert": dict_from_obstacle(alert),
        }
        
        return jsonify(response), 200

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/api/config", methods=["GET"])
def get_config():
    """Return current model configuration"""
    from config import (
        FRAME_HEIGHT,
        FRAME_WIDTH,
        SCORE_THRESHOLD,
        MAX_RESULTS,
        NEAR_AREA_RATIO,
        MEDIUM_AREA_RATIO,
    )
    return jsonify({
        "frame_width": FRAME_WIDTH,
        "frame_height": FRAME_HEIGHT,
        "score_threshold": SCORE_THRESHOLD,
        "max_results": MAX_RESULTS,
        "near_area_ratio": NEAR_AREA_RATIO,
        "medium_area_ratio": MEDIUM_AREA_RATIO,
    }), 200


if __name__ == "__main__":
    init_models()
    # Run on all interfaces at port 5000
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
