"""Measure typed decision quality and serial HTTP latency."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import sys
import time

from ..client import decide
from ..protocol import build_rows

DATA = Path(__file__).parent / "data"


def load_cases(paths):
    cases, fingerprints, seen = [], [], set()
    for path in paths:
        raw = path.read_bytes()
        fingerprints.append(
            {"file": path.name, "sha256": hashlib.sha256(raw).hexdigest()}
        )
        for line_number, line in enumerate(raw.splitlines(), 1):
            if not line.strip():
                continue
            row = json.loads(line)
            if (
                not isinstance(row, dict)
                or not isinstance(row.get("id"), str)
                or not row["id"]
            ):
                raise ValueError(f"{path}:{line_number}: missing case id")
            if row["id"] in seen:
                raise ValueError(f"duplicate case id: {row['id']}")
            seen.add(row["id"])
            build_rows(
                {"state": row.get("state"), "questions": {"q": row.get("question")}}
            )
            q = row["question"]
            expected = row.get("expected")
            if q["type"] == "noul":
                valid = isinstance(expected, str) and expected in ("yes", "no")
            elif q["type"] == "choice":
                valid = isinstance(expected, str) and expected in q["criteria"]
            else:
                valid = type(expected) is int and 0 <= expected < len(q["criteria"])
            if not valid:
                raise ValueError(f"{row['id']}: expected label does not match question")
            # Only state and question go to the server. Gold labels and rationales stay here.
            cases.append({**row, "tier": path.stem})
    if not cases:
        raise ValueError("dataset is empty")
    return cases, fingerprints


def evaluate(case, answer):
    kind = case["question"]["type"]
    expected = str(case["expected"])
    if kind == "noul":
        p = answer["noul"]
        probs = {"no": 1 - p, "yes": p}
    else:
        labels = (
            list(case["question"]["criteria"])
            if kind == "choice"
            else [str(i) for i in range(len(case["question"]["criteria"]))]
        )
        probs = answer.get("probabilities")
        if not isinstance(probs, dict) or set(probs) != set(labels):
            raise ValueError("missing or mismatched probability labels")
        if any(
            type(p) not in (int, float) or not math.isfinite(p) or not 0 <= p <= 1
            for p in probs.values()
        ):
            raise ValueError("invalid probability")
        if not math.isclose(sum(probs.values()), 1, abs_tol=1e-5):
            raise ValueError("probabilities do not sum to one")
        # Preserve the declared option order as the deterministic tie-break.
        probs = {label: probs[label] for label in labels}
        if kind == "choice" and probs[answer["choice"]] < max(probs.values()):
            raise ValueError("choice disagrees with probabilities")
        if kind == "score" and not math.isclose(
            answer["score"], sum(int(k) * p for k, p in probs.items()), abs_tol=1e-5
        ):
            raise ValueError("score disagrees with probabilities")
    predicted = max(probs, key=probs.get)
    return {
        "predicted": predicted,
        "expected": expected,
        "correct": predicted == expected,
        "confidence": probs[predicted],
        "brier": sum((p - (label == expected)) ** 2 for label, p in probs.items()),
        "score_absolute_error": abs(answer["score"] - case["expected"])
        if kind == "score"
        else None,
    }


def percentile(values, fraction):
    return (
        sorted(values)[max(0, math.ceil(len(values) * fraction) - 1)]
        if values
        else None
    )


def summarize(rows):
    good = [row for row in rows if "error" not in row]
    scores = [
        row["score_absolute_error"]
        for row in good
        if row["score_absolute_error"] is not None
    ]
    ece = 0.0
    for bin_id in range(10):
        bucket = [row for row in good if min(9, int(row["confidence"] * 10)) == bin_id]
        if bucket:
            ece += abs(sum(row["correct"] - row["confidence"] for row in bucket)) / len(
                good
            )
    return {
        "attempts": len(rows),
        "successful": len(good),
        "failures": len(rows) - len(good),
        "accuracy": sum(row["correct"] for row in good) / len(rows) if rows else None,
        "brier_successful": sum(row["brier"] for row in good) / len(good)
        if good
        else None,
        "ece_10_bins_successful": ece if good else None,
        "score_mae_successful": sum(scores) / len(scores) if scores else None,
        "latency_s": {
            "p50": percentile([r["wall_s"] for r in rows], 0.5),
            "p95": percentile([r["wall_s"] for r in rows], 0.95),
        },
    }


def run(cases, output, url, api_key, repeat, warmup, timeout, metadata):
    output.mkdir(parents=True, exist_ok=False)
    metadata = {
        **metadata,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "python": platform.python_version(),
        "client_platform": platform.platform(),
        "repeat": repeat,
        "warmup_requests": warmup,
        "case_ids": [case["id"] for case in cases],
        "status": "running",
    }
    manifest = output / "manifest.json"
    manifest.write_text(json.dumps(metadata, indent=2) + "\n")
    def payload(case):
        return {"state": case["state"], "questions": {"q": case["question"]}}
    try:
        for i in range(warmup):
            decide(payload(cases[i % len(cases)]), url, api_key, timeout=timeout)
    except (ValueError, OSError) as error:
        metadata.update(status="warmup_failed", error=str(error))
        manifest.write_text(json.dumps(metadata, indent=2) + "\n")
        raise
    rows = []
    started = time.perf_counter()
    with (output / "results.jsonl").open("x") as log:
        for iteration in range(repeat):
            for case in cases:
                row = {
                    "id": case["id"],
                    "tier": case["tier"],
                    "type": case["question"]["type"],
                    "iteration": iteration,
                }
                t0 = time.perf_counter()
                try:
                    response = decide(payload(case), url, api_key, timeout=timeout)
                    row["wall_s"] = time.perf_counter() - t0
                    row["response"] = response
                    row.update(evaluate(case, response["answers"]["q"]))
                except (ValueError, OSError) as error:
                    row.setdefault("wall_s", time.perf_counter() - t0)
                    row["error"] = str(error)
                rows.append(row)
                log.write(json.dumps(row, allow_nan=False) + "\n")
                log.flush()
                print(
                    f"\r{len(rows)}/{len(cases) * repeat} requests",
                    end="",
                    file=sys.stderr,
                    flush=True,
                )
    print(file=sys.stderr)
    elapsed = time.perf_counter() - started
    summary = {
        **summarize(rows),
        "elapsed_s": elapsed,
        "successful_decisions_per_s": sum("error" not in r for r in rows) / elapsed,
        "models": sorted(
            {
                str(r["response"].get("model", "unknown"))
                for r in rows
                if "response" in r
            }
        ),
        "by_tier": {
            tier: summarize([r for r in rows if r["tier"] == tier])
            for tier in sorted({r["tier"] for r in rows})
        },
        "by_type": {
            kind: summarize([r for r in rows if r["type"] == kind])
            for kind in sorted({r["type"] for r in rows})
        },
    }
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    metadata.update(
        status="completed", finished_at=datetime.now(timezone.utc).isoformat()
    )
    manifest.write_text(json.dumps(metadata, indent=2) + "\n")
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--suite", choices=("smoke", "public"), default="smoke")
    source.add_argument(
        "--dataset", type=Path, help="custom JSONL with id, state, question, expected"
    )
    parser.add_argument(
        "--url", default=os.environ.get("JEV_URL", "http://127.0.0.1:8077")
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("private/benchmarks")
        / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"),
    )
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--warmup", type=int, default=1)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument(
        "--label",
        default="",
        help="record server hardware/backend/quantization for comparisons",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="validate cases and print counts/hashes without requests or writes",
    )
    args = parser.parse_args(argv)
    try:
        if (
            args.repeat < 1
            or args.warmup < 0
            or (args.limit is not None and args.limit < 1)
            or not math.isfinite(args.timeout)
            or args.timeout <= 0
        ):
            raise ValueError(
                "repeat/limit/timeout must be positive; warmup must be nonnegative"
            )
        paths = (
            [args.dataset]
            if args.dataset
            else [
                DATA / (name + ".jsonl")
                for name in (
                    ("smoke",)
                    if args.suite == "smoke"
                    else ("easy", "original", "hard")
                )
            ]
        )
        cases, fingerprints = load_cases(paths)
        if args.limit:
            cases = cases[: args.limit]
        metadata = {
            "suite": "custom" if args.dataset else args.suite,
            "datasets": fingerprints,
            "label": args.label,
            "cases": len(cases),
            "limit": args.limit,
            "timeout_s": args.timeout,
        }
        if args.dry_run:
            print(json.dumps(metadata, indent=2))
            return 0
        summary = run(
            cases,
            args.output,
            args.url,
            os.environ.get("JEV_API_KEY"),
            args.repeat,
            args.warmup,
            args.timeout,
            metadata,
        )
        print(json.dumps({"output": str(args.output.resolve()), **summary}, indent=2))
        return 1 if summary["failures"] else 0
    except (ValueError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
