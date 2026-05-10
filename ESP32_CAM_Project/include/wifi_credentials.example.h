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
