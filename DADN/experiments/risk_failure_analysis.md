# DADN Collision-Risk Failure Analysis

## Current decision

DADN now treats collision risk as the primary signal. Object names are secondary:
if a detected box is large, low in the frame, centered enough, and confident
enough, the system may alert as `vật cản` even when the COCO class name is not a
useful obstacle label.

This is the right default for the current edge target because EfficientDet-Lite0
int8 is fast enough for Raspberry Pi-class testing, while COCO labels do not
cover many real indoor obstacles such as fans or partially visible furniture.

## Failure categories to track

| Category | Meaning | Next action |
| --- | --- | --- |
| Missed obstacle | No alert for a physically risky object | Tune risk thresholds; consider segmentation/fine-tune if repeated |
| Wrong label, acceptable alert | Alert fires but object name is wrong | Keep pretrained model; speak `vật cản` for generic risk |
| False alert | Alert fires for non-risky object/background | Raise generic risk thresholds or tighten center/lower-zone rules |
| Stream instability | Frames freeze, lag, or reconnect often | Tune ESP32 stream/network path before model changes |
| Low-light/noise failure | Object disappears under camera artifacts | Validate with synthetic robustness and real ESP32 frames |

## Robustness benchmark

Create synthetic stress cases from an existing labeled image subset:

```bash
python DADN/experiments/prepare_robustness_subset.py \
  --input /data/dadn-public-subset/images \
  --labels /data/dadn-public-subset/labels.json \
  --output /data/dadn-robustness/images \
  --labels-out /data/dadn-robustness/labels.json \
  --max-images 50
```

Run the benchmark against the same production candidate:

```bash
python DADN/benchmark_inference.py \
  --dataset /data/dadn-robustness/images \
  --labels /data/dadn-robustness/labels.json \
  --config DADN/experiments/configs/tuned_lite0_int8_high_recall.json \
  --min-frames 200 \
  --min-labeled-frames 200 \
  --min-alert-correctness 0.75
```

Use `risk_alert_correctness` as the primary metric. Use
`alert_correctness` only as the stricter group/zone/distance diagnostic.

## Real camera review set

Capture a small review set from the ESP32-CAM local stream:

```bash
python DADN/experiments/capture_real_camera_frames.py \
  --camera-url http://192.168.1.11:8081/stream \
  --output /data/dadn-real-camera/images \
  --labels-out /data/dadn-real-camera/labels.json \
  --frames 60 \
  --interval-seconds 0.5 \
  --expected-alert \
  --failure-type real_camera_occlusion_noise
```

Review/edit the generated labels before using them as final evidence. Do not
commit raw private frames; commit only the summarized failure analysis.

## Fine-tune gate

Do not fine-tune just because the label is wrong. Fine-tuning becomes justified
only if the robustness or real ESP32 frame set shows repeated missed obstacles
after risk thresholds and camera quality have been tuned.

## Synthetic robustness run: 2026-05-11

Generated 3,000 robustness images from the 500-image public DADN subset:

- Source: `/mnt/d/datasets/dadn_public/subset/images`
- Labels: `/mnt/d/datasets/dadn_public/subset/labels_group.json`
- Synthetic output: `/mnt/d/datasets/dadn_public/robustness_20260511-181506`
- Benchmark summary: `DADN/experiments/results/20260511-181637/summary.json`

Candidate tested: `tuned_lite0_int8_high_recall` using EfficientDet-Lite0 int8.

| Variant | Frames | Risk correctness | Strict group correctness | Detection rate | Alert rate |
| --- | ---: | ---: | ---: | ---: | ---: |
| `center_occlusion` | 500 | 0.740 | 0.630 | 0.846 | 0.740 |
| `esp32_resize` | 500 | 0.828 | 0.696 | 0.872 | 0.828 |
| `jpeg_low_quality` | 500 | 0.832 | 0.722 | 0.884 | 0.832 |
| `low_light` | 500 | 0.804 | 0.694 | 0.864 | 0.804 |
| `motion_blur` | 500 | 0.830 | 0.712 | 0.896 | 0.830 |
| `noise` | 500 | 0.766 | 0.658 | 0.846 | 0.766 |

