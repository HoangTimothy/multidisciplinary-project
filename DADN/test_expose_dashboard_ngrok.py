import tempfile
import unittest
from pathlib import Path
from unittest import mock


try:
    from DADN import expose_dashboard_ngrok as dashboard
except ImportError:
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import expose_dashboard_ngrok as dashboard


class TestDashboardUrlHelpers(unittest.TestCase):
    def test_normalize_stream_url_adds_https_for_domain(self):
        self.assertEqual(
            dashboard.normalize_stream_url("xxxx.ngrok-free.app"),
            "https://xxxx.ngrok-free.app/stream",
        )

    def test_normalize_stream_url_adds_http_for_localhost(self):
        self.assertEqual(
            dashboard.normalize_stream_url("localhost:8081"),
            "http://localhost:8081/stream",
        )

    def test_normalize_stream_url_is_idempotent(self):
        self.assertEqual(
            dashboard.normalize_stream_url("https://xxxx.ngrok-free.app/stream"),
            "https://xxxx.ngrok-free.app/stream",
        )

    def test_read_url_file_ignores_comments(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "url.txt"
            path.write_text("# comment\n\nhttps://example.ngrok-free.app/stream\n", encoding="utf-8")
            self.assertEqual(dashboard.read_url_file(path), "https://example.ngrok-free.app/stream")


class TestNgrokTunnelHelpers(unittest.TestCase):
    def test_find_public_url_matches_supported_upstreams(self):
        tunnels = [
            {
                "public_url": "https://demo.ngrok-free.app",
                "config": {"addr": "http://localhost:5000"},
            }
        ]
        with mock.patch.object(dashboard, "get_ngrok_tunnels", return_value=tunnels):
            self.assertEqual(
                dashboard.find_public_url("http://127.0.0.1:4040", {"http://localhost:5000", "5000"}),
                "https://demo.ngrok-free.app",
            )

    def test_find_public_url_ignores_non_https(self):
        tunnels = [
            {
                "public_url": "http://demo.ngrok-free.app",
                "config": {"addr": "http://localhost:5000"},
            }
        ]
        with mock.patch.object(dashboard, "get_ngrok_tunnels", return_value=tunnels):
            self.assertIsNone(dashboard.find_public_url("http://127.0.0.1:4040", {"http://localhost:5000"}))


if __name__ == "__main__":
    unittest.main()
