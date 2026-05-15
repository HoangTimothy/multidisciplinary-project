from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict

from core.config import MODEL_DIR


@dataclass(frozen=True)
class ModelSpec:
    model_id: str
    filename: str
    url: str
    input_size: tuple[int, int]
    quantization: str
    family: str
    role: str
    notes: str

    @property
    def path(self) -> Path:
        return MODEL_DIR / self.filename


MODEL_REGISTRY: Dict[str, ModelSpec] = {
    "efficientdet_lite0_int8": ModelSpec(
        model_id="efficientdet_lite0_int8",
        filename="efficientdet_lite0_int8.tflite",
        url="https://storage.googleapis.com/mediapipe-models/object_detector/efficientdet_lite0/int8/latest/efficientdet_lite0.tflite",
        input_size=(320, 320),
        quantization="int8",
        family="EfficientDet-Lite0",
        role="baseline",
        notes="MediaPipe recommended balanced model; current deployment baseline.",
    ),
    "efficientdet_lite0_float16": ModelSpec(
        model_id="efficientdet_lite0_float16",
        filename="efficientdet_lite0_float16.tflite",
        url="https://storage.googleapis.com/mediapipe-models/object_detector/efficientdet_lite0/float16/latest/efficientdet_lite0.tflite",
        input_size=(320, 320),
        quantization="float16",
        family="EfficientDet-Lite0",
        role="sanity",
        notes="Useful for latency/accuracy sanity checks against int8.",
    ),
    "efficientdet_lite0_float32": ModelSpec(
        model_id="efficientdet_lite0_float32",
        filename="efficientdet_lite0_float32.tflite",
        url="https://storage.googleapis.com/mediapipe-models/object_detector/efficientdet_lite0/float32/latest/efficientdet_lite0.tflite",
        input_size=(320, 320),
        quantization="float32",
        family="EfficientDet-Lite0",
        role="sanity",
        notes="Accuracy/latency comparison only; usually too slow for edge demo.",
    ),
    "efficientdet_lite2_int8": ModelSpec(
        model_id="efficientdet_lite2_int8",
        filename="efficientdet_lite2_int8.tflite",
        url="https://storage.googleapis.com/mediapipe-models/object_detector/efficientdet_lite2/int8/latest/efficientdet_lite2.tflite",
        input_size=(448, 448),
        quantization="int8",
        family="EfficientDet-Lite2",
        role="accuracy",
        notes="Higher-accuracy candidate with higher latency/memory cost.",
    ),
    "efficientdet_lite2_float16": ModelSpec(
        model_id="efficientdet_lite2_float16",
        filename="efficientdet_lite2_float16.tflite",
        url="https://storage.googleapis.com/mediapipe-models/object_detector/efficientdet_lite2/float16/latest/efficientdet_lite2.tflite",
        input_size=(448, 448),
        quantization="float16",
        family="EfficientDet-Lite2",
        role="accuracy_sanity",
        notes="Higher-accuracy candidate for latency/quantization comparison against Lite2 int8.",
    ),
    "efficientdet_lite2_float32": ModelSpec(
        model_id="efficientdet_lite2_float32",
        filename="efficientdet_lite2_float32.tflite",
        url="https://storage.googleapis.com/mediapipe-models/object_detector/efficientdet_lite2/float32/latest/efficientdet_lite2.tflite",
        input_size=(448, 448),
        quantization="float32",
        family="EfficientDet-Lite2",
        role="accuracy_sanity",
        notes="Largest Lite2 sanity candidate; generally too slow for latency-first edge.",
    ),
    "ssd_mobilenet_v2_float16": ModelSpec(
        model_id="ssd_mobilenet_v2_float16",
        filename="ssd_mobilenet_v2_float16.tflite",
        url="https://storage.googleapis.com/mediapipe-models/object_detector/ssd_mobilenet_v2/float16/latest/ssd_mobilenet_v2.tflite",
        input_size=(256, 256),
        quantization="float16",
        family="SSD MobileNetV2",
        role="fast",
        notes="Fast lightweight candidate; official docs also list SSD MobileNetV2 as lower accuracy than EfficientDet-Lite0.",
    ),
    "ssd_mobilenet_v2_float32": ModelSpec(
        model_id="ssd_mobilenet_v2_float32",
        filename="ssd_mobilenet_v2_float32.tflite",
        url="https://storage.googleapis.com/mediapipe-models/object_detector/ssd_mobilenet_v2/float32/latest/ssd_mobilenet_v2.tflite",
        input_size=(256, 256),
        quantization="float32",
        family="SSD MobileNetV2",
        role="fast_sanity",
        notes="Fast model sanity check when float16 is not representative on CPU.",
    ),
}


def get_model_spec(model_id: str) -> ModelSpec:
    try:
        return MODEL_REGISTRY[model_id]
    except KeyError as exc:
        available = ", ".join(sorted(MODEL_REGISTRY))
        raise ValueError(f"Unknown model_id '{model_id}'. Available: {available}") from exc
