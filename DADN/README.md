# DADN - Real-time Obstacle Detection Server

Python server for receiving an ESP32-CAM MJPEG stream and running real-time object detection.

## Features
- MJPEG stream ingest from ESP32-CAM local URL or ngrok URL
- Real-time detection with EfficientDet Lite0 (MediaPipe)
- Collision-risk-first alerts (distance, zone, box geometry, confidence, class as secondary)
- Lightweight denoise/low-light preprocessing and temporal alert smoothing
- Web dashboard with live stats and alerts
- Smooth video path: capture/video streaming is decoupled from model inference
- Vietnamese TTS alerts via Google TTS with browser speech fallback
- Production WSGI serving with Waitress
- Offline benchmark runner for model/hyperparameter tuning

## Folder Structure
- `stream_server.py`: main Flask streaming + detection server
- `run_stream_server.py`: convenient launcher script
- `benchmark_inference.py`: offline benchmark runner for image/video datasets
- `benchmark_stream.py`: polls a running dashboard for FPS/latency/drop metrics
- `record_metrics.py`: report-ready wrapper for offline correctness and runtime metrics
- `expose_dashboard_ngrok.py`: Raspberry Pi launcher for public demo dashboard
- `detector.py`: MediaPipe detector wrapper
- `decision_engine.py`: obstacle scoring and alert logic
- `model_registry.py`: official MediaPipe model candidates used by experiments
- `experiments/`: benchmark configs, dataset notes, and ignored result outputs
- `config.py`: thresholds and model/runtime settings
- `templates/stream.html`: web UI with Vietnamese TTS alerts
- `tts_engine.py`: text-to-speech engine used by `main.py`

## Requirements
- Python 3.9+
- Dependencies in `requirements.txt`

Install:

```bash
pip install -r requirements.txt
```

## Run
Start server with an explicit camera stream URL:

```bash
python run_stream_server.py --camera-url http://<CAMERA_HOST>:8081/stream
```

Then open:
- `http://localhost:5000`

## Benchmark model and hyperparameters

Run offline benchmarks against an image/video folder:

```bash
python benchmark_inference.py \
  --dataset /path/to/dataset \
  --labels /path/to/labels.json \
  --config experiments/configs/balanced_lite0_int8.json \
  --config experiments/configs/tuned_lite0_int8_recall.json \
  --config experiments/configs/tuned_lite0_int8_high_recall.json \
  --config experiments/configs/fast_ssd_mobilenet_v2_float16.json \
  --config experiments/configs/accuracy_lite2_int8.json \
  --config experiments/configs/sanity_lite0_float32.json \
  --min-frames 200 \
  --min-labeled-frames 200 \
  --min-alert-correctness 0.75
```

Labels are required for a defensible model choice. Without matching labels,
the runner reports `alert_correctness: null` and `risk_alert_correctness: null`,
marks every config ineligible, and falls back to the current default model.

Outputs are written to `experiments/results/<timestamp>/` and ignored by Git.
See `experiments/README.md` for dataset guidance and
`experiments/tuning_methodology.md` for the tuning protocol. See
`experiments/final_benchmark_summary.md` for the current repo conclusion.
For a single merged handoff brief that combines both tuning methodology and
final benchmark evidence, read `experiments/report_handoff.md`.
For robustness/failure analysis, see `experiments/risk_failure_analysis.md`.
Use `--dry-run` to validate configs/dataset/output plumbing without loading
MediaPipe models.

Dataset-prep helpers such as `prepare_public_subset.py`,
`prepare_robustness_subset.py`, `prepare_external_subset.py`, and
`capture_real_camera_frames.py` are kept as support scripts. They are not part
of the main measurement flow.

Current tuned benchmark winner: EfficientDet Lite0 int8 with
`SCORE_THRESHOLD = 0.35` and `MAX_RESULTS = 15`.
The current production candidate also enables inference preprocessing and keeps
short-lived alerts through brief detector misses for noisy/occluded streams.

When the dashboard is running, collect stream metrics with:

```bash
python benchmark_stream.py --server-url http://127.0.0.1:5000 --duration 60
```

To produce report-ready metrics in one run, keep the dashboard server running
and run:

```bash
python benchmark/record_metrics.py \
  --dataset /data/dadn-public-subset/images \
  --labels /data/dadn-public-subset/labels.json \
  --server-url http://127.0.0.1:5000 \
  --runs 3 \
  --warmup 10 \
  --duration 60 \
  --interval 1
```

