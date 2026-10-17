#!/usr/bin/env python3
"""Small, offline regression for metadata model integrity and interrupted downloads."""
import hashlib
import http.server
import importlib.util
from pathlib import Path
import tempfile
import threading
import types
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("serve", Path(__file__).resolve().parents[1] / "deploy/metadata/serve.py")
serve = importlib.util.module_from_spec(spec)
spec.loader.exec_module(serve)
DATA = b"pinned synthetic model bytes for download tests"
SHA = hashlib.sha256(DATA).hexdigest()


class Handler(http.server.BaseHTTPRequestHandler):
    mode = "range"
    requests = []

    def do_GET(self):
        self.requests.append(self.headers.get("Range"))
        offset = int(self.headers.get("Range", "bytes=0-")[6:-1])
        if self.mode == "ignore":
            offset = 0
        self.send_response(206 if self.headers.get("Range") and self.mode != "ignore" else 200)
        if self.headers.get("Range") and self.mode != "ignore":
            start = offset + (1 if self.mode == "bad-range" else 0)
            self.send_header("Content-Range", f"bytes {start}-{len(DATA)-1}/{len(DATA)}")
        body = (b"!" + DATA[1:] if self.mode == "corrupt" else DATA)[offset:]
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class DownloadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f"http://127.0.0.1:{cls.server.server_port}/model"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.model = self.root / serve.NAME
        self.partial = self.root / (serve.NAME + ".partial")
        Handler.mode = "range"
        Handler.requests.clear()

    def ensure(self):
        return serve.ensure_model(self.root, self.url, len(DATA), SHA)

    def test_download_and_cached_restart(self):
        self.assertEqual(self.ensure().read_bytes(), DATA)
        self.assertFalse(self.partial.exists())
        self.assertEqual(self.ensure().read_bytes(), DATA)
        self.assertEqual(len(Handler.requests), 1)

    def test_interrupted_download_resumes(self):
        self.partial.write_bytes(DATA[:11])
        self.assertEqual(self.ensure().read_bytes(), DATA)
        self.assertEqual(Handler.requests, ["bytes=11-"])

    def test_server_ignoring_range_restarts_partial_only(self):
        Handler.mode = "ignore"
        self.partial.write_bytes(DATA[:11])
        self.assertEqual(self.ensure().read_bytes(), DATA)

    def test_completed_partial_is_verified_and_activated_without_network(self):
        self.partial.write_bytes(DATA)
        self.assertEqual(self.ensure().read_bytes(), DATA)
        self.assertEqual(Handler.requests, [])

    def test_existing_invalid_model_is_preserved(self):
        self.model.write_bytes(b"x" * len(DATA))
        with self.assertRaisesRegex(RuntimeError, "Existing model checksum mismatch"):
            self.ensure()
        self.assertEqual(self.model.read_bytes(), b"x" * len(DATA))
        self.assertEqual(Handler.requests, [])

    def test_corrupt_download_never_activated(self):
        Handler.mode = "corrupt"
        with self.assertRaisesRegex(RuntimeError, "checksum-mismatched"):
            self.ensure()
        self.assertFalse(self.model.exists())
        self.assertTrue(self.partial.exists())

    def test_incorrect_resume_range_preserves_partial(self):
        Handler.mode = "bad-range"
        self.partial.write_bytes(DATA[:11])
        with self.assertRaisesRegex(RuntimeError, "Content-Range"):
            self.ensure()
        self.assertEqual(self.partial.read_bytes(), DATA[:11])

    def test_insufficient_space_fails_before_downloading(self):
        with patch.object(serve.shutil, "disk_usage", return_value=types.SimpleNamespace(free=1)):
            with self.assertRaisesRegex(RuntimeError, "Not enough disk space"):
                self.ensure()
        self.assertEqual(Handler.requests, [])

    def test_symlink_is_not_overwritten(self):
        target = self.root / "retained"
        target.write_bytes(b"retained")
        self.partial.symlink_to(target)
        with self.assertRaisesRegex(RuntimeError, "Refusing symlink"):
            self.ensure()
        self.assertEqual(target.read_bytes(), b"retained")


if __name__ == "__main__":
    unittest.main()
