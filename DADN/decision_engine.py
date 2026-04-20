from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

from config import (
    CENTER_ZONE_MAX_X,
    CENTER_ZONE_MIN_X,
    CLASS_WEIGHTS,
    LOWER_ZONE_MIN_Y,
    MEDIUM_AREA_RATIO,
    NEAR_AREA_RATIO,
    VI_LABELS,
)
from detector import DetectionItem


@dataclass
class ScoredObstacle:
    label: str
    label_vi: str
    score: float
    x: int
    y: int
    w: int
    h: int
    area_ratio: float
    horizontal_zone: str
    distance_level: str
    is_in_center_zone: bool
    priority: float
    spoken_text: str


class DecisionEngine:
    def __init__(self, frame_width: int, frame_height: int) -> None:
        self.frame_width = frame_width
        self.frame_height = frame_height
        self.frame_area = frame_width * frame_height

    def choose_alert(self, detections: Iterable[DetectionItem]) -> Optional[ScoredObstacle]:
        candidates = [self._score_detection(item) for item in detections]
        candidates = [item for item in candidates if item is not None]
        if not candidates:
            return None
        return max(candidates, key=lambda item: item.priority)

    def _score_detection(self, det: DetectionItem) -> Optional[ScoredObstacle]:
        class_weight = CLASS_WEIGHTS.get(det.label)
        if class_weight is None:
            return None

        area_ratio = (det.w * det.h) / max(self.frame_area, 1)
        center_x_ratio = (det.x + det.w / 2) / self.frame_width
        bottom_y_ratio = (det.y + det.h) / self.frame_height

        horizontal_zone = self._horizontal_zone(center_x_ratio)
        is_in_center_zone = CENTER_ZONE_MIN_X <= center_x_ratio <= CENTER_ZONE_MAX_X
        is_in_lower_zone = bottom_y_ratio >= LOWER_ZONE_MIN_Y

        distance_level, distance_weight = self._distance_level(area_ratio, is_in_lower_zone)
        center_weight = 1.15 if is_in_center_zone else 0.85
        direction_weight = 1.00 if horizontal_zone == "giữa" else 0.92
        confidence_weight = max(0.4, det.score)

        priority = (
            class_weight
            * distance_weight
            * center_weight
            * direction_weight
            * confidence_weight
        )

        label_vi = VI_LABELS.get(det.label, det.label)
        spoken_text = self._spoken_text(label_vi, distance_level, horizontal_zone)

        return ScoredObstacle(
            label=det.label,
            label_vi=label_vi,
            score=det.score,
            x=det.x,
            y=det.y,
            w=det.w,
            h=det.h,
            area_ratio=area_ratio,
            horizontal_zone=horizontal_zone,
            distance_level=distance_level,
            is_in_center_zone=is_in_center_zone,
            priority=priority,
            spoken_text=spoken_text,
        )

    @staticmethod
    def _horizontal_zone(center_x_ratio: float) -> str:
        if center_x_ratio < 0.33:
            return "bên trái"
        if center_x_ratio > 0.67:
            return "bên phải"
        return "giữa"

    @staticmethod
    def _spoken_text(label_vi: str, distance_level: str, horizontal_zone: str) -> str:
        if distance_level == "gần":
            return f"Cẩn thận, có {label_vi} ở {horizontal_zone}, rất gần"
        if distance_level == "trung bình":
            return f"Có {label_vi} ở {horizontal_zone}, khoảng cách trung bình"
        return f"Có {label_vi} ở {horizontal_zone}, phía trước"

    @staticmethod
    def _distance_level(area_ratio: float, is_in_lower_zone: bool) -> tuple[str, float]:
        adjusted_ratio = area_ratio * (1.1 if is_in_lower_zone else 1.0)
        if adjusted_ratio >= NEAR_AREA_RATIO:
            return "gần", 1.35
        if adjusted_ratio >= MEDIUM_AREA_RATIO:
            return "trung bình", 1.05
        return "xa", 0.75
