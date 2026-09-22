# Benchmark suite

Evaluate a running JEV-compatible server over HTTP. No model dependencies are
required in the benchmark client. Start the server using the root README, then:

```sh
.venv/bin/python -m jev_local.benchmarks --suite smoke
.venv/bin/python -m jev_local.benchmarks --suite public \
  --label "Apple Silicon, MLX 8-bit, shared, localhost"
```

`jev-bench` provides the same CLI after installation. `--url` / `JEV_URL` selects
the base URL and `JEV_API_KEY` supplies the bearer token. Inputs go only to that
endpoint; do not use a remote service for private custom cases unless intended.

## Datasets

| Suite | Cases | Purpose |
|---|---:|---|
| `smoke` (default) | 6 | Two cases per primitive, drawn from the public set |
| `public` | 231 | JevBench public easy (48), original (72), and hard (111) cases |

These are the MIT-licensed public files from the archived JevBench checkout,
copied unchanged into `jev_local/benchmarks/data/`. Each row retains its
provenance. The original copyright and license are in that directory's
`LICENSE`; `manifest.json` records source, counts, and SHA-256 hashes. The exact
upstream commit was not available, so the file hashes identify this snapshot.
The smoke file is a derived subset and must not be added to public-suite scores.

This runner is not the official JevBench leaderboard harness. It does not
include private cases, leaderboard weighting, cost estimates, or latency
adjustments. The public cases have already been used during local development;
they are regression/development data, not an independent held-out evaluation.

## Run controls and artifacts

```sh
# Validate all cases without model calls or writing results.
jev-bench --suite public --dry-run

# Repeat a small prefix for timing experiments.
jev-bench --suite public --limit 12 --repeat 3 --warmup 2 \
  --timeout 120 --output private/benchmarks/my-run
```

`--limit` takes the first N cases in easy/original/hard order; it is not a
representative sample. A repeat reruns the same cases in the same order and
counts each attempt in metrics. Default warm-up is one excluded request.
One question is sent per request, serially. This does **not** benchmark
multi-question shared-prefix acceleration or concurrent throughput.

Each run creates a new directory (existing directories are refused):

- `manifest.json`: timestamps, dataset hashes, ordered case IDs, repeat/warm-up
  counts, timeout, label, client platform/Python, and run status.
- `results.jsonl`: one record per measured attempt, raw response including model
  and usage, client wall time, prediction, gold label, metrics, or error.
- `summary.json`: aggregate results plus breakdowns by tier and question type.

Gold labels, provenance rationales, and other metadata are never sent to the
model. Only the case's state and question are sent. No silent truncation,
retries, or fallback predictions occur. A failed warm-up aborts and records
`warmup_failed`. Measured request failures are recorded and the remaining cases
continue; completed runs with failures exit 1. Successful runs exit 0 regardless
of accuracy, so this is a measurement tool rather than a quality gate.
An interrupted run keeps its flushed row log and `running` status; start a new
output directory for the next run.

## Metric definitions

- **Accuracy:** correct argmax decisions / all measured attempts. Failures count
  as incorrect. Noul maps to no/yes; score uses the most probable discrete level,
  not a rounded expected score. Ties use declared option order (no before yes).
- **Brier:** mean sum of squared differences between option probabilities and
  the one-hot gold label, on successful attempts only. Range 0–2, including for
  binary questions. Lower is better; this is not a gold-distribution metric.
- **ECE:** ten equal-width confidence bins, weighted absolute gap between
  accuracy and maximum option probability, on successful attempts only.
  Small samples are noisy; a smoke run cannot establish calibration.
- **Score MAE:** mean absolute difference between the returned expected score
  and the gold level, on successful score questions only.
- **p50/p95:** nearest-rank percentiles of client-observed HTTP request duration,
  including failed attempts. Excludes model startup, warm-up, file writes, and
  local metric computation. A fast error can lower these latency numbers; always
  read failure counts alongside them.
- **Throughput:** successful decisions / elapsed measured loop time, including
  client validation, metrics, and artifact writes. It is serial end-to-end throughput.

Absent metrics are `null`, never zero. Probabilities must be finite, normalized,
and cover exactly the declared options. Malformed results count as failures.
All types use hard gold labels; probabilistic ambiguity is not scored here.
Some hard cases may exceed the server's context limit and remain explicit errors.

For comparisons, hold dataset hashes, question ordering, limits, repetition,
warm-up, hardware, quantization, server mode, and network path constant. Use
`--label` to record server details: the automatically recorded platform belongs
to the **client**, which might be a different machine. Keys are not recorded.

## Custom JSONL

Use `--dataset /path/to/cases.jsonl` with one object per line:

```json
{"id":"shipped-1","state":"Order status: shipped.","question":{"type":"noul","instructions":"Has the order shipped?"},"expected":"yes"}
```

Required fields are `id` (unique nonempty string), `state`, `question`, and
`expected`. Noul gold labels are `"yes"`/`"no"`; choice labels are criteria keys;
score labels are zero-based integer levels. The request schema is the same as
the server's. The full dataset is validated before any requests or output writes.
