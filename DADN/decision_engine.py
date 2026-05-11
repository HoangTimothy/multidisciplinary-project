from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

from config import (
    ALERT_PRIORITY_THRESHOLD,
    CENTER_ZONE_MAX_X,
    CENTER_ZONE_MIN_X,
    CLASS_WEIGHTS,
    GENERIC_OBSTACLE_LABEL_VI,
    GENERIC_RISK_ENABLED,
    GENERIC_RISK_LOWER_ZONE_MIN_Y,
    GENERIC_RISK_MIN_AREA_RATIO,
    GENERIC_RISK_MIN_CENTER_AREA_RATIO,
    GENERIC_RISK_PRESERVE_LABELS,
    GENERIC_RISK_PRIORITY_THRESHOLD,
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
    raw_label_vi: str
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
    semantic_priority: float
    collision_risk_priority: float
    alert_kind: str
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
        generic_risk_enabled: bool = GENERIC_RISK_ENABLED,
        generic_obstacle_label_vi: str = GENERIC_OBSTACLE_LABEL_VI,
        generic_risk_min_area_ratio: float = GENERIC_RISK_MIN_AREA_RATIO,
        generic_risk_min_center_area_ratio: float = GENERIC_RISK_MIN_CENTER_AREA_RATIO,
        generic_risk_lower_zone_min_y: float = GENERIC_RISK_LOWER_ZONE_MIN_Y,
        generic_risk_priority_threshold: float = GENERIC_RISK_PRIORITY_THRESHOLD,
        generic_risk_preserve_labels: Optional[Iterable[str]] = None,
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
        self.generic_risk_enabled = generic_risk_enabled
        self.generic_obstacle_label_vi = generic_obstacle_label_vi
        self.generic_risk_min_area_ratio = generic_risk_min_area_ratio
        self.generic_risk_min_center_area_ratio = generic_risk_min_center_area_ratio
        self.generic_risk_lower_zone_min_y = generic_risk_lower_zone_min_y
        self.generic_risk_priority_threshold = generic_risk_priority_threshold
        self.generic_risk_preserve_labels = set(generic_risk_preserve_labels or GENERIC_RISK_PRESERVE_LABELS)

    def choose_alert(self, detections: Iterable[DetectionItem]) -> Optional[ScoredObstacle]:
        candidates = [self._score_detection(item) for item in detections]
        candidates = [item for item in candidates if item is not None]
        if not candidates:
            return None
        return max(candidates, key=lambda item: item.priority)

    def _score_detection(self, det: DetectionItem) -> Optional[ScoredObstacle]:
        class_weight = self.class_weights.get(det.label)

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

        geometry_priority = distance_weight * center_weight * direction_weight * confidence_weight
        semantic_priority = (class_weight or 0.0) * geometry_priority
        semantic_pass = class_weight is not None and semantic_priority >= self.alert_priority_threshold

        generic_pass = self._is_generic_collision_risk(
            area_ratio=area_ratio,
            bottom_y_ratio=bottom_y_ratio,
            is_in_center_zone=is_in_center_zone,
            geometry_priority=geometry_priority,
        )
        if not semantic_pass and not generic_pass:
            return None

        raw_label_vi = VI_LABELS.get(det.label, det.label)
        use_generic_label = generic_pass and (
            not semantic_pass or self._should_use_generic_label(det.label, class_weight)
        )
        label_vi = self.generic_obstacle_label_vi if use_generic_label else raw_label_vi
        priority = max(semantic_priority, geometry_priority if generic_pass else 0.0)
        alert_kind = "generic_risk" if use_generic_label else "semantic"
        spoken_text = self._spoken_text(label_vi, distance_level, horizontal_zone)

        return ScoredObstacle(
            label=det.label,
            label_vi=label_vi,
            raw_label_vi=raw_label_vi,
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
            semantic_priority=semantic_priority,
            collision_risk_priority=geometry_priority,
            alert_kind=alert_kind,
            spoken_text=spoken_text,
        )

    def _is_generic_collision_risk(
        self,
        *,
        area_ratio: float,
        bottom_y_ratio: float,
        is_in_center_zone: bool,
        geometry_priority: float,
    ) -> bool:
        if not self.generic_risk_enabled:
            return False
        if bottom_y_ratio < self.generic_risk_lower_zone_min_y:
            return False
        has_risky_size = area_ratio >= self.generic_risk_min_area_ratio
        has_center_risky_size = (
            is_in_center_zone and area_ratio >= self.generic_risk_min_center_area_ratio
        )
        return (
            (has_risky_size or has_center_risky_size)
            and geometry_priority >= self.generic_risk_priority_threshold
        )

    def _should_use_generic_label(self, label: str, class_weight: Optional[float]) -> bool:
        if label in self.generic_risk_preserve_labels:
            return False
        return class_weight is None or class_weight <= 0.55

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
