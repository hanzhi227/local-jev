"""Local JEV-compatible HTTP server using SemIf scoring."""

from __future__ import annotations

import argparse
import json
import logging
import os
import platform
from pathlib import Path
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .protocol import build_rows, format_answer

logger = logging.getLogger(__name__)

DEFAULT_MLX_SOURCE = "Qwen/Qwen3.5-4B"
DEFAULT_REVISION = "851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a"
DEFAULT_GGUF = "models/Qwen3.5-4B-Q4_K_S.gguf"


def default_backend():
    return (
        "mlx"
        if platform.system() == "Darwin" and platform.machine() == "arm64"
        else "llamacpp"
    )


def short_name(endpoint: str) -> str:
    """Quant tag from a GGUF filename: Qwen3.5-4B-Q4_K_S.gguf -> q4_k_s."""
    stem = os.path.splitext(os.path.basename(endpoint))[0].lower()
    for prefix in ("qwen_qwen3.5-4b-", "qwen3.5-4b-"):
        if stem.startswith(prefix):
            return stem[len(prefix) :]
    return stem


class Server:
    def __init__(
        self,
        endpoint: str,
        mode: str,
        max_questions: int,
        backend: str = "mlx",
        mlx_bits: int | None = 8,
    ):
        self.backend = backend
        self.mlx_bits = mlx_bits if backend == "mlx" else None
        self.label = (
            f"semif-qwen3.5-4b-mlx{mlx_bits}bit"
            if backend == "mlx"
            else f"semif-qwen3.5-4b-{short_name(endpoint)}-cpu"
        )
        self.max_tokens = 4096
        self.mode = mode
        self.max_questions = max_questions
        self.lock = threading.Lock()
        if backend == "mlx":
            from semif_phase1 import mlx_backend as engine
        else:
            from semif_phase1 import llamacpp_backend as engine
        self.score, self.score_shared = engine.score, engine.score_shared
        t0 = time.perf_counter()
        if backend == "mlx":
            self.loaded = engine.load_model(
                endpoint, DEFAULT_REVISION, mlx_bits, cache_limit_mib=256
            )
        else:
            if not Path(endpoint).is_file():
                raise ValueError(
                    f"GGUF file not found: {endpoint}. Supply --gguf PATH."
                )
            self.loaded = engine.load_model(
                DEFAULT_MLX_SOURCE,
                DEFAULT_REVISION,
                endpoint,
                context_tokens=self.max_tokens,
            )
        self.load_s = time.perf_counter() - t0
        logger.info(
            "model ready in %.1fs (backend=%s, %s)", self.load_s, backend, endpoint
        )

    def decide(self, request: dict) -> dict:
        rows = build_rows(request, self.max_questions)
        questions = request["questions"]
        t0 = time.perf_counter()
        with self.lock:
            model, tok, meta = self.loaded
            if self.mode == "shared" and len(rows) > 1:
                results, timing = self.score_shared(
                    model, tok, rows, meta, self.max_tokens
                )
            else:
                results = [
                    self.score(model, tok, row, meta, self.max_tokens) for row in rows
                ]
                timing = {}
        latency = time.perf_counter() - t0
        answers = {}
        input_tokens = 0
        for (key, question), out in zip(questions.items(), results):
            probs = dict(zip(out["option_ids"], out["probabilities"]))
            answers[key] = format_answer(question, probs)
            input_tokens += out.get("input_tokens", 0)
        return {
            "model": self.label,
            "answers": answers,
            "usage": {
                "input_tokens": input_tokens,
                "output_tokens": 0,
                "state_tokens": timing.get("prefix_tokens", 0),
                "question_tokens": input_tokens - timing.get("prefix_tokens", 0),
                "state_cache_hit": bool(timing.get("batch_size", 0) > 1),
                "images": 0,
            },
            "latency_s": round(latency, 4),
        }


def make_handler(server: Server, api_key: str | None):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def _send(self, status: int, payload: dict):
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.close_connection = True
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path in ("/ready", "/health", "/healthz"):
                self._send(
                    200,
                    {
                        "ok": True,
                        "model": server.label,
                        "loaded": True,
                        "backend": server.backend,
                        "mlx_bits": server.mlx_bits,
                        "load_s": round(server.load_s, 1),
                        "mode": server.mode,
                    },
                )
            else:
                self._send(
                    404, {"error": {"message": "not found", "type": "not_found"}}
                )

        def do_POST(self):
            if self.path != "/v1/systemone":
                self._send(
                    404, {"error": {"message": "not found", "type": "not_found"}}
                )
                return
            if api_key and self.headers.get("authorization", "") != f"Bearer {api_key}":
                self._send(
                    401,
                    {
                        "error": {
                            "message": "invalid or missing API key",
                            "type": "invalid_api_key",
                        }
                    },
                )
                return
            try:
                if self.headers.get("Transfer-Encoding"):
                    raise ValueError(
                        "Transfer-Encoding is unsupported; send Content-Length"
                    )
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 1024 * 1024:
                    raise ValueError("request body must be between 1 byte and 1 MiB")
                request = json.loads(self.rfile.read(length) or b"{}")
            except ValueError as e:
                self._send(
                    400,
                    {"error": {"message": f"bad request: {e}", "type": "bad_request"}},
                )
                return
            try:
                self._send(200, server.decide(request))
            except ValueError as e:
                self._send(400, {"error": {"message": str(e), "type": "bad_request"}})
            except Exception as e:  # surface the failure, never fake an answer
                logger.exception("decision failed")
                self._send(
                    500,
                    {
                        "error": {
                            "message": f"{type(e).__name__}: {str(e)[:300]}",
                            "type": "decision_failed",
                        }
                    },
                )

        def log_message(self, fmt, *args):
            logger.info("%s - %s", self.address_string(), fmt % args)

    return Handler


