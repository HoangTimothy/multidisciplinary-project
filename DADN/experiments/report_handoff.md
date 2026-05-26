# DADN Report Handoff Brief

This file merges the tuning methodology and final benchmark conclusions into one
source of truth for report writing. It is written so another agent can turn it
into a formal thesis/report section without having to chase multiple files.

## One-line project summary

DADN is an ESP32-CAM plus edge-server obstacle warning system that streams
camera frames over Wi-Fi, runs an EfficientDet-Lite0-based detector on the
server, applies a geometry-aware Decision Engine, and speaks alert messages on
the dashboard.

## What was actually tuned

The project does **not** use a separate ML adapter, LoRA, or custom head.
Tuning is config-based and post-processing based:

- detector family and detector thresholds,
- runtime frame/queue/preprocessing settings,
- Decision Engine geometry and risk thresholds,
- alert smoothing and repeat-guard logic.

Support scripts exist for dataset construction and review labeling, but they are
not part of the main measurement flow.

## Labeling convention

There is one canonical safety ontology in the repo:

- `person`
- `vehicle`
- `static_obstacle`

That ontology is used for benchmark labels and evaluation. At runtime, the same
selected detection may be spoken with a more natural label such as `người`,
`ô tô`, or the generic fallback `vật cản` when the exact class name is not
useful for navigation.

For the formal report, prefer the specific object name when it is available
(`người`, `ô tô`, `xe máy`, `ghế`, ...). Reserve `vật cản` for the generic-risk
fallback section or when discussing the alerting policy at a higher level.

So the repo is **not** using two different taxonomies. It is using one safety
taxonomy and two surface forms:

- benchmark surface form: group-level labels for evaluation,
- runtime surface form: spoken Vietnamese label for the user.

The important rule is that the report must not mix those two forms as if they
were different semantic systems.

## Tuning goal

The system is tuned for obstacle warning, not generic COCO object accuracy. The
preferred behavior is:

- do not miss dangerous obstacles,
- choose the most collision-relevant object in the frame,
- keep latency low enough for an edge demo,
- avoid repeated or unstable voice alerts.

Because of that, the main safety metric is `risk_alert_correctness`. Strict
`alert_correctness` is kept as a diagnostic metric because it also checks group,
zone, and distance labels when those labels are available.

## Dataset protocol

Three dataset levels are used:

| Dataset level | Purpose |
| --- | --- |
| Public COCO/BDD subset | Main offline model and config selection |
| Synthetic robustness set | Stress-test occlusion, low light, JPEG compression, resizing, motion blur, and noise |
| Real camera review set | Validate behavior on ESP32-CAM frames and demo-like scenes |

Important limitations:

- Public COCO/BDD images are used for **offline** model/config selection, but
  they are **not i.i.d.** with the actual ESP32-CAM stream.
- The real stream has lower resolution, compression artifacts, motion blur,
  unstable exposure, noise, and camera placement differences.
- If a dataset is not representative enough for the deployment target, it
  should **not** be used to select the final config. Keep it only as a
  sanity/debug benchmark.
- So the public benchmark tells us which config is better on a controlled
  benchmark, not that the live stream follows the same distribution.
- The public benchmark subset is positive-risk heavy, so it cannot by itself
  prove false-alert behavior on negative scenes.
- Final claims should be supported by synthetic robustness tests and real-camera
  review frames.

COCO-style object detectors are trained on 80 COCO classes, but DADN maps
navigation-relevant classes into three groups:

- `person`
- `vehicle`
- `static_obstacle`

## Baseline config

The baseline config is `balanced_lite0_int8`.

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

## Winner policy

The repo uses this selection policy for the current offline benchmark path:

- require enough benchmarked frames/images,
- require enough labeled frames/images,
- require minimum alert/risk correctness,
- select the highest `balanced_score`,
- if scores are close, prefer lower `p95_latency_ms`,
- if no config is eligible, keep `efficientdet_lite0_int8`.

If you want the strict deployment rule, public COCO/BDD should **not** be the
final gate. In that version, the final deployment choice must come from
synthetic robustness and real-camera review evidence, while public COCO/BDD is
only a pre-screen.

The tuned winner in the current repo is:

- `tuned_lite0_int8_high_recall`
- EfficientDet-Lite0 int8
- `score_threshold = 0.35`
- `max_results = 15`

## Detector tuning

Detector tuning changes model family, confidence threshold, and the maximum
number of returned detections.

### Tuned parameters

| Parameter | Tuned values / candidates | Rationale |
| --- | --- | --- |
| `model_id` | Lite0 int8, Lite0 float16/float32, Lite2 int8/float16/float32, SSD MobileNetV2 float16/float32 | Compare speed/accuracy tradeoff between official MediaPipe models |
| `score_threshold` | `0.50`, `0.45`, `0.40`, `0.35`, hard probe `0.25` | Lower values increase recall but may add false alerts |
| `max_results` | `5`, `8`, `10`, `15`, hard probe `25` | More candidates reduce missed dangerous objects in busy scenes |

