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
