# DADN - Real-time Obstacle Detection Server

Python server for receiving ESP32-CAM MJPEG stream and running real-time object detection.

## Features
- MJPEG stream ingest from ESP32-CAM
- Real-time detection with EfficientDet Lite0 (MediaPipe)
- Obstacle prioritization (distance, zone, class weight)
- Web dashboard with live stats and alerts

## Folder Structure
- `stream_server.py`: main Flask streaming + detection server
- `run_stream_server.py`: convenient launcher script
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
Start server with explicit ESP32 stream URL:

```bash
python run_stream_server.py --esp32-url http://<ESP32_IP>:8081/stream
```

Then open:
- `http://localhost:5000`

## Notes
- Do not hardcode personal WiFi/IP in code before pushing to GitHub.
- Model file is ignored by `.gitignore` and downloaded/managed separately.
