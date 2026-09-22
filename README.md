# JEV local

Host a JEV-compatible decision server on your own machine using
[SemIf](https://github.com/TheoLeeCJ/SemIf) and Qwen3.5-4B. Send text or structured
data with questions over HTTP and get typed answers with probabilities.
The repo includes runnable examples and a benchmark suite.

This is an independent implementation. It uses a different model from TypeSafe's
hosted Jev, so its speed, accuracy, and calibration will differ.

## Install

Install Git and [uv](https://docs.astral.sh/uv/), then run from the checkout:

```sh
bash scripts/setup.sh
.venv/bin/jev
```

On Apple Silicon, setup uses MLX with 8-bit quantization. The first run downloads
about 8.7 GB of weights and needs roughly 9 GB of memory while loading, then
4.5 GB while running. Use `jev --mlx-bits 4` to reduce running memory to about
2.4 GB. Loading still needs roughly 9 GB.

For CPU inference on macOS or Linux, use llama.cpp with a
[Qwen3.5-4B GGUF](https://huggingface.co/bartowski/Qwen_Qwen3.5-4B-GGUF):

```sh
bash scripts/setup.sh llamacpp
.venv/bin/jev --gguf /path/to/Qwen3.5-4B-Q4_K_S.gguf
```

Building llama.cpp may require CMake and a C/C++ compiler. It downloads the
reference tokenizer on first use. Both backends reuse cached files afterward.

For an existing Python 3.10+ environment, use
`pip install -e '.[mlx]'` or `pip install -e '.[llamacpp]'`.

## Send a request

The server listens on `127.0.0.1:8077`.

```sh
curl http://127.0.0.1:8077/ready
curl http://127.0.0.1:8077/v1/systemone \
  -H 'Content-Type: application/json' \
  --data-binary @examples/request.json
```

Requests contain `state` (a nonempty string, object, or array) and named
`questions`:

```json
{
  "state": "The application crashes when I sign in.",
  "questions": {
    "needs_engineer": {
      "type": "noul",
      "instructions": "Does this issue require an engineer?"
    }
  }
}
```

Each question has `instructions` and one of these types:

| Type | `criteria` | Answer |
|---|---|---|
| `noul` | Optional `true`/`false` descriptions | Probability of true |
| `choice` | Object of 2 to 16 named descriptions | Selected choice and probabilities |
| `score` | Array of 2 to 16 ordered descriptions | Expected zero-based score and probabilities |

Responses include `model`, `answers`, `usage`, and `latency_s`. The server selects
the model at startup and accepts the request's optional `model` field for
compatibility. Probabilities are relative to the supplied options;
`confidence` is the largest probability. The `score` type extends SemIf's option
scoring.

The server handles one request at a time and shares the state prefix across
questions. Default limits are 32 questions per request, a 1 MiB body, and a
4096-token context. The server rejects inputs that exceed these limits.

## Examples

Keep the server running and try an example in another terminal. These clients
need no extra dependencies:

```sh
# Rank posts by your interests, concrete detail, and promotional content.
.venv/bin/python -m jev_local.examples feed examples/feed.json

# Turn a brief into a procedural audio preview (writes a new WAV file).
.venv/bin/python -m jev_local.examples soundscape "Soft ocean surf with a warm drone"

# A small pet remembers its mood and the last five interactions.
.venv/bin/python -m jev_local.examples pet "I bring you a toy and sit nearby."
.venv/bin/python -m jev_local.examples pet "Want to play again?"
```

Add `--dry-run` to print the request without calling the model or writing files.
After installation, `jev-examples` is shorthand for `python -m jev_local.examples`.
The [examples guide](examples/README.md) covers custom inputs, audio playback,
pet memory, and limitations.

## Benchmarks

With the server running:

```sh
# Six cases covering all three answer types; one excluded warm-up request.
.venv/bin/python -m jev_local.benchmarks --suite smoke

# All 231 public JevBench cases, including the hard tier.
.venv/bin/python -m jev_local.benchmarks --suite public \
  --label "My Mac, MLX 8-bit, shared mode"
```

Results go in a new directory under `private/benchmarks/`. Each run saves raw
responses, dataset hashes, and configuration, plus accuracy, Brier score,
calibration error, score MAE, p50/p95 latency, throughput, and failure counts.

Use `jev-bench` as the installed shorthand, or add `--dry-run` to validate the
suite without a model. See [benchmark methodology](benchmarks/README.md) for
metric definitions, custom datasets, and comparison limits.

## Configuration and hosting

Run `.venv/bin/jev --help` for CLI flags. Flags override environment variables.

| Environment variable | Default |
|---|---|
| `JEV_BACKEND` | `mlx` on Apple Silicon, `llamacpp` elsewhere |
| `JEV_ENDPOINT` | `Qwen/Qwen3.5-4B` for MLX; local checkpoints also accepted |
| `JEV_GGUF` | `models/Qwen3.5-4B-Q4_K_S.gguf`, relative to the working directory |
| `JEV_MLX_BITS` | `8`; also supports `4` |
| `JEV_HOST` / `JEV_PORT` | `127.0.0.1` / `8077` |
| `JEV_MODE` | `shared`; also supports `direct` |
| `JEV_MAX_QUESTIONS` | `32` |
| `JEV_API_KEY` | Unset; when set, decisions require `Authorization: Bearer <key>` |

On macOS, `bash deploy/install_launchd.sh` installs a service that starts at
login, saves your `JEV_*` settings, and writes logs to `private/logs/`.
Run `bash deploy/install_launchd.sh uninstall` to remove it.

The [hosting guide](docs/hosting.md) covers macOS services, Linux systemd,
remote clients, and operating limits.

## Development

| Location | Contents |
|---|---|
| `jev_local/server.py`, `protocol.py` | Inference server and wire format |
| `jev_local/client.py` | Shared HTTP client |
| `jev_local/examples/` | Feed, soundscape, and pet implementations |
| `examples/` | Sample inputs and usage guide |
| `jev_local/benchmarks/` | Benchmark runner and licensed datasets |
| `benchmarks/` | Benchmark methodology and usage |
| `docs/`, `deploy/`, `scripts/` | Hosting docs, service installation, and setup |
| `tests/` | Unit and HTTP integration tests |

Git ignores local weights in `models/`, outputs in `private/`, and old experiments
in `archive/`. Installation does not need the archive or a local `third_party/`
checkout.

Tests use the standard library and do not load model weights:

```sh
python -m unittest discover -s tests -v
```

## License

[MIT](LICENSE). SemIf is an MIT-licensed dependency, pinned in `pyproject.toml`.
Model weights are downloaded separately and retain their upstream licenses.
The public JevBench cases use their [upstream MIT license](jev_local/benchmarks/data/LICENSE).
The [dataset manifest](jev_local/benchmarks/data/manifest.json) records their source and file hashes.
The Qwen weights and reference tokenizer use revision
`851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a`.
