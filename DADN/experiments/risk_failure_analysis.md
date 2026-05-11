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
