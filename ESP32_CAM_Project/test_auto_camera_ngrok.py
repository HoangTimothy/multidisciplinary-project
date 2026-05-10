import unittest
from unittest import mock


# Allow running tests from repo root:
#   python -m unittest ESP32_CAM_Project.test_auto_camera_ngrok
try:
    from ESP32_CAM_Project import auto_camera_ngrok as acn
    from ESP32_CAM_Project import configure_esp32_wifi as wifi_config
    from ESP32_CAM_Project import run_esp32_all as one_run
except ImportError:
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import auto_camera_ngrok as acn
    import configure_esp32_wifi as wifi_config
    import run_esp32_all as one_run


class TestUrlNormalization(unittest.TestCase):
    def test_normalize_base_url_adds_scheme(self):
        self.assertEqual(acn.normalize_base_url("192.168.1.50:8081"), "http://192.168.1.50:8081")

    def test_normalize_base_url_strips_stream(self):
        self.assertEqual(
            acn.normalize_base_url("http://192.168.1.50:8081/stream"),
            "http://192.168.1.50:8081",
        )

    def test_public_stream_url_appends_stream(self):
        self.assertEqual(
            acn.public_stream_url("https://xxxx.ngrok-free.app"),
            "https://xxxx.ngrok-free.app/stream",
        )

    def test_public_stream_url_idempotent(self):
        self.assertEqual(
            acn.public_stream_url("https://xxxx.ngrok-free.app/stream"),
            "https://xxxx.ngrok-free.app/stream",
        )


class TestEsp32Validation(unittest.TestCase):
    def test_validate_esp32_accepts_root_html(self):
        def fake_try_read_url(url: str, timeout: float, read_bytes: int = 256):
            self.assertTrue(url.endswith("/"))
            return "text/html", b"<html>ESP32-CAM <a href='/stream'>stream</a></html>"

        with mock.patch.object(acn, "try_read_url", side_effect=fake_try_read_url):
            candidate = acn.validate_esp32_host("192.168.1.50", 8081, 0.2)

        self.assertIsNotNone(candidate)
        assert candidate is not None
        self.assertEqual(candidate.base_url, "http://192.168.1.50:8081")
        self.assertEqual(candidate.stream_url, "http://192.168.1.50:8081/stream")
        self.assertEqual(candidate.reason, "root page")

    def test_validate_esp32_accepts_stream_content_type(self):
        def fake_try_read_url(url: str, timeout: float, read_bytes: int = 256):
            if url.endswith("/"):
                raise OSError("root not reachable")
            self.assertTrue(url.endswith("/stream"))
            return "multipart/x-mixed-replace; boundary=frame", b"--frame\r\n"

        with mock.patch.object(acn, "try_read_url", side_effect=fake_try_read_url):
            candidate = acn.validate_esp32_host("192.168.1.99", 8081, 0.2)

        self.assertIsNotNone(candidate)
        assert candidate is not None
        self.assertEqual(candidate.reason, "mjpeg stream")


class TestUrlFileFormat(unittest.TestCase):
    def test_url_file_is_stream_url(self):
        # Smoke-check the spec requirement: what we write must end with /stream.
        stream_url = acn.public_stream_url("https://example.ngrok-free.app")
        self.assertTrue(stream_url.endswith("/stream"))


class TestOneRunHelpers(unittest.TestCase):
    def test_normalize_stream_url_accepts_base_url(self):
        self.assertEqual(
            one_run.normalize_stream_url("192.168.1.50:8081"),
            "http://192.168.1.50:8081/stream",
        )

    def test_normalize_stream_url_is_idempotent(self):
        self.assertEqual(
            one_run.normalize_stream_url("http://192.168.1.50:8081/stream"),
            "http://192.168.1.50:8081/stream",
        )

    def test_stream_base_url_strips_path(self):
        self.assertEqual(
            one_run.stream_base_url("http://192.168.1.50:8081/stream"),
            "http://192.168.1.50:8081",
        )

    def test_download_boot_detection(self):
        lines = ["rst:0x1 (POWERON_RESET),boot:0x3 (DOWNLOAD_BOOT(UART0/UART1/SDIO_REI_REO_V2))", "waiting for download"]
        self.assertTrue(one_run.saw_download_mode(lines))
        self.assertFalse(one_run.saw_firmware_ready(lines))

    def test_ignores_unspecified_ip_from_failed_wifi(self):
        text = "[INFO] Stream URL: http://0.0.0.0:8081/stream"
        self.assertIsNone(one_run.parse_stream_url(text))
        self.assertIsNone(one_run.parse_ip("[SUCCESS] Local IP: 0.0.0.0"))

    def test_wifi_failure_detection_extracts_ssid(self):
        lines = ["[INFO] Connecting WiFi: HCMUT-MEETING", "[ERROR] WiFi connection failed for all configured candidates"]
        self.assertTrue(one_run.saw_wifi_failure(lines))
        self.assertEqual(one_run.connecting_ssids(lines), ["HCMUT-MEETING"])


class TestWifiConfigHelpers(unittest.TestCase):
    def test_c_string_escapes_quotes_and_backslashes(self):
        self.assertEqual(wifi_config.c_string('A"B\\C'), '"A\\"B\\\\C"')


class TestHostHints(unittest.TestCase):
    def test_parse_hosts_from_text_filters_noise(self):
        text = "192.168.1.12 ff-aa dynamic\n224.0.0.1 multicast\n10.0.0.255 broadcast\n"
        self.assertEqual(acn.parse_hosts_from_text(text), ["192.168.1.12"])

    def test_merge_hosts_prefers_hints_and_dedupes(self):
        self.assertEqual(
            acn.merge_hosts(["192.168.1.5", "192.168.1.6"], ["192.168.1.6", "192.168.1.7"]),
            ["192.168.1.5", "192.168.1.6", "192.168.1.7"],
        )


if __name__ == "__main__":
    unittest.main()
