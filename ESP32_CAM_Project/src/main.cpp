#include <Arduino.h>
#include "esp_camera.h"
#include <WiFi.h>
#include <esp_wifi.h>
#include <WebServer.h>

#if __has_include("wifi_credentials.h")
#include "wifi_credentials.h"
#endif

// AI Thinker ESP32-CAM pin map
#define PWDN_GPIO_NUM 32
#define RESET_GPIO_NUM -1
#define XCLK_GPIO_NUM 0
#define SIOD_GPIO_NUM 26
#define SIOC_GPIO_NUM 27
#define Y9_GPIO_NUM 35
#define Y8_GPIO_NUM 34
#define Y7_GPIO_NUM 39
#define Y6_GPIO_NUM 36
#define Y5_GPIO_NUM 21
#define Y4_GPIO_NUM 19
#define Y3_GPIO_NUM 18
#define Y2_GPIO_NUM 5
#define VSYNC_GPIO_NUM 25
#define HREF_GPIO_NUM 23
#define PCLK_GPIO_NUM 22

// WiFi + server config
// Replace these placeholders with your local network values.
struct WifiCandidate
{
  const char *ssid;
  const char *password;
};

#ifdef DADN_WIFI_CANDIDATES
static const WifiCandidate WIFI_CANDIDATES[] = DADN_WIFI_CANDIDATES;
#else
static const WifiCandidate WIFI_CANDIDATES[] = {
    {"YOUR_WIFI_SSID", "YOUR_WIFI_PASSWORD"},
};
#endif

#ifdef DADN_SERVER_IP
static const char *SERVER_IP = DADN_SERVER_IP;
#else
static const char *SERVER_IP = "192.168.1.100";
#endif
static const int SERVER_PORT = 5000;

#ifndef DADN_ENABLE_SERVER_HEALTH_CHECK
#define DADN_ENABLE_SERVER_HEALTH_CHECK 0
#endif

#ifndef DADN_CAMERA_VFLIP
#define DADN_CAMERA_VFLIP 0
#endif

#ifndef DADN_CAMERA_HMIRROR
#define DADN_CAMERA_HMIRROR 0
#endif

#ifndef DADN_STREAM_TIMEOUT_MS
#define DADN_STREAM_TIMEOUT_MS 300000
#endif

#ifndef DADN_JPEG_QUALITY
#define DADN_JPEG_QUALITY 24
#endif

#ifndef DADN_FRAME_DELAY_MS
#define DADN_FRAME_DELAY_MS 15
#endif

// Streaming + GPIO config
#define STREAM_PORT 8081
#define STATUS_LED 33
#define ALERT_LED 4
#define SEND_TO_SERVER_INTERVAL_MS 1000

WebServer server(STREAM_PORT);
uint32_t frameCount = 0;
uint32_t lastServerSendTime = 0;
bool serverConnected = false;

bool initCamera()
{
  camera_config_t config;
  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer = LEDC_TIMER_0;
  config.pin_d0 = Y2_GPIO_NUM;
  config.pin_d1 = Y3_GPIO_NUM;
  config.pin_d2 = Y4_GPIO_NUM;
  config.pin_d3 = Y5_GPIO_NUM;
  config.pin_d4 = Y6_GPIO_NUM;
  config.pin_d5 = Y7_GPIO_NUM;
  config.pin_d6 = Y8_GPIO_NUM;
  config.pin_d7 = Y9_GPIO_NUM;
  config.pin_xclk = XCLK_GPIO_NUM;
  config.pin_pclk = PCLK_GPIO_NUM;
  config.pin_vsync = VSYNC_GPIO_NUM;
  config.pin_href = HREF_GPIO_NUM;
  config.pin_sccb_sda = SIOD_GPIO_NUM;
  config.pin_sccb_scl = SIOC_GPIO_NUM;
  config.pin_pwdn = PWDN_GPIO_NUM;
  config.pin_reset = RESET_GPIO_NUM;
  config.xclk_freq_hz = 20000000;
  config.pixel_format = PIXFORMAT_JPEG;
  config.frame_size = FRAMESIZE_QVGA;
  config.jpeg_quality = DADN_JPEG_QUALITY;
  config.fb_count = 2;
  config.fb_location = CAMERA_FB_IN_PSRAM;
  config.grab_mode = CAMERA_GRAB_LATEST;

  esp_err_t err = esp_camera_init(&config);
  if (err != ESP_OK)
  {
    Serial.printf("[ERROR] Camera init failed: 0x%x\n", err);
    return false;
  }

  sensor_t *s = esp_camera_sensor_get();
  s->set_framesize(s, FRAMESIZE_QVGA);
  s->set_vflip(s, DADN_CAMERA_VFLIP);
  s->set_hmirror(s, DADN_CAMERA_HMIRROR);
  Serial.printf("[INFO] Camera orientation vflip=%d hmirror=%d\n", DADN_CAMERA_VFLIP, DADN_CAMERA_HMIRROR);
  Serial.printf("[INFO] Camera jpeg_quality=%d frame_delay_ms=%d\n", DADN_JPEG_QUALITY, DADN_FRAME_DELAY_MS);
  Serial.println("[INFO] Camera initialized");
  return true;
}

