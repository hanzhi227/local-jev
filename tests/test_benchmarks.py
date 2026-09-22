import contextlib
import hashlib
from http.server import ThreadingHTTPServer
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from jev_local.benchmarks import runner
from jev_local.server import make_handler
from test_server import fake_server


class MetricTests(unittest.TestCase):
    def test_known_binary_metrics_and_failure_denominator(self):
        case = {"question": {"type": "noul"}, "expected": "yes"}
        result = runner.evaluate(case, {"noul": 0.8})
        self.assertTrue(result["correct"])
        self.assertAlmostEqual(result["brier"], 0.08)
        summary = runner.summarize(
            [{**result, "wall_s": 1}, {"error": "failed", "wall_s": 3}]
        )
        self.assertEqual(summary["accuracy"], 0.5)
        self.assertEqual(summary["failures"], 1)
        self.assertAlmostEqual(summary["ece_10_bins_successful"], 0.2)
        self.assertEqual(summary["latency_s"], {"p50": 1, "p95": 3})
        self.assertIsNone(summary["score_mae_successful"])

    def test_score_uses_argmax_for_accuracy_and_expectation_for_mae(self):
        case = {
            "question": {"type": "score", "criteria": ["low", "middle", "high"]},
            "expected": 0,
        }
        result = runner.evaluate(
            case, {"score": 0.95, "probabilities": {"0": 0.4, "1": 0.25, "2": 0.35}}
        )
        self.assertTrue(result["correct"])
        self.assertAlmostEqual(result["score_absolute_error"], 0.95)

    def test_bad_distributions_fail(self):
        case = {
            "question": {"type": "choice", "criteria": {"a": "A", "b": "B"}},
            "expected": "a",
        }
        for probs in ({"a": 0.3}, {"a": 0.1, "b": 0.2}, {"a": float("nan"), "b": 0.2}):
            with self.assertRaises(ValueError):
                runner.evaluate(case, {"choice": "a", "probabilities": probs})
        with self.assertRaises(ValueError):
            runner.evaluate(
                case, {"choice": "a", "probabilities": {"a": 0.2, "b": 0.8}}
            )

    def test_all_failed_has_no_calibration_score(self):
        summary = runner.summarize([{"error": "bad", "wall_s": 1}])
        self.assertEqual(summary["accuracy"], 0)
        self.assertIsNone(summary["brier_successful"])
        self.assertIsNone(summary["ece_10_bins_successful"])

    def test_bundled_snapshot_and_gold_validation(self):
        manifest = json.loads((runner.DATA / "manifest.json").read_text())
        for name, entry in manifest["files"].items():
            path = runner.DATA / name
            self.assertEqual(
                hashlib.sha256(path.read_bytes()).hexdigest(), entry["sha256"]
            )
            cases, _ = runner.load_cases([path])
            self.assertEqual(len(cases), entry["cases"])
        with self.assertRaisesRegex(ValueError, "duplicate"):
            runner.load_cases([runner.DATA / "smoke.jsonl"] * 2)


class RunnerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.http = ThreadingHTTPServer(
            ("127.0.0.1", 0), make_handler(fake_server(), "bench-key")
        )
        cls.thread = threading.Thread(target=cls.http.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = "http://%s:%s" % cls.http.server_address

    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown()
        cls.http.server_close()
        cls.thread.join()

    def test_http_run_writes_reproducible_artifacts(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict("os.environ", {"JEV_API_KEY": "bench-key"}),
        ):
            output = Path(directory) / "run"
            with (
                contextlib.redirect_stdout(io.StringIO()),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                code = runner.main(
                    ["--url", self.url, "--repeat", "2", "--output", str(output)]
                )
            self.assertEqual(code, 0)
            summary = json.loads((output / "summary.json").read_text())
            self.assertEqual(summary["attempts"], 12)
            self.assertEqual(summary["failures"], 0)
            self.assertEqual(summary["models"], ["test-local"])
            self.assertEqual(set(summary["by_type"]), {"noul", "choice", "score"})
            manifest = json.loads((output / "manifest.json").read_text())
            self.assertEqual(manifest["status"], "completed")
            self.assertEqual(manifest["warmup_requests"], 1)
            self.assertNotIn("bench-key", (output / "manifest.json").read_text())
            self.assertEqual(
                len((output / "results.jsonl").read_text().splitlines()), 12
            )

    def test_errors_recorded_and_gold_never_sent(self):
        cases, _ = runner.load_cases([runner.DATA / "smoke.jsonl"])
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(runner, "decide", side_effect=ValueError("offline")) as decide,
        ):
            with contextlib.redirect_stderr(io.StringIO()):
                summary = runner.run(
                    cases[:1], Path(directory) / "run", self.url, None, 1, 0, 1, {}
                )
            self.assertEqual(summary["failures"], 1)
            self.assertEqual(summary["accuracy"], 0)
            sent = decide.call_args.args[0]
            self.assertEqual(set(sent), {"state", "questions"})
            self.assertEqual(sent["questions"]["q"], cases[0]["question"])

    def test_dry_run_does_not_call_or_write(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(runner, "decide") as decide,
        ):
            path = Path(directory) / "run"
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(
                    runner.main(
                        ["--suite", "public", "--output", str(path), "--dry-run"]
                    ),
                    0,
                )
            self.assertFalse(path.exists())
            decide.assert_not_called()

    def test_warmup_failure_is_recorded(self):
        cases, _ = runner.load_cases([runner.DATA / "smoke.jsonl"])
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(runner, "decide", side_effect=ValueError("offline")),
        ):
            path = Path(directory) / "run"
            with self.assertRaises(ValueError):
                runner.run(cases, path, self.url, None, 1, 1, 1, {})
            self.assertEqual(
                json.loads((path / "manifest.json").read_text())["status"],
                "warmup_failed",
            )
            self.assertFalse((path / "summary.json").exists())


if __name__ == "__main__":
    unittest.main()