Overall:

- `risk_alert_correctness`: 0.800
- `alert_correctness`: 0.685
- `detection_rate`: 0.868
- `alert_rate`: 0.800
- `false_alert_rate`: 0.000 on this positive-only robustness set
- `p95_latency_ms`: 35.4 ms on laptop

Interpretation:

- The risk-first logic is useful: risk correctness is much higher than strict
  group correctness, so alerting as `vật cản` is safer than trusting the class
  name.
- The weakest synthetic cases are center occlusion and noise, which matches the
  real ESP32-CAM concerns: partial objects and noisy frames.
- The main remaining failure type is missed detections, not just wrong labels.
  Fine-tuning or segmentation becomes worth considering only if the same missed
  obstacle pattern appears in the real ESP32 review set.

## Alert-recall tuning run: 2026-05-11

Tuned the production candidate for higher alert recall:

- `SCORE_THRESHOLD`: 0.40 -> 0.35
- `MAX_RESULTS`: 10 -> 15
- `GENERIC_RISK_MIN_AREA_RATIO`: 0.10 -> 0.08
- `GENERIC_RISK_MIN_CENTER_AREA_RATIO`: 0.06 -> 0.045
- `GENERIC_RISK_PRIORITY_THRESHOLD`: 0.55 -> 0.48

Benchmark summary: `DADN/experiments/results/20260511-214131/summary.json`.

| Variant | Risk correctness | Strict group correctness | Detection rate | Alert rate |
| --- | ---: | ---: | ---: | ---: |
| `center_occlusion` | 0.770 | 0.636 | 0.884 | 0.770 |
| `esp32_resize` | 0.840 | 0.708 | 0.910 | 0.840 |
| `jpeg_low_quality` | 0.850 | 0.726 | 0.910 | 0.850 |
| `low_light` | 0.816 | 0.698 | 0.898 | 0.816 |
| `motion_blur` | 0.848 | 0.726 | 0.926 | 0.848 |
| `noise` | 0.774 | 0.660 | 0.878 | 0.774 |

Overall after tuning:

- `risk_alert_correctness`: 0.816, up from 0.800
- `alert_correctness`: 0.692, up from 0.685
- `detection_rate`: 0.901, up from 0.868
- `alert_rate`: 0.816, up from 0.800
- `p95_latency_ms`: 33.2 ms on laptop

This tune is worth keeping for the laptop/edge candidate because it improves
missed-alert robustness without increasing measured p95 latency on the synthetic
set. The remaining weakest cases are still center occlusion and noise.

## Preprocessing and temporal smoothing run: 2026-05-11

Added lightweight inference preprocessing and temporal alert smoothing:

- Median denoise before inference.
- CLAHE low-light enhancement when luminance is low.
- Hold the latest alert for up to 2 inference frames or 0.8 seconds when a
  short detector miss occurs.

Benchmark summary: `DADN/experiments/results/20260511-215104/summary.json`.

| Variant | Risk correctness | Strict group correctness | Detection rate | Alert rate |
| --- | ---: | ---: | ---: | ---: |
| `center_occlusion` | 0.756 | 0.638 | 0.868 | 0.756 |
| `esp32_resize` | 0.846 | 0.716 | 0.926 | 0.846 |
| `jpeg_low_quality` | 0.840 | 0.724 | 0.916 | 0.840 |
| `low_light` | 0.838 | 0.712 | 0.912 | 0.838 |
| `motion_blur` | 0.858 | 0.734 | 0.926 | 0.858 |
| `noise` | 0.826 | 0.688 | 0.920 | 0.826 |

Overall after preprocessing/smoothing:

- `risk_alert_correctness`: 0.827, up from 0.816 after threshold tuning
- `alert_correctness`: 0.702, up from 0.692
- `detection_rate`: 0.911, up from 0.901
- `p95_latency_ms`: 35.6 ms on laptop

