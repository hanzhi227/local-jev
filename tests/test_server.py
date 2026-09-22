import argparse
import http.client
import json
from pathlib import Path
import threading
import unittest
from unittest.mock import patch

from jev_local.protocol import build_rows
from jev_local.server import Server, build_server_from_env, make_handler
from http.server import ThreadingHTTPServer

REQUEST = json.loads(
    (Path(__file__).resolve().parents[1] / "examples/request.json").read_text()
)


class ProtocolTests(unittest.TestCase):
    def test_prompt_mapping_matches_existing_scoring(self):
        rows = build_rows(REQUEST)
        self.assertEqual(
            rows[0]["options"][1], {"id": "technical", "description": "technical: Bugs"}
        )
        self.assertEqual(
            rows[1]["options"][2], {"id": "2", "description": "2: Blocking"}
        )
        self.assertEqual(
            rows[2]["options"],
            [
                {"id": "true", "description": "true: The proposition is true."},
                {"id": "false", "description": "false: The proposition is false."},
            ],
        )

    def test_rejects_invalid_requests_before_inference(self):
        for request in [
            [],
            {},
            {"state": "x", "questions": []},
            {**REQUEST, "state": float("nan")},
            {**REQUEST, "questions": {"q": []}},
        ]:
            with self.subTest(request=request), self.assertRaises(ValueError):
                build_rows(request)
        for q in [
            {"type": "choice", "instructions": "x", "criteria": {"a": "one"}},
            {"type": "score", "instructions": "x", "criteria": ["a", 2]},
            {"type": "noul", "instructions": "x", "criteria": []},
            {"type": "noul", "instructions": ""},
            {"type": "unknown", "instructions": "x"},
        ]:
            with self.subTest(question=q), self.assertRaises(ValueError):
                build_rows({"state": "x", "questions": {"q": q}})
        with self.assertRaises(ValueError):
            build_rows(REQUEST, max_questions=2)

    def test_env_validation_precedes_loading(self):
        args = argparse.Namespace(
            backend=None, endpoint=None, mode=None, max_questions=None, mlx_bits=None
        )
        for env in [
            {"JEV_MODE": "wrong"},
            {"JEV_MLX_BITS": "3"},
            {"JEV_MAX_QUESTIONS": "0"},
        ]:
            with (
                patch.dict("os.environ", env, clear=True),
                patch("jev_local.server.Server") as loader,
            ):
                with self.assertRaises(ValueError):
                    build_server_from_env(args)
                loader.assert_not_called()


def fake_server():
    server = Server.__new__(Server)
    server.backend, server.mlx_bits, server.label = "mlx", 8, "test-local"
    server.mode, server.max_questions, server.max_tokens = "shared", 32, 4096
    server.load_s = 0
    server.lock = threading.Lock()
    server.loaded = (None, None, {})

    def score(model, tok, row, meta, max_tokens):
        count = len(row["options"])
        return {
            "option_ids": [o["id"] for o in row["options"]],
            "probabilities": [1 / count] * count,
            "input_tokens": 100,
        }

    server.score = score
    server.score_shared = lambda m, t, rows, meta, limit: (
        [score(m, t, row, meta, limit) for row in rows],
        {"prefix_tokens": 20, "batch_size": len(rows)},
    )
    return server


class DecisionTests(unittest.TestCase):
    def test_direct_and_shared_return_same_typed_answers(self):
        server = fake_server()
        shared = server.decide(REQUEST)
        server.mode = "direct"
        direct = server.decide(REQUEST)
        self.assertEqual(shared["answers"], direct["answers"])
        self.assertEqual(shared["answers"]["needs_engineer"]["noul"], 0.5)
        self.assertEqual(shared["answers"]["urgency"]["score"], 1)
        self.assertTrue(shared["usage"]["state_cache_hit"])
        self.assertFalse(direct["usage"]["state_cache_hit"])


class HTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.http = ThreadingHTTPServer(
            ("127.0.0.1", 0), make_handler(fake_server(), "secret")
        )
        cls.thread = threading.Thread(target=cls.http.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown()
        cls.http.server_close()
        cls.thread.join()

    def request(self, method, path, body=None, authenticated=True, headers=None):
        conn = http.client.HTTPConnection(*self.http.server_address, timeout=5)
        actual_headers = {"Authorization": "Bearer secret"} if authenticated else {}
        actual_headers.update(headers or {})
        conn.request(method, path, body, actual_headers)
        response = conn.getresponse()
        status, data = response.status, json.loads(response.read())
        conn.close()
        return status, data

    def test_health_and_decision(self):
        self.assertEqual(self.request("GET", "/ready", authenticated=False)[0], 200)
        status, data = self.request("POST", "/v1/systemone", json.dumps(REQUEST))
        self.assertEqual(status, 200)
        self.assertEqual(set(data["answers"]), set(REQUEST["questions"]))

    def test_auth_routing_and_malformed_input(self):
        self.assertEqual(
            self.request("POST", "/v1/systemone", "{}", authenticated=False)[0], 401
        )
        self.assertEqual(self.request("POST", "/unknown", "{}")[0], 404)
        for body in [
            "{",
            "[]",
            "{}",
            json.dumps({**REQUEST, "questions": {"q": None}}),
        ]:
            with self.subTest(body=body):
                self.assertEqual(self.request("POST", "/v1/systemone", body)[0], 400)
        self.assertEqual(
            self.request("POST", "/v1/systemone", "", headers={"Content-Length": "-1"})[
                0
            ],
            400,
        )
        self.assertEqual(
            self.request(
                "POST", "/v1/systemone", "", headers={"Content-Length": "1048577"}
            )[0],
            400,
        )


if __name__ == "__main__":
    unittest.main()