void initWiFi()
{
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);
  esp_wifi_set_ps(WIFI_PS_NONE);
  WiFi.setTxPower(WIFI_POWER_19_5dBm);

  for (size_t i = 0; i < (sizeof(WIFI_CANDIDATES) / sizeof(WIFI_CANDIDATES[0])); ++i)
  {
    const char *ssid = WIFI_CANDIDATES[i].ssid;
    const char *password = WIFI_CANDIDATES[i].password;

    Serial.printf("[INFO] Connecting WiFi: %s\n", ssid);
    WiFi.begin(ssid, password);

    int attempts = 0;
    while (WiFi.status() != WL_CONNECTED && attempts < 30)
    {
      delay(500);
      Serial.print(".");
      attempts++;
    }
    Serial.println();

    if (WiFi.status() == WL_CONNECTED)
    {
      Serial.printf("[SUCCESS] WiFi connected with SSID: %s\n", ssid);
      Serial.printf("[SUCCESS] Local IP: %s\n", WiFi.localIP().toString().c_str());
      digitalWrite(STATUS_LED, HIGH);
      return;
    }

    WiFi.disconnect(true, true);
    delay(200);
  }

  Serial.println("[ERROR] WiFi connection failed for all configured candidates");
}

void handleStream()
{
  WiFiClient client = server.client();
  client.setTimeout(1);
  client.setNoDelay(true);
  String response = "HTTP/1.1 200 OK\r\n";
  response += "Content-Type: multipart/x-mixed-replace; boundary=frame\r\n";
  response += "Cache-Control: no-store, no-cache, must-revalidate, max-age=0\r\n";
  response += "Pragma: no-cache\r\n";
  response += "Access-Control-Allow-Origin: *\r\n";
  response += "X-Accel-Buffering: no\r\n";
  response += "Connection: close\r\n\r\n";
  if (client.write((const uint8_t *)response.c_str(), response.length()) != response.length())
  {
    client.stop();
    return;
  }

  uint32_t streamDeadline = DADN_STREAM_TIMEOUT_MS > 0 ? millis() + DADN_STREAM_TIMEOUT_MS : 0;
  Serial.println("[INFO] Stream client connected");
  while (client.connected())
  {
    if (DADN_STREAM_TIMEOUT_MS > 0 && millis() > streamDeadline)
    {
      Serial.println("[WARN] Stream timeout");
      break;
    }

    camera_fb_t *fb = esp_camera_fb_get();
    if (!fb)
    {
      Serial.println("[ERROR] Capture failed");
      delay(30);
      continue;
    }

    frameCount++;
    String head = "--frame\r\nContent-Type: image/jpeg\r\nContent-Length: " + String(fb->len) + "\r\n\r\n";
    bool write_ok = true;
    write_ok = write_ok && client.write((const uint8_t *)head.c_str(), head.length()) == head.length();
    write_ok = write_ok && client.write((const uint8_t *)fb->buf, fb->len) == fb->len;
    write_ok = write_ok && client.write((const uint8_t *)"\r\n", 2) == 2;
    esp_camera_fb_return(fb);
    if (!write_ok)
    {
      Serial.println("[WARN] Stream client write failed");
      break;
    }

    if (DADN_FRAME_DELAY_MS > 0)
    {
      delay(DADN_FRAME_DELAY_MS);
    }
    else
    {
      yield();
    }
  }

  client.stop();
  Serial.println("[INFO] Stream client disconnected");
}

void handleRoot()
{
  String html = "<html><head><title>ESP32-CAM</title></head><body>";
  html += "<h2>ESP32-CAM Stream</h2>";
  html += "<p>IP: " + WiFi.localIP().toString() + "</p>";
  html += "<p>Frames: " + String(frameCount) + "</p>";
  html += "<p><a href='/stream'>Open MJPEG stream</a></p>";
  html += "</body></html>";
  server.send(200, "text/html", html);
}

void checkServerHealth()
{
  WiFiClient client;
  if (!client.connect(SERVER_IP, SERVER_PORT))
  {
    serverConnected = false;
    Serial.printf("[WARN] API server not reachable: %s:%d\n", SERVER_IP, SERVER_PORT);
    return;
  }

  String req = "GET /health HTTP/1.1\r\nHost: " + String(SERVER_IP) + "\r\nConnection: close\r\n\r\n";
  client.write((const uint8_t *)req.c_str(), req.length());
  delay(300);

  String resp;
  while (client.available())
  {
    resp += (char)client.read();
  }
  client.stop();

  serverConnected = resp.indexOf("200") >= 0;
}

void setup()
{
  Serial.begin(115200);
  delay(800);
  Serial.println("\n=== ESP32-CAM PlatformIO Stream ===");

  pinMode(STATUS_LED, OUTPUT);
  pinMode(ALERT_LED, OUTPUT);
  digitalWrite(STATUS_LED, LOW);
  digitalWrite(ALERT_LED, LOW);

  if (!initCamera())
  {
    while (true)
    {
      digitalWrite(ALERT_LED, !digitalRead(ALERT_LED));
      delay(400);
    }
  }

  initWiFi();

  server.on("/", HTTP_GET, handleRoot);
  server.on("/stream", HTTP_GET, handleStream);
  server.begin();

  Serial.printf("[INFO] Stream URL: http://%s:%d/stream\n", WiFi.localIP().toString().c_str(), STREAM_PORT);
#if DADN_ENABLE_SERVER_HEALTH_CHECK
  checkServerHealth();
#endif
}

void loop()
{
  server.handleClient();

#if DADN_ENABLE_SERVER_HEALTH_CHECK
  if (millis() - lastServerSendTime > SEND_TO_SERVER_INTERVAL_MS)
  {
    lastServerSendTime = millis();
    checkServerHealth();
  }
#endif

  delay(5);
}
