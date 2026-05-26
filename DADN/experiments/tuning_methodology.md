# DADN Tuning Methodology

This document explains how the DADN detector, runtime, and Decision Engine
parameters were selected. It separates benchmark-driven choices from heuristic
choices that were later validated by benchmarks and demo observations.

## Tuning Goal

The system is tuned for an obstacle-warning use case, so the primary objective is
not generic COCO object accuracy. The preferred behavior is:

- detect enough candidates so dangerous objects are not missed,
- select the most collision-relevant object in the frame,
- keep latency low enough for an edge demo,
- avoid repeated or unstable voice alerts.

For that reason, the main metric is `risk_alert_correctness`. Strict
`alert_correctness` is kept as a diagnostic metric because it also checks group,
zone, and distance labels when those labels are available.

## Metrics

| Metric | Meaning | Used for |
| --- | --- | --- |
| `risk_alert_correctness` | Whether the system raises or suppresses an alert correctly for a labeled risky frame | Primary safety-oriented metric |
| `alert_correctness` | Whether the alert also matches the expected group/zone/distance fields that exist in the label file | Stricter diagnostic |
| `detection_rate` | Fraction of frames with at least one detection | Recall/debugging signal |
| `alert_rate` | Fraction of frames that produce an alert | Missed-alert and spam analysis |
| `avg_latency_ms`, `p95_latency_ms` | Offline inference latency from the benchmark runner | Speed comparison between configs |
| `balanced_score` | Combined score used by `benchmark_inference.py` | Winner selection after eligibility gates |

The winner policy is:

- require enough benchmark frames and labeled frames,
- require minimum alert/risk correctness,
- select the highest `balanced_score`,
- if scores are close, prefer lower `p95_latency_ms`.

## Dataset Protocol

Three dataset levels are used:

| Dataset level | Purpose |
| --- | --- |
| Public COCO/BDD subset | Main offline model and config selection |
| Synthetic robustness set | Stress-test occlusion, low light, JPEG compression, resizing, motion blur, and noise |
| Real camera review set | Validate behavior on ESP32-CAM frames and demo-like scenes |

Public dataset labels are usually group-level: `person`, `vehicle`, and
`static_obstacle`. Zone and distance labels from public datasets are not treated
as final calibration because they do not come from the actual ESP32-CAM setup.

The repo uses one canonical safety ontology:

- `person`
- `vehicle`
- `static_obstacle`

That ontology is used for benchmark evaluation. At runtime, the Decision Engine
may speak a more specific class label or the generic fallback `vật cản`, but it
is still the same underlying safety decision.

For the formal report, use the specific object name when it is available and
reserve `vật cản` for the generic-risk fallback policy.

COCO-style object detectors are trained on the 80 COCO object classes. DADN does
not use all 80 classes as final alert classes; it maps navigation-relevant
classes into three groups: `person`, `vehicle`, and `static_obstacle`.

Important limitation: public COCO/BDD images are not i.i.d. with the actual
ESP32-CAM stream. The real stream has lower resolution, compression artifacts,
motion blur, unstable exposure, noise, and camera placement that differ from
public datasets. Public datasets are therefore used for offline model/config
selection only. The final claim must be supported by synthetic robustness tests
and real-camera review frames.

The positive-risk public subset is also not enough to measure false-alert spam.
Aggressive configs that lower thresholds too far must be validated on
negative/non-risk scenes before being promoted.

## Baseline Config

The baseline config is `balanced_lite0_int8`:

| Parameter group | Baseline value |
| --- | --- |
| Model | `efficientdet_lite0_int8` |
| `score_threshold` | `0.50` |
| `max_results` | `5` |
| Frame size | `640x480` |
| `infer_every_n_frames` | `5` |
| `jpeg_quality` | `60` |
| `inference_queue_size` | `1` |
| Near / medium area ratio | `0.18` / `0.06` |
| Center zone | `[0.25, 0.75]` |
| Lower-zone threshold | `0.40` |

This baseline was used as the reference when tuning recall, robustness, and
runtime tradeoffs.

## Detector Tuning

Detector tuning changes model family, confidence threshold, and the maximum
number of returned detections.

### Parameters Tuned

| Parameter | Tuned values / candidates | Rationale |
| --- | --- | --- |
| `model_id` | Lite0 int8, Lite0 float16/float32, Lite2 int8/float16/float32, SSD MobileNetV2 float16/float32 | Compare speed/accuracy tradeoff between official MediaPipe models |
| `score_threshold` | `0.50`, `0.45`, `0.40`, `0.35`, hard probe `0.25` | Lower values increase recall but may add false alerts |
| `max_results` | `5`, `8`, `10`, `15`, hard probe `25` | More candidates reduce missed dangerous objects in busy scenes |

### Main Change

The selected config, `tuned_lite0_int8_high_recall`, uses:

```json
"detector": {
  "model_id": "efficientdet_lite0_int8",
  "score_threshold": 0.35,
  "max_results": 15
}
```

