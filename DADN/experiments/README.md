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
- A small DADN demo set: 5-10 short videos from a local camera/ESP32 in corridors,
  campus walkways, sidewalks, and indoor obstacle scenes.

Model candidates are from the MediaPipe Object Detector task guide:
https://ai.google.dev/edge/mediapipe/solutions/vision/object_detector

See `tuning_methodology.md` for the full detector/runtime/Decision Engine
tuning protocol and the distinction between benchmark-driven and heuristic
parameters.
If you need one consolidated file to hand to another agent or to turn into the
formal report, read `report_handoff.md`.

The open datasets are useful for model sanity. For a production handoff, keep
the raw COCO/BDD images outside Git, generate a small labeled subset locally,
and commit only the final benchmark summary.

## Collision-risk robustness subset

For DADN, the main production question is whether a risky obstacle triggers an
alert, not whether the object name is perfect. A synthetic robustness set can
be derived from an existing labeled public subset with the support script
`prepare_robustness_subset.py`. The important measurement step is still
`benchmark_inference.py` on the resulting dataset.

This generates motion blur, noise, low-light, JPEG-compressed, center-occluded,
and ESP32-resized variants. Use `risk_alert_correctness` as the primary metric;
`alert_correctness` remains the stricter group/zone/distance diagnostic.

For real ESP32-CAM review frames, use
`DADN/experiments/capture_real_camera_frames.py` and keep the raw frames outside
Git.

## External assistive datasets

`prepare_external_subset.py` adds adapters for datasets closer to assistive
navigation than generic COCO/BDD.

Zenodo `10781048` is directly downloadable, but it is a sensor-only ultrasonic
and IMU benchmark rather than camera frames. Use it as collision-risk
evidence, not as input for `benchmark_inference.py`.

GuideDog is useful for egocentric BLV street-view evaluation. It is gated on
Hugging Face, with auto-approved academic/non-commercial access. After accepting
the terms and running `huggingface-cli login`, the support adapter
`prepare_external_subset.py` can build an image subset.

HRBUST-LLPED is a good low-light wearable pedestrian candidate, but it is not
yet wired into this repo because a stable direct download/schema was not found
from the paper page. Add it through the same adapter style once the dataset
files are available locally.

## Dataset Prep

`prepare_public_subset.py`, `prepare_robustness_subset.py`,
`prepare_external_subset.py`, and `capture_real_camera_frames.py` are support
scripts for one-time dataset construction and review labeling. They are kept in
the repo for reproducibility, but they are not measurement entrypoints. The
main measurement scripts are `benchmark_inference.py`, `benchmark_stream.py`,
`record_metrics.py`, and `run_tuning_sweep.py`.

When you report results, describe the dataset source and the measurement script
separately. The reader should be able to tell which part constructs the data
and which part measures the system.

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
The latest Raspberry Pi / ESP32-CAM remote run is recorded in
`remote_benchmark_20260526.md`.

## Raspberry Pi handoff

Use `DADN/run_pi_edge_tests.py` on the Raspberry Pi to bundle preflight, model
inventory, optional offline benchmark, and optional live `/api/stats` benchmark
into one ignored results folder. For runtime sweeps, restart the server with
`DADN_INFER_EVERY_N_FRAMES=3`, `5`, `7`, or `10` and compare
`stream_summary.json`.
