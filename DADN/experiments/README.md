# DADN Experiments

This folder contains reproducible benchmark inputs for model and hyperparameter
tuning. Keep large datasets and generated benchmark outputs outside Git.

## Candidate datasets

Start with datasets that include pedestrian-facing safety classes:

- COCO validation images: broad sanity check for `person`, vehicles, chairs,
  benches, bags, and other COCO classes used by MediaPipe models.
  Source: https://cocodataset.org/
- BDD100K or similar road-scene samples: useful for vehicles, motorcycles,
  pedestrians, traffic lights, and outdoor scenes.
  Source: https://bdd-data.berkeley.edu/
- Open Images subset: useful when filtering many object categories such as
  people, bags, furniture, bicycles, and vehicles.
  Source: https://storage.googleapis.com/openimages/web/index.html
- A small DADN demo set: 5-10 short videos from laptop/ESP32 in corridors,
  campus walkways, sidewalks, and indoor obstacle scenes.

Model candidates are from the MediaPipe Object Detector task guide:
https://ai.google.dev/edge/mediapipe/solutions/vision/object_detector

The open datasets are useful for model sanity. For a production handoff, keep
the raw COCO/BDD images outside Git, generate a small labeled subset locally,
and commit only the final benchmark summary.

## Collision-risk robustness subset

For DADN, the main production question is whether a risky obstacle triggers an
alert, not whether the object name is perfect. Build a synthetic robustness set
from the labeled public subset to stress ESP32-like conditions:

```bash
python DADN/experiments/prepare_robustness_subset.py \
  --input /data/dadn-public-subset/images \
  --labels /data/dadn-public-subset/labels.json \
  --output /data/dadn-robustness/images \
  --labels-out /data/dadn-robustness/labels.json \
  --max-images 50
```

This generates motion blur, noise, low-light, JPEG-compressed, center-occluded,
and ESP32-resized variants. Use `risk_alert_correctness` as the primary metric;
`alert_correctness` remains the stricter group/zone/distance diagnostic.

For real ESP32-CAM review frames, use
`DADN/experiments/capture_real_camera_frames.py` and keep the raw frames outside
Git.

## Prepare a COCO + BDD subset

BDD100K normally requires downloading the dataset through its official access
flow, so this repository does not auto-download the official release. The final
laptop run used COCO val2017 annotations plus a BDD100K FiftyOne `samples.json`
mirror. Generate a reproducible 200-500 item subset with:

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

The helper selects labels relevant to DADN (`person`, vehicles, and static
obstacles). By default it emits group-level labels, which are the right choice
for public COCO/BDD model selection; use `--label-detail all` only for
diagnostic runs where approximate zone/distance labels are useful.

## Minimal labels format

`benchmark_inference.py` can run without labels and will still measure latency
and detection/alert rates. For alert correctness, add a JSON file:

```json
{
  "items": {
    "corridor_person.jpg": {
      "expected_alert": true,
      "expected_group": "person",
      "expected_zone": "giữa",
      "expected_distance": "gần"
    },
    "campus_walk.mp4#frame=120": {
      "expected_alert": true,
      "expected_group": "vehicle",
      "expected_zone": "bên phải",
      "expected_distance": "trung bình"
    }
  }
}
```

Allowed `expected_group` values are `person`, `vehicle`, and
`static_obstacle`. Leave fields out when they are unknown; the benchmark only
scores fields that are present.

## Example

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
  --sample-every 15 \
  --max-frames-per-video 120 \
  --min-frames 200 \
  --min-labeled-frames 200 \
  --min-alert-correctness 0.75
```

Generated results are written to `DADN/experiments/results/<timestamp>/`.
The winner rule keeps only configs with enough labeled evidence and
risk/alert correctness >= `0.75`; if scores are within `0.03`, the lower p95
latency candidate wins. If no config passes, keep `efficientdet_lite0_int8`.

See `final_benchmark_summary.md` for the current repo conclusion and
`risk_failure_analysis.md` for the collision-risk failure-analysis workflow.

## Raspberry Pi handoff

Use `DADN/run_pi_edge_tests.py` on the Raspberry Pi to bundle preflight, model
inventory, optional offline benchmark, and optional live `/api/stats` benchmark
into one ignored results folder. For runtime sweeps, restart the server with
`DADN_INFER_EVERY_N_FRAMES=3`, `5`, `7`, or `10` and compare
`stream_summary.json`.