def build_server_from_env(args) -> Server:
    backend = args.backend or os.environ.get("JEV_BACKEND", default_backend())
    if backend not in ("mlx", "llamacpp"):
        raise ValueError(f"unknown backend {backend!r}; use mlx or llamacpp")
    endpoint = args.endpoint or os.environ.get("JEV_ENDPOINT")
    if not endpoint:
        endpoint = (
            os.environ.get("JEV_GGUF", DEFAULT_GGUF)
            if backend == "llamacpp"
            else DEFAULT_MLX_SOURCE
        )
    if backend == "llamacpp" and not endpoint:
        raise ValueError(
            "llamacpp backend needs JEV_GGUF or --gguf pointing at a .gguf file"
        )
    mode = args.mode or os.environ.get("JEV_MODE", "shared")
    max_questions = (
        args.max_questions
        if args.max_questions is not None
        else int(os.environ.get("JEV_MAX_QUESTIONS", "32"))
    )
    mlx_bits = (
        args.mlx_bits
        if args.mlx_bits is not None
        else int(os.environ.get("JEV_MLX_BITS", "8"))
    )
    if mode not in ("shared", "direct") or mlx_bits not in (4, 8) or max_questions < 1:
        raise ValueError(
            "mode must be shared/direct, MLX bits 4/8, and max questions positive"
        )
    return Server(endpoint, mode, max_questions, backend=backend, mlx_bits=mlx_bits)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--endpoint",
        default=None,
        help="model source: HF id (mlx) or GGUF path (llamacpp); env JEV_ENDPOINT",
    )
    ap.add_argument(
        "--backend",
        choices=("mlx", "llamacpp"),
        default=None,
        help="env JEV_BACKEND (default: mlx on Apple Silicon, llamacpp elsewhere)",
    )
    ap.add_argument(
        "--gguf", default=None, help="alias for the llamacpp endpoint; env JEV_GGUF"
    )
    ap.add_argument(
        "--mlx-bits",
        dest="mlx_bits",
        type=int,
        choices=(4, 8),
        default=None,
        help="MLX in-memory quantization width; env JEV_MLX_BITS (default 8)",
    )
    ap.add_argument("--host", default=None, help="env JEV_HOST (default 127.0.0.1)")
    ap.add_argument(
        "--port", type=int, default=None, help="env JEV_PORT (default 8077)"
    )
    ap.add_argument(
        "--mode",
        choices=("shared", "direct"),
        default=None,
        help="env JEV_MODE (default shared)",
    )
    ap.add_argument(
        "--max-questions",
        dest="max_questions",
        type=int,
        default=None,
        help="env JEV_MAX_QUESTIONS (default 32)",
    )
    args = ap.parse_args()
    if args.gguf:
        if args.backend and args.backend != "llamacpp":
            ap.error("--gguf requires the llamacpp backend")
        if args.endpoint:
            ap.error("use either --endpoint or --gguf")
        args.backend = "llamacpp"
        args.endpoint = args.gguf

    host = args.host or os.environ.get("JEV_HOST", "127.0.0.1")
    try:
        port = (
            args.port
            if args.port is not None
            else int(os.environ.get("JEV_PORT", "8077"))
        )
        if not 0 <= port <= 65535:
            raise ValueError("port must be between 0 and 65535")
        server = build_server_from_env(args)
    except ImportError as error:
        ap.exit(2, f"{error}\nInstall a backend with bash scripts/setup.sh.\n")
    except (ValueError, RuntimeError, OSError) as error:
        ap.exit(2, f"{error}\n")
    api_key = os.environ.get("JEV_API_KEY") or None
    try:
        app = ThreadingHTTPServer((host, port), make_handler(server, api_key))
    except OSError as error:
        ap.exit(2, f"Cannot listen on {host}:{port}: {error}\n")
    logger.info(
        "serving %s on http://%s:%d (POST /v1/systemone, auth %s)",
        server.label,
        host,
        app.server_port,
        "on" if api_key else "off",
    )
    try:
        app.serve_forever()
    except KeyboardInterrupt:
        logger.info("shutting down")
    finally:
        app.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
