# ESP32_CAM_Project

PlatformIO firmware project for AI Thinker ESP32-CAM.

## Features
- MJPEG stream endpoint: `/stream` on port `8081`
- Basic board status page at `/`
- Periodic health ping to Python server

## Configuration
Edit WiFi and server IP placeholders in:
- `src/main.cpp`

```cpp
{"YOUR_WIFI_SSID", "YOUR_WIFI_PASSWORD"}
static const char* SERVER_IP = "192.168.1.100";
```

## Build and Upload (PlatformIO)
From this folder:

```bash
platformio run
platformio run --target upload
platformio device monitor
```

If your COM port is unstable, set fixed ports in `platformio.ini`:

```ini
upload_port = COM7
monitor_port = COM7
```

## Board
- Board: `esp32cam` (AI Thinker ESP32-CAM)
- Framework: Arduino
