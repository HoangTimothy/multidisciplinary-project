# DADN - Real-time Obstacle Detection Server

Python server for receiving an ESP32-CAM MJPEG stream and running real-time object detection.

## Features
- MJPEG stream ingest from ESP32-CAM local URL or ngrok URL
- Real-time detection with EfficientDet Lite0 (MediaPipe)
- Obstacle prioritization (distance, zone, class weight)
- Web dashboard with live stats and alerts

## Folder Structure
- `stream_server.py`: main Flask streaming + detection server
- `run_stream_server.py`: convenient launcher script
- `expose_dashboard_ngrok.py`: Raspberry Pi launcher for public demo dashboard
- `detector.py`: MediaPipe detector wrapper
- `decision_engine.py`: obstacle scoring and alert logic
- `config.py`: thresholds and model/runtime settings
- `templates/stream.html`: web UI

## Requirements
- Python 3.9+
- Dependencies in `requirements_api.txt`

Install:

```bash
pip install -r requirements_api.txt
```

## Run
Start server with an explicit camera stream URL:

```bash
python run_stream_server.py --camera-url http://<CAMERA_HOST>:8081/stream
```

Then open:
- `http://localhost:5000`

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
- Model file is ignored by `.gitignore` and downloaded/managed separately.
