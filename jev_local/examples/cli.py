"""Run the feed, soundscape, and pet examples."""

import argparse
import json
import os
from pathlib import Path
import sys

from ..client import decide
from ..protocol import build_rows
from .feed import feed_request, feed_result
from .soundscape import soundscape_request, render_soundscape
from .pet import load_memory, pet_request, save_memory, REACTIONS


def emit(value):
    print(json.dumps(value, indent=2, ensure_ascii=False))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    feed = commands.add_parser("feed", help="rank posts from a JSON array")
    feed.add_argument("input", type=Path)
    feed.add_argument(
        "--interests", default="Practical local AI, reproducible results, little hype"
    )
    sound = commands.add_parser(
        "soundscape", help="choose and render a procedural WAV preview"
    )
    sound.add_argument("brief")
    sound.add_argument(
        "--output", type=Path, default=Path("private/examples/soundscape.wav")
    )
    sound.add_argument(
        "--seconds", type=int, choices=range(1, 121), default=15, metavar="1-120"
    )
    pet = commands.add_parser(
        "pet", help="interact once with a pet that remembers recent turns"
    )
    pet.add_argument("message")
    pet.add_argument("--memory", type=Path, default=Path("private/examples/pet.json"))
    for command in (feed, sound, pet):
        command.add_argument(
            "--url", default=os.environ.get("JEV_URL", "http://127.0.0.1:8077")
        )
        command.add_argument(
            "--dry-run",
            action="store_true",
            help="print requests without inference or writes",
        )
    args = parser.parse_args(argv)
    try:
        if args.command == "feed":
            items = json.loads(args.input.read_text())
            if (
                not isinstance(items, list)
                or not 1 <= len(items) <= 100
                or any(
                    not isinstance(item, dict)
                    or not isinstance(item.get("text"), str)
                    or not item["text"].strip()
                    or len(item["text"]) > 3000
                    for item in items
                )
            ):
                raise ValueError(
                    "feed must contain 1–100 objects with nonempty text up to 3000 characters"
                )
            if not args.interests.strip() or len(args.interests) > 1000:
                raise ValueError("interests must contain 1–1000 characters")
            payloads = [feed_request(item, args.interests) for item in items]
        elif args.command == "soundscape":
            if not args.brief.strip() or len(args.brief) > 1000:
                raise ValueError("brief must contain 1–1000 characters")
            if not args.dry_run and args.output.exists():
                raise ValueError(
                    f"output already exists: {args.output}; choose a new --output"
                )
            payloads = [soundscape_request(args.brief)]
        else:
            if not args.message.strip() or len(args.message) > 500:
                raise ValueError("message must contain 1–500 characters")
            memory = load_memory(args.memory)
            payloads = [pet_request(args.message, memory)]
        for payload in payloads:
            build_rows(payload)
        if args.dry_run:
            emit(payloads if args.command == "feed" else payloads[0])
            return 0
        results = [
            decide(payload, args.url, os.environ.get("JEV_API_KEY"))
            for payload in payloads
        ]
        if args.command == "feed":
            ranked = [
                feed_result(item, result["answers"])
                for item, result in zip(items, results)
            ]
            emit(sorted(ranked, key=lambda item: item["rank_score"], reverse=True))
        elif args.command == "soundscape":
            plan = {
                key: answer["choice"]
                for key, answer in results[0]["answers"].items()
                if key in payloads[0]["questions"]
            }
            render_soundscape(plan, args.output, args.seconds)
            emit(
                {
                    "plan": plan,
                    "output": str(args.output.resolve()),
                    "decision": results[0],
                }
            )
        else:
            answers = results[0]["answers"]
            action = answers["action"]["choice"]
            memory = {
                "mood": answers["mood"]["choice"],
                "history": (
                    memory["history"] + [{"message": args.message, "action": action}]
                )[-5:],
            }
            save_memory(args.memory, memory)
            emit(
                {
                    "reaction": REACTIONS[action],
                    "memory": memory,
                    "decision": results[0],
                }
            )
        return 0
    except (OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
