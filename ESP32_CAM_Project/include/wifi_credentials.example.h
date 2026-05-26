#pragma once

// Copy this file to include/wifi_credentials.h, then edit the values.
// The real wifi_credentials.h file is gitignored so WiFi passwords stay local.

#define DADN_WIFI_CANDIDATES { \
  {"YOUR_WIFI_SSID", "YOUR_WIFI_PASSWORD"} \
}

#define DADN_SERVER_IP "192.168.1.100"

// Keep disabled for camera-stream-only demos. Enable only when a local DADN API
// server is running and reachable from the ESP32-CAM.
#define DADN_ENABLE_SERVER_HEALTH_CHECK 0

// Camera orientation. Try vflip=1 if the camera is physically upside down.
#define DADN_CAMERA_VFLIP 0
#define DADN_CAMERA_HMIRROR 0

// Capture resolution. Current firmware default is QVGA, but the camera
// hardware supports higher modes such as VGA, SVGA, XGA, SXGA, and UXGA.
#define DADN_CAMERA_FRAME_SIZE FRAMESIZE_QVGA

// Long enough for demos, finite so stale ngrok/browser clients are released.
// Use 0 only if you are sure clients disconnect cleanly.
#define DADN_STREAM_TIMEOUT_MS 300000

// ESP32 camera JPEG quality: higher means smaller/lower quality.
#define DADN_JPEG_QUALITY 24

// Lower delay reduces visual latency but raises WiFi/CPU load.
#define DADN_FRAME_DELAY_MS 15
