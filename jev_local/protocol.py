"""Translate the JEV wire format into SemIf decision rows."""

import json


def build_rows(request, max_questions=32):
    if not isinstance(request, dict):
        raise ValueError("request must be a JSON object")
    state = request.get("state")
    if not isinstance(state, (str, dict, list)) or not state:
        raise ValueError("state must be a nonempty string, object, or array")
    try:
        json.dumps(state, allow_nan=False)
    except (TypeError, ValueError) as error:
        raise ValueError("state must contain finite JSON values") from error
    questions = request.get("questions")
    if not isinstance(questions, dict) or not 1 <= len(questions) <= max_questions:
        raise ValueError(
            f"questions must be an object containing 1–{max_questions} questions"
        )
    rows = []
    for key, question in questions.items():
        if not isinstance(key, str) or not key or not isinstance(question, dict):
            raise ValueError("each question needs a nonempty key and an object value")
        instructions = question.get("instructions")
        if not isinstance(instructions, str) or not instructions.strip():
            raise ValueError(f"{key}: instructions must be a nonempty string")
        qtype, criteria = question.get("type"), question.get("criteria")
        if qtype == "noul":
            if criteria is not None and (
                not isinstance(criteria, dict)
                or any(
                    k not in ("true", "false") or not isinstance(v, str)
                    for k, v in criteria.items()
                )
            ):
                raise ValueError(
                    f"{key}: noul criteria may contain true/false descriptions"
                )
            options = [
                (k, (criteria or {}).get(k, f"The proposition is {k}."))
                for k in ("true", "false")
            ]
        elif qtype == "choice":
            if (
                not isinstance(criteria, dict)
                or not 2 <= len(criteria) <= 16
                or any(
                    not isinstance(k, str) or not k or not isinstance(v, str)
                    for k, v in criteria.items()
                )
            ):
                raise ValueError(
                    f"{key}: choice criteria needs 2–16 named string descriptions"
                )
            options = [(k, v or k) for k, v in criteria.items()]
        elif qtype == "score":
            if (
                not isinstance(criteria, list)
                or not 2 <= len(criteria) <= 16
                or any(not isinstance(v, str) for v in criteria)
            ):
                raise ValueError(
                    f"{key}: score criteria needs 2–16 ordered string levels"
                )
            options = [(str(i), v) for i, v in enumerate(criteria)]
        else:
            raise ValueError(f"{key}: type must be noul, choice, or score")
        rows.append(
            {
                "id": key,
                "state": state,
                "question": instructions,
                "options": [{"id": k, "description": f"{k}: {v}"} for k, v in options],
            }
        )
    return rows


def format_answer(question: dict, probabilities: dict) -> dict:
    """Map native option probabilities to the JEV response shape."""
    qtype = question["type"]
    if qtype == "noul":
        return {"type": qtype, "noul": float(probabilities["true"])}
    probs = {key: float(value) for key, value in probabilities.items()}
    answer = {"type": qtype, "probabilities": probs, "confidence": max(probs.values())}
    if qtype == "choice":
        answer["choice"] = max(probs, key=probs.get)
    else:
        answer["score"] = sum(int(key) * value for key, value in probs.items())
        answer["legend"] = {
            str(i): level for i, level in enumerate(question["criteria"])
        }
    return answer
