from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
MODEL_DIR = BASE_DIR / "models"
MODEL_ID = "efficientdet_lite0_int8"
MODEL_PATH = MODEL_DIR / "efficientdet_lite0_int8.tflite"
MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/object_detector/"
    "efficientdet_lite0/int8/latest/efficientdet_lite0.tflite"
)

CAMERA_INDEX = 0
FRAME_WIDTH = 640
FRAME_HEIGHT = 480
INFER_EVERY_N_FRAMES = 5
SCORE_THRESHOLD = 0.35
MAX_RESULTS = 15

# Distance estimation thresholds
NEAR_AREA_RATIO = 0.18
MEDIUM_AREA_RATIO = 0.06

# Spatial zones
CENTER_ZONE_MIN_X = 0.25
CENTER_ZONE_MAX_X = 0.75
LOWER_ZONE_MIN_Y = 0.40

SPEAK_COOLDOWN_SECONDS = 3.0
REPEAT_IF_RISK_UPGRADED_SECONDS = 1.0
ALERT_PRIORITY_THRESHOLD = 0.35

# Collision-risk logic
GENERIC_OBSTACLE_LABEL_VI = "vật cản"
GENERIC_RISK_ENABLED = True
GENERIC_RISK_MIN_AREA_RATIO = 0.08
GENERIC_RISK_MIN_CENTER_AREA_RATIO = 0.045
GENERIC_RISK_LOWER_ZONE_MIN_Y = 0.35
GENERIC_RISK_PRIORITY_THRESHOLD = 0.48

# Temporal smoothing
TEMPORAL_ALERT_SMOOTHING_ENABLED = True
TEMPORAL_ALERT_HOLD_FRAMES = 2
TEMPORAL_ALERT_HOLD_SECONDS = 0.8

# Image preprocessing
INFERENCE_PREPROCESSING_ENABLED = True
PREPROCESS_DENOISE_ENABLED = True
PREPROCESS_LOW_LIGHT_ENABLED = True

VI_LABELS = {
    "person": "người",
    "bicycle": "xe đạp",
    "car": "ô tô",
    "motorcycle": "xe máy",
    "airplane": "máy bay",
    "bus": "xe buýt",
    "train": "tàu hỏa",
    "truck": "xe tải",
    "boat": "thuyền",
    "traffic light": "đèn giao thông",
    "fire hydrant": "vòi cứu hỏa",
    "stop sign": "biển báo dừng",
    "parking meter": "đồng hồ đỗ xe",
    "bench": "ghế dài",
    "bird": "chim",
    "cat": "mèo",
    "dog": "chó",
    "horse": "ngựa",
    "sheep": "cừu",
    "cow": "bò",
    "elephant": "voi",
    "bear": "gấu",
    "zebra": "ngựa vằn",
    "giraffe": "hươu cao cổ",
    "backpack": "ba lô",
    "umbrella": "ô dù",
    "handbag": "túi xách",
    "tie": "cà vạt",
    "suitcase": "va li",
    "frisbee": "đĩa bay",
    "skis": "ván trượt tuyết",
    "snowboard": "ván trượt",
    "sports ball": "bóng thể thao",
    "kite": "diều",
    "baseball bat": "gậy bóng chày",
    "baseball glove": "găng tay bóng chày",
    "skateboard": "ván trượt",
    "surfboard": "ván lướt sóng",
    "tennis racket": "vợt tennis",
    "bottle": "chai lọ",
    "wine glass": "ly rượu",
    "cup": "cốc",
    "fork": "nĩa",
    "knife": "dao",
    "spoon": "thìa",
    "bowl": "bát",
    "banana": "chuối",
    "apple": "táo",
    "sandwich": "bánh mì kẹp",
    "orange": "cam",
    "broccoli": "bông cải xanh",
    "carrot": "cà rốt",
    "hot dog": "xúc xích",
    "pizza": "bánh pizza",
    "donut": "bánh vòng",
    "cake": "bánh ngọt",
    "chair": "ghế",
    "couch": "ghế sofa",
    "potted plant": "chậu cây",
    "bed": "giường",
    "dining table": "bàn ăn",
    "toilet": "bồn cầu",
    "tv": "tivi",
    "laptop": "máy tính xách tay",
    "mouse": "chuột máy tính",
    "remote": "điều khiển",
    "keyboard": "bàn phím",
    "cell phone": "điện thoại",
    "microwave": "lò vi sóng",
    "oven": "lò nướng",
    "toaster": "máy nướng bánh mì",
    "sink": "bồn rửa",
    "refrigerator": "tủ lạnh",
    "book": "sách",
    "clock": "đồng hồ",
    "vase": "bình hoa",
    "scissors": "kéo",
    "teddy bear": "gấu bông",
    "hair drier": "máy sấy tóc",
    "toothbrush": "bàn chải đánh răng",
}

# Class weights for alert priority calculation
DEFAULT_CLASS_WEIGHT = 0.55
MOBILITY_CLASS_WEIGHTS = {
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
CLASS_WEIGHTS = {label: DEFAULT_CLASS_WEIGHT for label in VI_LABELS}
CLASS_WEIGHTS.update(MOBILITY_CLASS_WEIGHTS)

# High-confidence labels to preserve in TTS output
GENERIC_RISK_PRESERVE_LABELS = {
    "person",
    "bicycle",
    "motorcycle",
    "car",
    "bus",
    "truck",
    "chair",
    "bench",
    "backpack",
    "suitcase",
    "couch",
    "bed",
    "dining table",
    "potted plant",
    "tv",
    "laptop",
    "refrigerator",
}
