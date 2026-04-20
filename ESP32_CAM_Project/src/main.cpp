#include <Arduino.h>
#include "esp_camera.h"
#include <WiFi.h>
#include <WebServer.h>

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

static const WifiCandidate WIFI_CANDIDATES[] = {
    {"YOUR_WIFI_SSID", "YOUR_WIFI_PASSWORD"},
};

static const char *SERVER_IP = "192.168.1.100";
static const int SERVER_PORT = 5000;

// Streaming + GPIO config
#define STREAM_PORT 8081
#define STATUS_LED 33
#define ALERT_LED 4
#define JPEG_QUALITY 12
#define STREAM_TIMEOUT_MS 10000
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
  config.jpeg_quality = JPEG_QUALITY;
  config.fb_count = 2;
  config.fb_location = CAMERA_FB_IN_PSRAM;
  config.grab_mode = CAMERA_GRAB_WHEN_EMPTY;

  esp_err_t err = esp_camera_init(&config);
  if (err != ESP_OK)
  {
    Serial.printf("[ERROR] Camera init failed: 0x%x\n", err);
    return false;
  }

  sensor_t *s = esp_camera_sensor_get();
  s->set_framesize(s, FRAMESIZE_QVGA);
  Serial.println("[INFO] Camera initialized");
  return true;
}

void initWiFi()
{
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);

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
  String response = "HTTP/1.1 200 OK\r\n";
  response += "Content-Type: multipart/x-mixed-replace; boundary=frame\r\n";
  response += "Connection: close\r\n\r\n";
  client.write((const uint8_t *)response.c_str(), response.length());

  uint32_t streamDeadline = millis() + STREAM_TIMEOUT_MS;
  while (client.connected())
  {
    if (millis() > streamDeadline)
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
    client.write((const uint8_t *)head.c_str(), head.length());
    client.write((const uint8_t *)fb->buf, fb->len);
    client.write((const uint8_t *)"\r\n", 2);
    esp_camera_fb_return(fb);

    delay(40);
  }

  client.stop();
}

void handleRoot()
{
  String html = "<html><head><title>ESP32-CAM</title></head><body>";
  html += "<h2>ESP32-CAM Stream</h2>";
  html += "<p>IP: " + WiFi.localIP().toString() + "</p>";
  html += "<p>Frames: " + String(frameCount) + "</p>";
  html += "<img src='/stream' style='max-width:95%;height:auto;'/>";
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
  checkServerHealth();
}

void loop()
{
  server.handleClient();

  if (millis() - lastServerSendTime > SEND_TO_SERVER_INTERVAL_MS)
  {
    lastServerSendTime = millis();
    checkServerHealth();
  }

  delay(5);
}