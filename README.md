# Multidisciplinary Project (DADN + ESP32-CAM)

Repo này gồm 3 phần chính:

- **DADN/**: Python server nhận MJPEG stream (`/stream`) và chạy detection + dashboard realtime.
- **ESP32_CAM_Project/**: Firmware PlatformIO cho AI Thinker ESP32-CAM (serve MJPEG) + script tiện ích (WiFi creds, ngrok).
- **report/**: LaTeX report (mẫu HCMUT).

## Chạy nhanh (PC Windows + ESP32-CAM cùng mạng)

1) **Flash ESP32-CAM** (xem hướng dẫn chi tiết ở [ESP32_CAM_Project/README.md](ESP32_CAM_Project/README.md)) để lấy được URL dạng:

- `http://<ESP32_IP>:8081/stream`

2) **Cài dependencies cho DADN**:

```powershell
cd DADN
python -m pip install -r requirements.txt
```

3) **Chạy server + dashboard** (2 cách):

- Cách dễ nhất trên Windows:

```powershell
cd DADN
.\start_streaming_server.bat
```

- Hoặc chạy trực tiếp và truyền URL camera:

```powershell
cd DADN
python run_stream_server.py --camera-url http://<ESP32_IP>:8081/stream
```

Mở dashboard: `http://localhost:5000`

## Chạy remote (ESP32 ở laptop → ngrok → DADN trên Raspberry Pi)

1) Trên **máy đang nhìn thấy ESP32 stream** (thường là laptop cùng mạng với ESP32):

Ghi chú: `run_esp32_all.py` cần có `ngrok` trong `PATH` trên Windows. Auto-download ngrok chỉ hỗ trợ Linux/WSL/Raspberry Pi.
Nếu muốn tool tự dò COM port / đọc Serial fallback thì cài thêm: `python -m pip install pyserial`.

```powershell
cd ESP32_CAM_Project
python run_esp32_all.py --ngrok-token "<YOUR_NGROK_TOKEN>"
```

Script sẽ in ra URL public kết thúc bằng `/stream`.

2) Trên **Raspberry Pi / máy chạy inference**:

```bash
cd DADN
python run_stream_server.py --camera-url https://xxxx.ngrok-free.app/stream
```

Bạn cũng có thể đưa **base URL** (launcher sẽ tự append `/stream`):

```bash
python run_stream_server.py --camera-url https://xxxx.ngrok-free.app
```

## API server (tuỳ chọn)

Ngoài pipeline MJPEG streaming, repo còn có server API nhận JPEG qua `POST /api/detect`:

```powershell
cd DADN
python -m pip install -r requirements_api.txt
python api_server.py
```

Lưu ý: firmware ESP32-CAM trong repo **không POST frame** lên API server; nó chủ yếu **serve MJPEG `/stream`** và (tuỳ cấu hình) chỉ ping `GET /health` để kiểm tra sống.

## Tài liệu chi tiết

- DADN: [DADN/README.md](DADN/README.md)
- ESP32 firmware + ngrok helpers: [ESP32_CAM_Project/README.md](ESP32_CAM_Project/README.md)
- Report template: xem [report/README.txt](report/README.txt) và file chính [report/report.tex](report/report.tex)
