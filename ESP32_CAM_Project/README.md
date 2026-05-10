# ESP32_CAM_Project

PlatformIO firmware project for AI Thinker ESP32-CAM.

## Features
- MJPEG stream endpoint: `/stream` on port `8081`
- Basic board status page at `/`
- Periodic health ping to Python server
- ngrok helper for sending the ESP32-CAM stream to remote DADN inference

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

### Windows/COM13 local setup

On one Windows machine, the ESP32-CAM USB-UART adapter appeared as:

```text
USB-SERIAL CH340 (COM13)
```

`platformio` was not available directly in `PATH`, so PlatformIO was installed
into the existing Windows Python virtual environment:

```bat
D:\DADN\venv\Scripts\python.exe -m pip install platformio
```

Keep `platformio.ini` generic for Git. If your adapter appears as `COM13`, set
the ports locally before uploading:

```ini
upload_port = COM13
monitor_port = COM13
```

Build and upload from Windows:

```bat
cd /d D:\multidisciplinary-project\ESP32_CAM_Project
D:\DADN\venv\Scripts\python.exe -m platformio run
D:\DADN\venv\Scripts\python.exe -m platformio run --target upload
```

Read Serial Monitor manually from PowerShell if needed:

```powershell
$p = New-Object System.IO.Ports.SerialPort "COM13",115200,"None",8,"One"
$p.ReadTimeout = 1000
$p.Open()
while ($true) { try { $p.ReadLine() } catch {} }
```

To reset the ESP32-CAM and catch the boot log, pulse RTS before reading:

```powershell
$p.RtsEnable = $true
Start-Sleep -Milliseconds 150
$p.RtsEnable = $false
```

## Board
- Board: `esp32cam` (AI Thinker ESP32-CAM)
- Framework: Arduino

## Expose ESP32-CAM to Raspberry Pi DADN

Use this when the ESP32-CAM is running here, but Raspberry Pi runs `DADN` and
holds the model.

1. Flash the firmware and get the stream URL from Serial Monitor:

```bash
platformio device monitor
```

Example:

```text
http://192.168.1.50:8081/stream
```

2. On this computer, expose that ESP32-CAM URL through ngrok:

```bash
ngrok config add-authtoken <YOUR_NGROK_TOKEN>
python expose_esp32_ngrok.py --esp32-url http://192.168.1.50:8081/stream
```

Or let the launcher find the ESP32-CAM automatically, even if DHCP changes its IP:

```bash
python auto_camera_ngrok.py
```

One-command setup is available if `ngrok` is not installed yet. It downloads the
ngrok agent into the ignored repo-local `.tools/` folder, configures the token
from `NGROK_AUTHTOKEN`, scans for the ESP32-CAM, starts ngrok, and prints the
public `/stream` URL:

```bash
NGROK_AUTHTOKEN=<YOUR_NGROK_TOKEN> python run_esp32_all.py
```

If LAN scan cannot find the ESP32-CAM, the wrapper automatically falls back to
reading the ESP32 Serial Monitor, parses `Stream URL:
http://<ip>:8081/stream`, validates the stream, and exposes that URL. To force a
specific adapter:

```bash
python run_esp32_all.py --ngrok-token <YOUR_NGROK_TOKEN> --serial-port COM13
```

The wrapper scans common ESP32-CAM stream ports automatically: `8081`, `80`,
`81`, and `8080`. Override that list when needed:

```bash
python run_esp32_all.py --ngrok-token <YOUR_NGROK_TOKEN> --ports 80,8081
```

The auto launcher scans active local networks for an ESP32-CAM on port `8081`,
starts/restarts ngrok, writes the public URL to `.esp32-ngrok-url`, and prints
the Raspberry Pi command.

It keeps watching the ESP32. If DHCP changes the ESP32 IP, it detects the new
stream and restarts the managed ngrok tunnel. If your LAN is larger than `/24`,
pass the subnet explicitly:

```bash
python auto_camera_ngrok.py --subnet 10.130.0.0/16 --max-hosts-per-network 65536
```

For one-shot ESP32 setup that leaves ngrok running in the background:

```bash
python auto_camera_ngrok.py --once
```

For a laptop webcam instead of ESP32-CAM:

```bash
python auto_camera_ngrok.py --source laptop --camera-index 0
```

3. On Raspberry Pi, run `DADN` with the public URL printed by the script:

```bash
cd ../DADN
python run_stream_server.py --camera-url https://xxxx.ngrok-free.app/stream
```