The synthetic image benchmark mainly measures preprocessing because frames are
independent still images; temporal smoothing should be validated on a real
ESP32 stream where short detector misses happen across adjacent frames. Noise
improved the most (`0.774 -> 0.826`). Center occlusion remains weak
(`0.770 -> 0.756`), so partial-object failure is still the strongest argument
for a real-camera failure set and, if confirmed, fine-tuning or segmentation.

## Hard-only benchmark: occlusion + motion blur

The 3,000-image robustness set includes easier variants, so a hard-only set was
created from just `center_occlusion` and `motion_blur`:

- Hard set: `/mnt/d/datasets/dadn_public/robustness_hard_occlusion_motion_20260511`
- Frames: 1,000 total, 500 per hard variant
- Current candidate summary: `DADN/experiments/results/20260511-220254/summary.json`
- Probe summary: `DADN/experiments/results/20260511-220458/summary.json`

| Config | Risk correctness | Group correctness | Detection rate | p95 latency | Edge note |
| --- | ---: | ---: | ---: | ---: | --- |
| Current Lite0 recall | 0.807 | 0.686 | 0.897 | 34.7 ms | Current production candidate |
| `hard_recall_lite0_int8` | 0.842 | 0.705 | 0.946 | 34.3 ms | Best Lite0 hard-case recall probe |
| Lite2 int8 hard probe | 0.870 | 0.747 | 0.932 | 80.5 ms | Better, but much slower |

Hard-case detail for `hard_recall_lite0_int8`:

| Variant | Risk correctness | Group correctness | Detection rate | Alert rate |
| --- | ---: | ---: | ---: | ---: |
| `center_occlusion` | 0.806 | 0.658 | 0.926 | 0.806 |
| `motion_blur` | 0.878 | 0.752 | 0.966 | 0.878 |

Interpretation:

- Removing easy samples makes the weakness visible: current Lite0 drops to
  0.756 on occlusion and 0.858 on motion blur.
- Aggressive Lite0 tuning improves both hard cases without a laptop latency
  penalty, but this hard-only set is positive-only, so it cannot measure false
  alert spam.
- Lite2 int8 is the best accuracy probe, especially for occlusion, but its p95
  latency is over 2x Lite0 on laptop, so it should not replace Lite0 for the
  edge candidate unless Raspberry Pi tests show enough headroom.
- If real ESP32 negative/non-obstacle frames show acceptable spam, promote
  `hard_recall_lite0_int8`; otherwise keep it as a hard-case diagnostic config.

## External dataset triage: 2026-05-11

Three assistive/navigation-oriented datasets were checked for DADN integration:

| Dataset | Status | Use in DADN |
| --- | --- | --- |
| Zenodo `10781048` wearable obstacle benchmark | Direct download works; MIT license; sensor CSV, not images | Use as collision-risk/time-series evidence, not MediaPipe image benchmark |
| GuideDog | Hugging Face gated; access is auto-approved after accepting terms; image + bbox fields available in `object`/`depth` configs | Use for egocentric BLV street-view risk benchmark after HF login |
| HRBUST-LLPED | Good low-light wearable pedestrian candidate; stable direct download/schema not wired yet | Use later for low-light pedestrian robustness when files are available |

Implemented `DADN/experiments/prepare_external_subset.py`:

- `zenodo-sensor` downloads/summarizes Zenodo sensor CSV into a DADN-style
  risk manifest.
- `guidedog` prepares GuideDog image subsets for `benchmark_inference.py` after
  Hugging Face authentication and dataset terms acceptance.

Smoke result for Zenodo Corridor:

- Command prepared 500 rows from `Corridor_marked.csv`.
- Label counts: 363 no-alert rows, 137 alert rows.
- Output manifest:
  `/mnt/d/datasets/dadn_external/zenodo_10781048/corridor_sensor_manifest.json`.
