from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
MODEL_DIR = BASE_DIR / "models"
MODEL_PATH = MODEL_DIR / "efficientdet_lite0.tflite"
MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/object_detector/"
    "efficientdet_lite0/float32/latest/efficientdet_lite0.tflite"
)

CAMERA_INDEX = 0
FRAME_WIDTH = 640
FRAME_HEIGHT = 480
INFER_EVERY_N_FRAMES = 2
SCORE_THRESHOLD = 0.45
MAX_RESULTS = 8

# Relative distance estimation thresholds based on bounding box area ratio.
# These are starting values and should be tuned with real camera tests.
NEAR_AREA_RATIO = 0.18
MEDIUM_AREA_RATIO = 0.06

# Center danger zone: objects here are more relevant to the user's path.
CENTER_ZONE_MIN_X = 0.25
CENTER_ZONE_MAX_X = 0.75
LOWER_ZONE_MIN_Y = 0.40

SPEAK_COOLDOWN_SECONDS = 3.0
REPEAT_IF_RISK_UPGRADED_SECONDS = 1.0

# Only classes relevant to mobility safety should trigger alerts.
CLASS_WEIGHTS = {
    "person": 1.00,
    "bicycle": 0.90,
    "motorcycle": 1.00,
    "car": 0.95,
    "bus": 1.00,
    "truck": 1.00,
    "chair": 0.65,
    "bench": 0.60,
    "potted plant": 0.55,
    "suitcase": 0.60,
    "backpack": 0.45,
}

VI_LABELS = {
    "person": "người",
    "bicycle": "xe đạp",
    "motorcycle": "xe máy",
    "car": "ô tô",
    "bus": "xe buýt",
    "truck": "xe tải",
    "chair": "ghế",
    "bench": "ghế dài",
    "potted plant": "chậu cây",
    "suitcase": "va li",
    "backpack": "ba lô",
}
