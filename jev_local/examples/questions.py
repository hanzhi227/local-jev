"""Small helpers for typed question definitions."""


def choice(instructions, options):
    return {"type": "choice", "instructions": instructions, "criteria": options}


def score(instructions, levels):
    return {"type": "score", "instructions": instructions, "criteria": levels}