Compared with the baseline, this lowers the threshold from `0.50` to `0.35` and
raises `max_results` from `5` to `15`. The purpose is to improve recall for
obstacle warning, where a missed obstacle is more harmful than one extra
candidate that the Decision Engine can filter.

### Evidence

On the public benchmark, Lite2 int8 reached higher correctness but had much
higher latency. Lite0 int8 was selected because it gave the best edge-oriented
tradeoff. On the synthetic robustness benchmark, the alert-recall tuning raised:

- `risk_alert_correctness`: `0.800 -> 0.816`
- `detection_rate`: `0.868 -> 0.901`
- `alert_rate`: `0.800 -> 0.816`

The hard-case probe `hard_recall_lite0_int8` lowered the threshold further to
`0.25` and raised `max_results` to `25`. It improved difficult occlusion and
motion-blur cases, but is kept as a diagnostic probe because positive-only hard
sets cannot measure false-alert spam.

## Runtime Tuning

Runtime tuning controls how often inference is run and how frames are prepared.

### Parameters Tuned

| Parameter | Selected value | Rationale |
| --- | ---: | --- |
| `frame_width`, `frame_height` | `640x480` | Server-side processing size; keeps a fixed 4:3 canvas for detection/overlay and is a pragmatic compromise, not a formal resolution-sweep winner |
| `infer_every_n_frames` | `5` | Reduces compute load while keeping alerts responsive for demo speed |
| `jpeg_quality` | `60` | Balances stream bandwidth and image quality |
| `inference_queue_size` | `1` | Drops stale frames and prioritizes the newest frame |
| `inference_preprocessing_enabled` | `true` | Enables robustness improvements before inference |
| `preprocess_denoise_enabled` | `true` | Reduces camera noise |
| `preprocess_low_light_enabled` | `true` | Improves visibility under dim lighting |

The current ESP32-CAM firmware captures the stream in QVGA, and the server
normalizes incoming frames to `640x480` before inference. ESP32-CAM hardware
can support higher capture resolutions, but those have not been benchmarked in
this repo yet. So `640x480` is the processing resolution used by the benchmark
and runtime pipeline, not a hardware limit of the camera.

### Evidence

Preprocessing and smoothing raised synthetic robustness performance:

- `risk_alert_correctness`: `0.816 -> 0.827`
- `alert_correctness`: `0.692 -> 0.702`
- `detection_rate`: `0.901 -> 0.911`

The strongest improvement was on noisy frames. The selected runtime config is
therefore kept for the current demo candidate.

### Remaining Runtime Work

The current repo stores the selected runtime values, but it does not yet contain
a complete FPS sweep table for `infer_every_n_frames = 3, 5, 7, 10` on the final
hardware. That should be measured with `record_metrics.py` or
`benchmark_stream.py` on the actual demo server.

Capture resolution should also be swept on the real setup with
`DADN/benchmark/esp32_resolution_sweep.py` before the report claims that one
ESP32-CAM size is better than the others. The current firmware default is QVGA,
but the hardware supports the higher modes in the sweep script.

## Decision Engine Tuning

Decision Engine tuning controls how detections are converted into spoken alerts.
It is not just class classification; it also uses geometry and collision risk.

### Scoring Logic

For each detection, the engine computes:

- bbox area ratio,
- horizontal zone,
- whether the object is inside the central zone,
- whether the object is low enough in the frame,
- distance level from bbox area,
- semantic priority from class weight,
- collision-risk priority from geometry.

The final alert is the candidate with the highest priority.

### Selected Geometry Parameters

| Parameter | Selected value | Meaning |
| --- | ---: | --- |
| `near_area_ratio` | `0.18` | Object is treated as near when bbox area is large enough |
| `medium_area_ratio` | `0.06` | Object is treated as medium-distance above this area |
| `center_zone_min_x` | `0.25` | Left edge of the central danger zone |
| `center_zone_max_x` | `0.75` | Right edge of the central danger zone |
| `lower_zone_min_y` | `0.40` | Objects lower in the frame are more likely to be collision-relevant |
| `distance_weights.near` | `1.35` | Near objects receive higher priority |
| `distance_weights.medium` | `1.05` | Medium objects receive moderate priority |
| `distance_weights.far` | `0.75` | Far objects receive lower priority |
| `center_weight` | `1.15` | Central objects are prioritized |
| `off_center_weight` | `0.85` | Side objects are deprioritized |

These geometry values are heuristic parameters based on bbox geometry and demo
observations. They were then validated through benchmark runs rather than
derived from a full grid search.

### Generic Collision-Risk Parameters

The generic-risk logic allows the runtime to speak the generic fallback
`vật cản` when the detected COCO class name is not useful but the geometry is
dangerous.