The wrapper writes `metrics_summary.json` and `metrics_summary.md` under
`experiments/results/<timestamp>-record-metrics/`. Latency is reported as
`server_side_alert_latency_ms`, not full camera-to-audio end-to-end latency.

To run the detector/config sweep and keep the dataset/config/result trace
together:

```bash
python experiments/run_tuning_sweep.py \
  --dataset /data/dadn-public-subset/images \
  --labels /data/dadn-public-subset/labels.json \
  --min-frames 200 \
  --min-labeled-frames 200
```

For ESP32-CAM capture-resolution reporting, use
`benchmark/esp32_resolution_sweep.py` to flash QVGA/VGA/SVGA/XGA/SXGA/UXGA
presets and record runtime metrics on the real Raspberry Pi pipeline.

Use public datasets as offline validation only; final claims should also include
synthetic robustness and real ESP32-CAM review frames because public images are
not i.i.d. with the live camera stream.

## Raspberry Pi edge test suite

On the Raspberry Pi, first install dependencies and pre-download the edge models:

```bash
pip install -r requirements.txt
python run_pi_edge_tests.py --download-models
```

Run an offline benchmark if the COCO+BDD subset has been copied to the Pi:

```bash
python run_pi_edge_tests.py \
  --dataset /data/dadn-public-subset/images \
  --labels /data/dadn-public-subset/labels.json \
  --download-models
```

Run the live stream server and runtime benchmark:

```bash
DADN_INFER_EVERY_N_FRAMES=5 DADN_JPEG_QUALITY=60 \
python run_stream_server.py --camera-url http://<CAMERA_HOST>:8081/stream --no-browser

python run_pi_edge_tests.py --server-url http://127.0.0.1:5000 --stream-duration 120
```

To compare runtime load without editing code, restart the server with
`DADN_INFER_EVERY_N_FRAMES=3`, `5`, `7`, or `10`. Results are written under
`experiments/results/<timestamp>-pi-edge-suite/` and ignored by Git.

## Public demo dashboard from Raspberry Pi

`DADN` already serves a Flask web dashboard at `/`, with processed video at
`/video_feed` and stats at `/api/stats`. On Raspberry Pi, expose that dashboard
through ngrok with:

```bash
ngrok config add-authtoken <YOUR_NGROK_TOKEN>
python expose_dashboard_ngrok.py --camera-url https://xxxx.ngrok-free.app/stream
```

The script starts `run_stream_server.py`, waits for `http://127.0.0.1:5000`,
opens ngrok for port `5000`, writes the public dashboard URL to
`.dadn-dashboard-url`, and prints the URL for the demo.

If the DADN server is already running:

```bash
python expose_dashboard_ngrok.py --no-server --port 5000
```

If the model download/load is slow on Raspberry Pi, increase startup wait time:

```bash
python expose_dashboard_ngrok.py --camera-url https://xxxx.ngrok-free.app/stream --startup-timeout 300
```

## ESP32-CAM on this machine -> ngrok -> Raspberry Pi DADN

Flash/run the ESP32-CAM firmware first, then read its local stream URL from
Serial Monitor. It should look like:

```bash
http://192.168.1.50:8081/stream
```

On the computer that can open that ESP32-CAM URL:

```bash
cd ../ESP32_CAM_Project
ngrok config add-authtoken <YOUR_NGROK_TOKEN>
python expose_esp32_ngrok.py --esp32-url http://192.168.1.50:8081/stream
```

The script exposes the ESP32-CAM stream through ngrok and prints a public URL
ending in `/stream`.

Then run this on the Raspberry Pi, where the model/inference lives:

```bash
python run_stream_server.py --camera-url https://xxxx.ngrok-free.app/stream
```

You can also provide only the ngrok base URL; the launcher appends `/stream`:

```bash
python run_stream_server.py --camera-url https://xxxx.ngrok-free.app
```

Accepted alternatives:

```bash
CAMERA_STREAM_URL=https://xxxx.ngrok-free.app/stream python run_stream_server.py
CAMERA_NGROK_URL=https://xxxx.ngrok-free.app python run_stream_server.py
python run_stream_server.py --camera-url-file .camera-ngrok-url
```

## Notes
- Do not hardcode personal WiFi/IP in code before pushing to GitHub.
- The default model is tuned EfficientDet Lite0 int8 for lower latency on Raspberry Pi.
- Model file is ignored by `.gitignore` and downloaded/managed separately.
