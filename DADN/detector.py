from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List

import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision

from config import MAX_RESULTS, MODEL_PATH, SCORE_THRESHOLD


@dataclass
class DetectionItem:
    label: str
    score: float
    x: int
    y: int
    w: int
    h: int


class ObstacleDetector:
    def __init__(
        self,
        model_path: Path | str | None = None,
        score_threshold: float | None = None,
        max_results: int | None = None,
    ) -> None:
        options = vision.ObjectDetectorOptions(
            base_options=python.BaseOptions(model_asset_path=str(model_path or MODEL_PATH)),
            running_mode=vision.RunningMode.IMAGE,
            max_results=max_results if max_results is not None else MAX_RESULTS,
            score_threshold=score_threshold if score_threshold is not None else SCORE_THRESHOLD,
        )
        self.detector = vision.ObjectDetector.create_from_options(options)

    def detect(self, frame_bgr) -> List[DetectionItem]:
        frame_rgb = mp.Image(
            image_format=mp.ImageFormat.SRGB,
            data=frame_bgr[:, :, ::-1].copy(),
        )
        result = self.detector.detect(frame_rgb)

        items: List[DetectionItem] = []
        for detection in result.detections:
            category = detection.categories[0]
            bbox = detection.bounding_box
            items.append(
                DetectionItem(
                    label=category.category_name,
                    score=float(category.score),
                    x=int(bbox.origin_x),
                    y=int(bbox.origin_y),
                    w=int(bbox.width),
                    h=int(bbox.height),
                )
            )
        return items
