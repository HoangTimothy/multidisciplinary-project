from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

from config import (
    CENTER_ZONE_MAX_X,
    CENTER_ZONE_MIN_X,
    CLASS_WEIGHTS,
    FRAME_HEIGHT,
    FRAME_WIDTH,
    INFER_EVERY_N_FRAMES,
    LOWER_ZONE_MIN_Y,
    MAX_RESULTS,
    MEDIUM_AREA_RATIO,
    NEAR_AREA_RATIO,
    SCORE_THRESHOLD,
    SPEAK_COOLDOWN_SECONDS,
)


@dataclass(frozen=True)
class RuntimeParams:
    frame_width: int = FRAME_WIDTH
    frame_height: int = FRAME_HEIGHT
    infer_every_n_frames: int = INFER_EVERY_N_FRAMES
    jpeg_quality: int = 60
    inference_queue_size: int = 1


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


@dataclass(frozen=True)
class AlertParams:
    speak_cooldown_seconds: float = SPEAK_COOLDOWN_SECONDS
    client_repeat_guard_seconds: float = 3.0


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