| Parameter | Selected value |
| --- | ---: |
| `GENERIC_RISK_MIN_AREA_RATIO` | `0.08` |
| `GENERIC_RISK_MIN_CENTER_AREA_RATIO` | `0.045` |
| `GENERIC_RISK_LOWER_ZONE_MIN_Y` | `0.35` |
| `GENERIC_RISK_PRIORITY_THRESHOLD` | `0.48` |

These were tuned in the alert-recall run:

- `GENERIC_RISK_MIN_AREA_RATIO`: `0.10 -> 0.08`
- `GENERIC_RISK_MIN_CENTER_AREA_RATIO`: `0.06 -> 0.045`
- `GENERIC_RISK_PRIORITY_THRESHOLD`: `0.55 -> 0.48`

This increased risk correctness on robustness data, mostly by reducing missed
alerts for physically risky boxes whose class names were not ideal navigation
labels.

## Alert Smoothing Tuning

The selected alert settings are:

| Parameter | Selected value | Meaning |
| --- | ---: | --- |
| `speak_cooldown_seconds` | `3.0` | Avoid repeating voice alerts too often |
| `client_repeat_guard_seconds` | `3.0` | Browser-side repeat guard |
| `temporal_smoothing_enabled` | `true` | Keep alert stable through short detector misses |
| `temporal_hold_frames` | `2` | Hold the last alert for up to 2 inference frames |
| `temporal_hold_seconds` | `0.8` | Time limit for held alerts |

On still-image robustness data, smoothing is only partially evaluated because
temporal behavior requires a real stream. It should be validated with ESP32-CAM
runtime tests.

## Current Selected Config

The current selected config is `tuned_lite0_int8_high_recall`:

| Group | Selected value |
| --- | --- |
| Detector | EfficientDet-Lite0 int8, `score_threshold = 0.35`, `max_results = 15` |
| Runtime | `640x480`, infer every 5 frames, JPEG quality 60, queue size 1 |
| Preprocessing | denoise + low-light enhancement enabled |
| Decision | bbox geometry, center/lower-zone priority, generic collision-risk fallback |
| Alert | 3s cooldown, temporal hold 2 frames / 0.8s |

## What Is Benchmark-Driven vs Heuristic

| Component | Status |
| --- | --- |
| Model family selection | Benchmark-driven |
| `score_threshold` and `max_results` | Benchmark-driven |
| Generic-risk thresholds | Benchmark-driven on robustness data |
| Preprocessing on/off | Benchmark-driven on robustness data |
| Temporal smoothing | Partially validated; needs real stream validation |
| `infer_every_n_frames = 5` | Engineering tradeoff; needs final hardware FPS sweep |
| `near_area_ratio`, `medium_area_ratio`, center/lower-zone thresholds | Heuristic geometry values validated by benchmark/demo, not exhaustive grid search |

## How to Reproduce

Run the measurement on an existing labeled public subset:

```bash
python DADN/benchmark/record_metrics.py \
  --dataset /data/dadn-public-subset/images \
  --labels /data/dadn-public-subset/labels.json \
  --config DADN/experiments/configs/balanced_lite0_int8.json \
  --config DADN/experiments/configs/tuned_lite0_int8_recall.json \
  --config DADN/experiments/configs/tuned_lite0_int8_high_recall.json \
  --config DADN/experiments/configs/accuracy_lite2_int8.json \
  --config DADN/experiments/configs/fast_ssd_mobilenet_v2_float16.json \
  --skip-runtime \
  --min-frames 200 \
  --min-labeled-frames 200
```

Run the tuning sweep on an existing dataset/labels pair:

```bash
python DADN/experiments/run_tuning_sweep.py \
  --dataset /data/dadn-public-subset/images \
  --labels /data/dadn-public-subset/labels.json \
  --min-frames 200 \
  --min-labeled-frames 200
```

This writes a timestamped run directory containing:

- dataset trace derived from the labels file,
- group distribution and positive/negative alert counts,
- generated sweep config files,
- raw per-config CSV files,
- benchmark `summary.json`,
- `tuning_sweep_summary.md`.

Dataset preparation is a support step and is not part of the measurement flow.
If you need to build the dataset or review frames, use the support scripts
separately and keep them out of the reported benchmark command.

Runtime validation on a running dashboard:

```bash
python DADN/benchmark/record_metrics.py \
  --skip-offline \
  --server-url http://127.0.0.1:5000 \
  --runs 3 \
  --warmup 10 \
  --duration 60 \
  --interval 1
```

## How to Explain to an Examiner

The detector threshold and max results were tuned by benchmark sweeps because
the project prioritizes missed-obstacle reduction. The Decision Engine combines
semantic class weights with geometric risk from bbox size, position, and lower
frame placement. Some geometric thresholds are heuristic because the system has
no depth sensor; they are validated against benchmark and demo data rather than
claimed as physically calibrated distances. Runtime settings were selected to
keep the stream responsive, and final FPS/latency should be reported from the
actual demo hardware. Public-dataset results should be described as offline
validation, not as proof that the runtime stream distribution is i.i.d. with the
dataset.
