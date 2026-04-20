from __future__ import annotations

import time

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from config import CAMERA_INDEX, FRAME_HEIGHT, FRAME_WIDTH, INFER_EVERY_N_FRAMES
from decision_engine import DecisionEngine
from detector import ObstacleDetector
from model_utils import ensure_model
from tts_engine import VoiceAlertManager


def put_text_utf8(frame, text: str, xy, fontsize=20, color=(0, 255, 0)):
    """Draw UTF-8 text on frame using PIL."""
    pil_image = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(pil_image)
    try:
        font = ImageFont.truetype("arial.ttf", fontsize)
    except:
        font = ImageFont.load_default()
    draw.text(xy, text, font=font, fill=color)
    return cv2.cvtColor(np.array(pil_image), cv2.COLOR_RGB2BGR)


def draw_overlay(frame, obstacle, fps: float):
    cv2.putText(
        frame,
        f"FPS: {fps:.1f}",
        (10, 30),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.8,
        (0, 0, 255),
        2,
    )

    if obstacle is None:
        frame = put_text_utf8(frame, "Không có vật cản ưu tiên", (10, 65), fontsize=18, color=(0, 255, 255))
        return frame

    cv2.rectangle(
        frame,
        (obstacle.x, obstacle.y),
        (obstacle.x + obstacle.w, obstacle.y + obstacle.h),
        (0, 255, 0),
        2,
    )
    text = f"{obstacle.label} | {obstacle.distance_level} | {obstacle.horizontal_zone}"
    frame = put_text_utf8(frame, text, (obstacle.x, max(20, obstacle.y - 10)), fontsize=16, color=(0, 255, 0))
    
    frame = put_text_utf8(frame, obstacle.spoken_text, (10, FRAME_HEIGHT - 20), fontsize=16, color=(50, 220, 50))
    return frame


def main() -> None:
    ensure_model()

    detector = ObstacleDetector()
    decider = DecisionEngine(frame_width=FRAME_WIDTH, frame_height=FRAME_HEIGHT)
    voice = VoiceAlertManager()

    cap = cv2.VideoCapture(CAMERA_INDEX)
    if not cap.isOpened():
        raise RuntimeError("Khong mo duoc camera. Thu doi CAMERA_INDEX trong config.py")

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_HEIGHT)

    print("Nhan q de thoat.")

    frame_count = 0
    start_time = time.time()
    current_obstacle = None

    while True:
        ok, frame = cap.read()
        if not ok:
            print("Khong doc duoc frame tu camera.")
            break

        frame = cv2.resize(frame, (FRAME_WIDTH, FRAME_HEIGHT))
        frame_count += 1

        if frame_count % INFER_EVERY_N_FRAMES == 0:
            detections = detector.detect(frame)
            current_obstacle = decider.choose_alert(detections)
            if current_obstacle:
                print(
                    f"[ALERT] {current_obstacle.label} | {current_obstacle.distance_level} | "
                    f"{current_obstacle.horizontal_zone} | priority={current_obstacle.priority:.2f}"
                )
            voice.maybe_speak(current_obstacle)

        elapsed = max(time.time() - start_time, 1e-6)
        fps = frame_count / elapsed
        frame = draw_overlay(frame, current_obstacle, fps)

        cv2.imshow("Obstacle Warning", frame)
        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
