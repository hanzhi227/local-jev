import contextlib
from http.server import ThreadingHTTPServer
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import wave

from jev_local.examples import cli as examples
from jev_local.client import validate_answers
from jev_local.server import make_handler
from test_server import fake_server


class ExampleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.http = ThreadingHTTPServer(
            ("127.0.0.1", 0), make_handler(fake_server(), "test-key")
        )
        cls.thread = threading.Thread(target=cls.http.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = "http://%s:%s" % cls.http.server_address

    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown()
        cls.http.server_close()
        cls.thread.join()

    def run_cli(self, arguments):
        output, error = io.StringIO(), io.StringIO()
        with (
            patch.dict("os.environ", {"JEV_API_KEY": "test-key"}),
            contextlib.redirect_stdout(output),
            contextlib.redirect_stderr(error),
        ):
            status = examples.main([*arguments, "--url", self.url])
        return status, output.getvalue(), error.getvalue()

    def test_feed_ranks_relevant_substance_over_promotion(self):
        useful = {
            "relevance": {"score": 2},
            "substance": {"score": 2},
            "promotion": {"noul": 0},
        }
        ad = {
            "relevance": {"score": 0},
            "substance": {"score": 0},
            "promotion": {"noul": 1},
        }
        self.assertEqual(examples.feed_result({}, useful)["suggestion"], "highlight")
        self.assertEqual(examples.feed_result({}, ad)["suggestion"], "collapse")
        fixture = Path(__file__).resolve().parents[1] / "examples/feed.json"
        status, output, error = self.run_cli(["feed", str(fixture)])
        self.assertEqual(status, 0, error)
        self.assertEqual(len(json.loads(output)), 4)

    def test_soundscape_creates_valid_audio_and_preserves_existing_file(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "preview.wav"
            args = [
                "soundscape",
                "soft rain",
                "--seconds",
                "1",
                "--output",
                str(output),
            ]
            status, _, error = self.run_cli(args)
            self.assertEqual(status, 0, error)
            with wave.open(str(output)) as audio:
                self.assertEqual(audio.getnframes(), 22050)
                self.assertEqual(audio.getnchannels(), 1)
                self.assertEqual(audio.getsampwidth(), 2)
                self.assertNotEqual(set(audio.readframes(22050)), {0})
            original = output.read_bytes()
            self.assertEqual(self.run_cli(args)[0], 1)
            self.assertEqual(output.read_bytes(), original)

    def test_pet_remembers_bounded_history(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pet.json"
            for i in range(7):
                status, _, error = self.run_cli(
                    ["pet", f"Hello {i}", "--memory", str(path)]
                )
                self.assertEqual(status, 0, error)
            memory = examples.load_memory(path)
            self.assertEqual(len(memory["history"]), 5)
            self.assertEqual(memory["history"][0]["message"], "Hello 2")
            status, output, error = self.run_cli(
                ["pet", "Again", "--memory", str(path), "--dry-run"]
            )
            self.assertEqual(status, 0, error)
            self.assertEqual(json.loads(output)["state"]["memory"], memory)

    def test_dry_run_never_calls_server_or_writes(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(examples, "decide") as decide,
        ):
            path = Path(directory) / "output"
            for args in (
                ["pet", "Hello", "--memory", str(path)],
                ["soundscape", "wind", "--output", str(path)],
            ):
                status, output, error = self.run_cli([*args, "--dry-run"])
                self.assertEqual(status, 0, error)
                self.assertIn("questions", json.loads(output))
                self.assertFalse(path.exists())
            decide.assert_not_called()

    def test_server_failure_does_not_advance_memory(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pet.json"
            self.run_cli(["pet", "Hello", "--memory", str(path)])
            original = path.read_bytes()
            with patch.object(
                examples, "decide", side_effect=ValueError("server failed")
            ):
                self.assertEqual(
                    self.run_cli(["pet", "Again", "--memory", str(path)])[0], 1
                )
            self.assertEqual(path.read_bytes(), original)

    def test_auth_failure_and_malformed_outputs(self):
        payload = examples.soundscape_request("rain")
        with self.assertRaisesRegex(ValueError, "HTTP 401"):
            examples.decide(payload, self.url, "wrong")
        for result in ({}, {"answers": {"texture": {"type": "choice", "choice": []}}}):
            with self.assertRaises(ValueError):
                validate_answers(payload, result)
        payload = examples.feed_request({"text": "test"}, "test")
        with self.assertRaises(ValueError):
            validate_answers(
                payload,
                {"answers": {"relevance": {"type": "score", "score": float("nan")}}},
            )


if __name__ == "__main__":
    unittest.main()
