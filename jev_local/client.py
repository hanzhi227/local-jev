"""Dependency-free HTTP client shared by examples and benchmarks."""

import json
import math
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .protocol import build_rows


def decide(payload, url, api_key=None, timeout=120):
    build_rows(payload)
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = Request(
        url.rstrip("/") + "/v1/systemone",
        data=json.dumps(payload).encode(),
        headers=headers,
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            result = json.load(response)
    except HTTPError as error:
        raise ValueError(
            f"server returned HTTP {error.code}: {error.read().decode()[:500]}"
        ) from error
    except URLError as error:
        raise ValueError(
            f"cannot reach {url}; start jev first ({error.reason})"
        ) from error
    validate_answers(payload, result)
    return result


def validate_answers(payload, result):
    """Reject malformed outputs before writing files or advancing the pet's memory."""
    answers = result.get("answers") if isinstance(result, dict) else None
    if not isinstance(answers, dict):
        raise ValueError("server response is missing answers")
    for key, question in payload["questions"].items():
        answer = answers.get(key)
        kind = question["type"]
        if not isinstance(answer, dict) or answer.get("type") != kind:
            raise ValueError(f"invalid answer for {key}")
        if kind == "choice":
            if (
                not isinstance(answer.get("choice"), str)
                or answer["choice"] not in question["criteria"]
            ):
                raise ValueError(f"unknown choice for {key}")
        else:
            value = answer.get(kind)
            upper = 1 if kind == "noul" else len(question["criteria"]) - 1
            if (
                type(value) not in (int, float)
                or not math.isfinite(value)
                or not 0 <= value <= upper
            ):
                raise ValueError(f"invalid {kind} for {key}")
