from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

from core.config import (
    ALERT_PRIORITY_THRESHOLD,
    CENTER_ZONE_MAX_X,
    CENTER_ZONE_MIN_X,
    CLASS_WEIGHTS,
    FRAME_HEIGHT,
    FRAME_WIDTH,
    GENERIC_OBSTACLE_LABEL_VI,
    GENERIC_RISK_ENABLED,
    GENERIC_RISK_LOWER_ZONE_MIN_Y,
    GENERIC_RISK_MIN_AREA_RATIO,
    GENERIC_RISK_MIN_CENTER_AREA_RATIO,
    GENERIC_RISK_PRESERVE_LABELS,
    GENERIC_RISK_PRIORITY_THRESHOLD,
    INFER_EVERY_N_FRAMES,
    INFERENCE_PREPROCESSING_ENABLED,
    LOWER_ZONE_MIN_Y,
    MAX_RESULTS,
    MEDIUM_AREA_RATIO,
    NEAR_AREA_RATIO,
    PREPROCESS_DENOISE_ENABLED,
    PREPROCESS_LOW_LIGHT_ENABLED,
    SCORE_THRESHOLD,
    SPEAK_COOLDOWN_SECONDS,
    TEMPORAL_ALERT_HOLD_FRAMES,
    TEMPORAL_ALERT_HOLD_SECONDS,
    TEMPORAL_ALERT_SMOOTHING_ENABLED,
)


@dataclass(frozen=True)
class RuntimeParams:
    frame_width: int = FRAME_WIDTH
    frame_height: int = FRAME_HEIGHT
    infer_every_n_frames: int = INFER_EVERY_N_FRAMES
    jpeg_quality: int = 60
    inference_queue_size: int = 1
    inference_preprocessing_enabled: bool = INFERENCE_PREPROCESSING_ENABLED
    preprocess_denoise_enabled: bool = PREPROCESS_DENOISE_ENABLED
    preprocess_low_light_enabled: bool = PREPROCESS_LOW_LIGHT_ENABLED


@dataclass(frozen=True)
class DetectorParams:
    model_id: str = "efficientdet_lite0_int8"
    score_threshold: float = SCORE_THRESHOLD
    max_results: int = MAX_RESULTS


@dataclass(frozen=True)
class DecisionParams:
    near_area_ratio: float = NEAR_AREA_RATIO
    medium_area_ratio: float = MEDIUM_AREA_RATIO
    center_zone_min_x: float = CENTER_ZONE_MIN_X
    center_zone_max_x: float = CENTER_ZONE_MAX_X
    lower_zone_min_y: float = LOWER_ZONE_MIN_Y
    class_weights: Dict[str, float] = field(default_factory=lambda: dict(CLASS_WEIGHTS))
    distance_weights: Dict[str, float] = field(
        default_factory=lambda: {"near": 1.35, "medium": 1.05, "far": 0.75}
    )
    center_weight: float = 1.15
    off_center_weight: float = 0.85
    center_direction_weight: float = 1.0
    side_direction_weight: float = 0.92
    alert_priority_threshold: float = ALERT_PRIORITY_THRESHOLD
    generic_risk_enabled: bool = GENERIC_RISK_ENABLED
    generic_obstacle_label_vi: str = GENERIC_OBSTACLE_LABEL_VI
    generic_risk_min_area_ratio: float = GENERIC_RISK_MIN_AREA_RATIO
    generic_risk_min_center_area_ratio: float = GENERIC_RISK_MIN_CENTER_AREA_RATIO
    generic_risk_lower_zone_min_y: float = GENERIC_RISK_LOWER_ZONE_MIN_Y
    generic_risk_priority_threshold: float = GENERIC_RISK_PRIORITY_THRESHOLD
    generic_risk_preserve_labels: list[str] = field(default_factory=lambda: sorted(GENERIC_RISK_PRESERVE_LABELS))


@dataclass(frozen=True)
class AlertParams:
    speak_cooldown_seconds: float = SPEAK_COOLDOWN_SECONDS
    client_repeat_guard_seconds: float = 3.0
    temporal_smoothing_enabled: bool = TEMPORAL_ALERT_SMOOTHING_ENABLED
    temporal_hold_frames: int = TEMPORAL_ALERT_HOLD_FRAMES
    temporal_hold_seconds: float = TEMPORAL_ALERT_HOLD_SECONDS


@dataclass(frozen=True)
class ExperimentConfig:
    experiment_id: str
    description: str
    detector: DetectorParams
    runtime: RuntimeParams
    decision: DecisionParams
    alert: AlertParams


def _merge_dict(defaults: Dict[str, Any], overrides: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    merged = dict(defaults)
    if overrides:
        merged.update(overrides)
    return merged


def load_experiment_config(path: Path) -> ExperimentConfig:
    data = json.loads(path.read_text(encoding="utf-8"))

    detector_defaults = DetectorParams().__dict__
    runtime_defaults = RuntimeParams().__dict__
    decision_defaults = DecisionParams().__dict__
    alert_defaults = AlertParams().__dict__

    return ExperimentConfig(
        experiment_id=data.get("experiment_id", path.stem),
        description=data.get("description", ""),
        detector=DetectorParams(**_merge_dict(detector_defaults, data.get("detector"))),
        runtime=RuntimeParams(**_merge_dict(runtime_defaults, data.get("runtime"))),
        decision=DecisionParams(**_merge_dict(decision_defaults, data.get("decision"))),
        alert=AlertParams(**_merge_dict(alert_defaults, data.get("alert"))),
    )
