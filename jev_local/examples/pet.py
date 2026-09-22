"""A text pet with bounded, persistent interaction history."""

import json
import os
import tempfile

from .questions import choice

MOODS = {
    "curious": "Interested and attentive",
    "happy": "Content and playful",
    "sleepy": "Tired and ready to rest",
    "wary": "Cautious after an unpleasant interaction",
}


ACTIONS = {
    "play": "Play with a toy",
    "nap": "Curl up and sleep",
    "approach": "Come closer to the person",
    "hide": "Retreat to a safe corner",
    "watch": "Watch quietly",
}


REACTIONS = {
    "play": "Your pet bats a wooden ball across the floor.",
    "nap": "Your pet curls up and closes its eyes.",
    "approach": "Your pet shuffles closer and leans against you.",
    "hide": "Your pet slips behind its little house.",
    "watch": "Your pet tilts its head and watches you.",
}


def load_memory(path):
    if not path.exists():
        return {"mood": "curious", "history": []}
    memory = json.loads(path.read_text())
    if (
        not isinstance(memory, dict)
        or not isinstance(memory.get("mood"), str)
        or memory["mood"] not in MOODS
        or not isinstance(memory.get("history"), list)
        or len(memory["history"]) > 5
    ):
        raise ValueError("invalid pet memory; choose a new --memory path to start over")
    for event in memory["history"]:
        if (
            not isinstance(event, dict)
            or not isinstance(event.get("message"), str)
            or len(event["message"]) > 500
            or not isinstance(event.get("action"), str)
            or event["action"] not in ACTIONS
        ):
            raise ValueError("invalid event in pet memory")
    return memory


def pet_request(message, memory):
    return {
        "state": {
            "character": "A small, curious woodland pet. React to the latest interaction, "
            "taking recent experiences into account.",
            "memory": memory,
            "message": message,
        },
        "questions": {
            "mood": choice("How does the pet feel after this interaction?", MOODS),
            "action": choice(
                "What should the pet do next, given this interaction and memory?",
                ACTIONS,
            ),
        },
    }


def save_memory(path, memory):
    path.parent.mkdir(parents=True, exist_ok=True)
    # A failed write should leave the previous session intact.
    name = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", dir=path.parent, delete=False
        ) as file:
            name = file.name
            json.dump(memory, file, indent=2)
            file.write("\n")
        os.replace(name, path)
    finally:
        if name and os.path.exists(name):
            os.unlink(name)