### Main detector change

`tuned_lite0_int8_high_recall` uses:

```json
"detector": {
  "model_id": "efficientdet_lite0_int8",
  "score_threshold": 0.35,
  "max_results": 15
}
```

Compared with the baseline, this lowers the threshold from `0.50` to `0.35`
and raises `max_results` from `5` to `15`. The purpose is to improve recall for
obstacle warning, where a missed obstacle is more harmful than one extra
candidate that the Decision Engine can filter.

### Detector evidence

On the public benchmark, Lite2 int8 reached higher correctness but had much
higher latency. Lite0 int8 was selected because it gave the best edge-oriented
tradeoff.

On the synthetic robustness benchmark, the alert-recall tuning raised:

- `risk_alert_correctness`: `0.800 -> 0.816`
- `detection_rate`: `0.868 -> 0.901`
- `alert_rate`: `0.800 -> 0.816`

The hard-case probe `hard_recall_lite0_int8` lowered the threshold further to
`0.25` and raised `max_results` to `25`. It improved difficult occlusion and
motion-blur cases, but it is kept as a diagnostic probe because positive-only
hard sets cannot measure false-alert spam.

## Runtime tuning

Runtime tuning controls how often inference is run and how frames are prepared.

### Tuned parameters

| Parameter | Selected value | Rationale |
| --- | ---: | --- |
| `frame_width`, `frame_height` | `640x480` | Server-side processing size; keeps a fixed 4:3 canvas for detection/overlay and is a pragmatic compromise, not a formal resolution-sweep winner |
| `infer_every_n_frames` | `5` | Reduces compute load while keeping alerts responsive for demo speed |
| `jpeg_quality` | `60` | Balances stream bandwidth and image quality |
| `inference_queue_size` | `1` | Drops stale frames and prioritizes the newest frame |
| `inference_preprocessing_enabled` | `true` | Enables robustness improvements before inference |
| `preprocess_denoise_enabled` | `true` | Reduces camera noise |
| `preprocess_low_light_enabled` | `true` | Improves visibility under dim lighting |

The current ESP32-CAM firmware is configured to QVGA, and the server normalizes
incoming frames to `640x480` before inference. ESP32-CAM hardware can support
higher capture resolutions, but this repo has not yet benchmarked them, so the
report should describe `640x480` as the processing resolution and QVGA as the
current capture setting, not as a hardware limit.

If the report needs to justify the chosen capture resolution, it should refer to
the dedicated `DADN/benchmark/esp32_resolution_sweep.py` script and the real
Raspberry Pi results, not to the firmware default alone.

### Runtime evidence

Preprocessing and smoothing raised synthetic robustness performance:

- `risk_alert_correctness`: `0.816 -> 0.827`
- `alert_correctness`: `0.692 -> 0.702`
- `detection_rate`: `0.901 -> 0.911`

The strongest improvement was on noisy frames. The selected runtime config is
therefore kept for the current demo candidate.

### Remaining runtime work

The repo stores the selected runtime values, but it does not yet contain a full
FPS sweep table for `infer_every_n_frames = 3, 5, 7, 10` on the final hardware.
That should be measured with `record_metrics.py` or `benchmark_stream.py` on the
actual demo server.

## Decision Engine tuning

Decision Engine tuning controls how detections are converted into spoken alerts.
It is not just class classification; it also uses geometry and collision risk.

### Scoring logic

For each detection, the engine computes:

- bbox area ratio,
- horizontal zone,
- whether the object is inside the central zone,
- whether the object is low enough in the frame,
- distance level from bbox area,
- semantic priority from class weight,
- collision-risk priority from geometry.

The final alert is the candidate with the highest priority.

### Selected geometry parameters

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

### Generic collision-risk parameters

The generic-risk logic controls when the runtime is allowed to use the generic
spoken fallback `vật cản` instead of a more specific class name. This is still
the same canonical safety ontology; only the spoken surface form changes.

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

## Alert smoothing

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

## Final benchmark summary

### Final offline evidence

Dataset: 500 public images, built from 250 COCO val2017 images and 250 BDD100K
validation images. Labels are group-level (`person`, `vehicle`,
`static_obstacle`) because zone/distance from public dataset boxes is not a
stable proxy for DADN camera calibration.

Run directory: `DADN/experiments/results/20260509-214633/`.

