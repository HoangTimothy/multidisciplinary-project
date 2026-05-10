from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from decision_engine import DecisionEngine
from detector import DetectionItem
from benchmark_inference import choose_winner
from experiment_config import load_experiment_config
from model_registry import get_model_spec


def test_model_registry_baseline_spec():
    spec = get_model_spec("efficientdet_lite0_int8")
    assert spec.input_size == (320, 320)
    assert spec.quantization == "int8"
    assert spec.path.name == "efficientdet_lite0_int8.tflite"


def test_experiment_config_loads_balanced_config():
    config = load_experiment_config(Path("DADN/experiments/configs/balanced_lite0_int8.json"))
    assert config.experiment_id == "balanced_lite0_int8"
    assert config.detector.model_id == "efficientdet_lite0_int8"
    assert config.runtime.infer_every_n_frames == 5
    assert config.decision.distance_weights["near"] > config.decision.distance_weights["far"]


def test_decision_engine_accepts_tunable_thresholds():
    engine = DecisionEngine(
        640,
        480,
        near_area_ratio=0.05,
        medium_area_ratio=0.02,
        center_zone_min_x=0.3,
        center_zone_max_x=0.7,
        class_weights={"person": 1.0},
    )
    alert = engine.choose_alert([DetectionItem("person", 0.9, 260, 240, 120, 180)])
    assert alert is not None
    assert alert.distance_level == "gần"
    assert alert.horizontal_zone == "giữa"


def test_benchmark_winner_prefers_latency_when_scores_are_close():
    summaries = [
        {
            "experiment_id": "accurate_slow",
            "model_id": "efficientdet_lite2_int8",
            "frames": 250,
            "labeled_frames": 250,
            "alert_correctness": 0.85,
            "balanced_score": 0.82,
            "p95_latency_ms": 130.0,
        },
        {
            "experiment_id": "fast_close",
            "model_id": "ssd_mobilenet_v2_float16",
            "frames": 250,
            "labeled_frames": 250,
            "alert_correctness": 0.82,
            "balanced_score": 0.80,
            "p95_latency_ms": 60.0,
        },
    ]

    winner = choose_winner(
        summaries,
        default_model_id="efficientdet_lite0_int8",
        min_alert_correctness=0.75,
        close_score_delta=0.03,
        min_frames=200,
        min_labeled_frames=200,
    )

    assert winner["experiment_id"] == "fast_close"
    assert winner["fallback"] is False


def test_benchmark_winner_falls_back_without_labeled_evidence():
    summaries = [
        {
            "experiment_id": "balanced_lite0_int8",
            "model_id": "efficientdet_lite0_int8",
            "frames": 20,
            "labeled_frames": 0,
            "alert_correctness": None,
            "balanced_score": 0.70,
            "p95_latency_ms": 56.0,
        },
        {
            "experiment_id": "fast_ssd_mobilenet_v2_float16",
            "model_id": "ssd_mobilenet_v2_float16",
            "frames": 20,
            "labeled_frames": 0,
            "alert_correctness": None,
            "balanced_score": 0.78,
            "p95_latency_ms": 62.0,
        },
    ]

    winner = choose_winner(
        summaries,
        default_model_id="efficientdet_lite0_int8",
        min_alert_correctness=0.75,
        close_score_delta=0.03,
        min_frames=200,
        min_labeled_frames=200,
    )

    assert winner["model_id"] == "efficientdet_lite0_int8"
    assert winner["fallback"] is True
