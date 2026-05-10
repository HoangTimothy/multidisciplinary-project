from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

from config import (
    ALERT_PRIORITY_THRESHOLD,
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
    def __init__(
        self,
        frame_width: int,
        frame_height: int,
        *,
        near_area_ratio: float = NEAR_AREA_RATIO,
        medium_area_ratio: float = MEDIUM_AREA_RATIO,
        center_zone_min_x: float = CENTER_ZONE_MIN_X,
        center_zone_max_x: float = CENTER_ZONE_MAX_X,
        lower_zone_min_y: float = LOWER_ZONE_MIN_Y,
        class_weights: Optional[dict[str, float]] = None,
        distance_weights: Optional[dict[str, float]] = None,
        center_weight: float = 1.15,
        off_center_weight: float = 0.85,
        center_direction_weight: float = 1.0,
        side_direction_weight: float = 0.92,
        alert_priority_threshold: float = ALERT_PRIORITY_THRESHOLD,
    ) -> None:
        self.frame_width = frame_width
        self.frame_height = frame_height
        self.frame_area = frame_width * frame_height
        self.near_area_ratio = near_area_ratio
        self.medium_area_ratio = medium_area_ratio
        self.center_zone_min_x = center_zone_min_x
        self.center_zone_max_x = center_zone_max_x
        self.lower_zone_min_y = lower_zone_min_y
        self.class_weights = class_weights or CLASS_WEIGHTS
        self.distance_weights = distance_weights or {"near": 1.35, "medium": 1.05, "far": 0.75}
        self.center_weight = center_weight
        self.off_center_weight = off_center_weight
        self.center_direction_weight = center_direction_weight
        self.side_direction_weight = side_direction_weight
        self.alert_priority_threshold = alert_priority_threshold

    def choose_alert(self, detections: Iterable[DetectionItem]) -> Optional[ScoredObstacle]:
        candidates = [self._score_detection(item) for item in detections]
        candidates = [item for item in candidates if item is not None]
        if not candidates:
            return None
        return max(candidates, key=lambda item: item.priority)

    def _score_detection(self, det: DetectionItem) -> Optional[ScoredObstacle]:
        class_weight = self.class_weights.get(det.label)
        if class_weight is None:
            return None

        area_ratio = (det.w * det.h) / max(self.frame_area, 1)
        center_x_ratio = (det.x + det.w / 2) / self.frame_width
        bottom_y_ratio = (det.y + det.h) / self.frame_height

        horizontal_zone = self._horizontal_zone(center_x_ratio)
        is_in_center_zone = self.center_zone_min_x <= center_x_ratio <= self.center_zone_max_x
        is_in_lower_zone = bottom_y_ratio >= self.lower_zone_min_y

        distance_level, distance_weight = self._distance_level(area_ratio, is_in_lower_zone)
        center_weight = self.center_weight if is_in_center_zone else self.off_center_weight
        direction_weight = self.center_direction_weight if horizontal_zone == "giữa" else self.side_direction_weight
        confidence_weight = max(0.4, det.score)

        priority = (
            class_weight
            * distance_weight
            * center_weight
            * direction_weight
            * confidence_weight
        )
        if priority < self.alert_priority_threshold:
            return None

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

    def _distance_level(self, area_ratio: float, is_in_lower_zone: bool) -> tuple[str, float]:
        adjusted_ratio = area_ratio * (1.1 if is_in_lower_zone else 1.0)
        if adjusted_ratio >= self.near_area_ratio:
            return "gần", self.distance_weights["near"]
        if adjusted_ratio >= self.medium_area_ratio:
            return "trung bình", self.distance_weights["medium"]
        return "xa", self.distance_weights["far"]
