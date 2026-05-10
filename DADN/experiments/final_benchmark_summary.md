# DADN Model Benchmark Summary

## Current conclusion

The laptop-first public benchmark now passes the evidence gate. The selected
production candidate is `tuned_lite0_int8_high_recall`: EfficientDet-Lite0 int8
with `score_threshold = 0.4` and `max_results = 10`.

This keeps the Raspberry Pi-friendly int8 model while improving group-level
alert correctness on the COCO + BDD subset.

## Winner policy

- Require at least 200 benchmarked frames/images.
- Require at least 200 labeled frames/images.
- Require `alert_correctness >= 0.75`.
- Among eligible configs, select the best `balanced_score`.
- If the best scores are within `0.03`, select the lower `p95_latency_ms`.
- If no config is eligible, keep `efficientdet_lite0_int8`.

## Final laptop evidence

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

## Edge-focused rerun

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
Lite0 int8 on this laptop pipeline. A separate SSD MobileNetV2 int8 path was
checked, but `/ssd_mobilenet_v2/int8/latest/ssd_mobilenet_v2.tflite` returned
404, so it was not kept as a runnable repo candidate.

## Reproducible final benchmark command

Prepare the public subset. The run above used COCO val2017 annotations and a
BDD100K FiftyOne `samples.json` mirror from Hugging Face:

```bash
python DADN/experiments/prepare_public_subset.py \
  --coco-annotations /data/coco/annotations/instances_val2017.json \
  --bdd-fiftyone-samples /data/bdd100k/samples.json \
  --bdd-hf-repo dgural/bdd100k \
  --output-dir /data/dadn-public-subset/images \
  --labels-out /data/dadn-public-subset/labels.json \
  --max-coco 250 \
  --max-bdd 250 \
  --label-detail group
```

Run all current candidates:

```bash
python DADN/benchmark_inference.py \
  --dataset /data/dadn-public-subset/images \
  --labels /data/dadn-public-subset/labels.json \
  --config DADN/experiments/configs/balanced_lite0_int8.json \
  --config DADN/experiments/configs/tuned_lite0_int8_recall.json \
  --config DADN/experiments/configs/tuned_lite0_int8_high_recall.json \
  --config DADN/experiments/configs/fast_ssd_mobilenet_v2_float16.json \
  --config DADN/experiments/configs/accuracy_lite2_int8.json \
  --config DADN/experiments/configs/sanity_lite0_float32.json \
  --min-frames 200 \
  --min-labeled-frames 200 \
  --min-alert-correctness 0.75
```

The raw `experiments/results/<timestamp>/summary.json` contains the selected
winner, eligibility flags, label coverage, unmatched label count, latency, and
balanced score for every config.

## Production handoff note

This conclusion is laptop-first. Before calling the config final for production
hardware, run `benchmark_stream.py` on the Raspberry Pi/ESP32-CAM demo for FPS,
reconnect stability, and end-to-end alert timing.