| Experiment | Model | Frames | Alert correctness | Balanced score | p95 latency | Decision |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| `tuned_lite0_int8_high_recall` | EfficientDet-Lite0 int8 | 500 | 0.812 | 0.867 | 31.4 ms | Winner |
| `tuned_lite0_int8_recall` | EfficientDet-Lite0 int8 | 500 | 0.770 | 0.843 | 32.6 ms | Eligible |
| `accuracy_lite2_int8` | EfficientDet-Lite2 int8 | 500 | 0.842 | 0.833 | 84.7 ms | Eligible but slower |
| `balanced_lite0_int8` | EfficientDet-Lite0 int8 | 500 | 0.738 | 0.823 | 34.2 ms | Below correctness gate |
| `fast_ssd_mobilenet_v2_float16` | SSD MobileNetV2 float16 | 500 | 0.732 | 0.820 | 30.7 ms | Below correctness gate |
| `sanity_lite0_float32` | EfficientDet-Lite0 float32 | 500 | 0.726 | 0.806 | 44.5 ms | Below correctness gate |

The winner policy selected the tuned Lite0 int8 config because it passed
`alert_correctness >= 0.75`, had the best balanced score, and was much faster
than Lite2 while only slightly lower in correctness.

### Edge-focused rerun

Full official MediaPipe sweep run directory:
`DADN/experiments/results/20260509-225934/`.

| Experiment | Artifact | Size | Correctness | Avg | p95 | Edge note |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| `tuned_lite0_int8_high_recall` | Lite0 int8 | 4.6 MB | 0.812 | 28.8 ms | 33.9 ms | Winner |
| `tuned_lite0_int8_recall` | Lite0 int8 | 4.6 MB | 0.770 | 31.7 ms | 36.9 ms | Eligible |
| `balanced_lite0_int8` | Lite0 int8 | 4.6 MB | 0.738 | 31.5 ms | 38.1 ms | Below correctness gate |
| `fast_ssd_mobilenet_v2_float32` | SSD MobileNetV2 float32 | 11.3 MB | 0.734 | 32.5 ms | 37.0 ms | Fast but below gate |
| `fast_ssd_mobilenet_v2_float16` | SSD MobileNetV2 float16 | 5.9 MB | 0.732 | 34.3 ms | 38.6 ms | Smaller than SSD float32, below gate |
| `sanity_lite0_float32` | Lite0 float32 | 13.8 MB | 0.726 | 40.4 ms | 47.6 ms | Larger/slower |
| `sanity_lite0_float16` | Lite0 float16 | 7.3 MB | 0.726 | 40.3 ms | 49.5 ms | Larger/slower than int8 |
| `accuracy_lite2_int8` | Lite2 int8 | 7.5 MB | 0.842 | 76.7 ms | 93.9 ms | More accurate, too slow for latency-first edge |
| `accuracy_lite2_float32` | Lite2 float32 | 23.1 MB | 0.848 | 126.6 ms | 152.7 ms | Highest correctness, too large/slow |
| `accuracy_lite2_float16` | Lite2 float16 | 12.1 MB | 0.848 | 126.9 ms | 153.4 ms | Highest correctness, too slow |

This sweep covers the official MediaPipe object detector artifacts that are
runnable with the current `ObstacleDetector` pipeline: EfficientDet-Lite0
int8/float16/float32, EfficientDet-Lite2 int8/float16/float32, and SSD
MobileNetV2 float16/float32. MediaPipe documentation lists SSD MobileNetV2 as
the speed-oriented family, but the downloadable artifacts did not beat tuned
Lite0 int8 on this offline pipeline. A separate SSD MobileNetV2 int8 path was
checked, but `/ssd_mobilenet_v2/int8/latest/ssd_mobilenet_v2.tflite` returned
404, so it was not kept as a runnable repo candidate.

## Reproducible commands

Run a report-ready benchmark on an existing labeled public subset:

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

## What the report should say

Use these claims in the formal report:

- The project is tuned for obstacle warning, so `risk_alert_correctness` is the
  primary safety metric.
- Public COCO/BDD results are offline validation only. If the dataset is not
  representative enough for the deployment target, do not use it as the final
  selection gate.
- The tuned winner is EfficientDet-Lite0 int8 with `score_threshold = 0.35`
  and `max_results = 15`.
- Geometry-based Decision Engine thresholds are heuristic because there is no
  depth sensor; they were validated by benchmark and demo observations.
- Runtime settings are chosen to keep the stream responsive, but final FPS and
  latency must be reported from the actual demo hardware.
- The dashboard TTS is a demo convenience and may depend on the browser or
  network if `gTTS` is used.

## What the report should not claim

- Do not claim the public benchmark is i.i.d. with the ESP32-CAM stream.
- Do not call server-side alert latency "full end-to-end latency" unless the
  report explicitly measures camera-to-user audio timing.
- Do not claim the Decision Engine thresholds are physically calibrated
  distances; they are geometry heuristics.
- Do not describe the tuning as an ML adapter or LoRA workflow; it is
  configuration tuning plus post-processing.
