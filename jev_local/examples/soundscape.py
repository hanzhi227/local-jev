"""Select a soundscape and synthesize a procedural WAV preview."""

from array import array
import math
import random
import sys
import wave

from .questions import choice


def soundscape_request(brief):
    return {
        "state": brief,
        "questions": {
            "texture": choice(
                "Choose the closest available background texture for the request.",
                {
                    "rain": "Steady rain-like noise",
                    "ocean": "Slow rolling surf",
                    "wind": "Soft low wind",
                    "fire": "Crackling fireplace",
                    "quiet": "No background texture",
                },
            ),
            "intensity": choice(
                "Choose the requested background intensity.",
                {
                    "soft": "Quiet and unobtrusive",
                    "medium": "Clearly present",
                    "strong": "Immersive and prominent",
                },
            ),
            "tone": choice(
                "Choose a tonal layer; use none unless music or an eerie tone is wanted.",
                {
                    "none": "No musical layer",
                    "warm": "A gentle consonant drone",
                    "eerie": "A low dissonant drone",
                },
            ),
        },
    }


def render_soundscape(plan, path, seconds):
    """Render a modest procedural preview, not recordings or model-generated audio."""
    if not 1 <= seconds <= 120:
        raise ValueError("seconds must be between 1 and 120")
    rate = 22050
    rng = random.Random(7)
    low = crackle = 0.0
    amplitude = {"soft": 0.12, "medium": 0.25, "strong": 0.4}[plan["intensity"]]
    frequencies = {"none": (), "warm": (110, 165), "eerie": (82.41, 87.31)}[
        plan["tone"]
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation prevents accidentally overwriting an existing recording.
    with path.open("xb") as stream, wave.open(stream, "wb") as output:
        output.setparams((1, 2, rate, 0, "NONE", "not compressed"))
        for second in range(seconds):
            samples = array("h")
            for offset in range(rate):
                t = second + offset / rate
                noise = rng.uniform(-1, 1)
                low = 0.98 * low + 0.02 * noise
                crackle = crackle * 0.9 + (noise if rng.random() < 0.001 else 0)
                texture = {
                    "rain": noise * 0.45 + low,
                    "ocean": low * 4 * (0.6 + 0.4 * math.sin(t * 0.8)),
                    "wind": low * 3,
                    "fire": low + crackle,
                    "quiet": 0,
                }[plan["texture"]]
                drone = sum(math.sin(2 * math.pi * hz * t) for hz in frequencies) * 0.12
                fade = max(0, min(1, t, seconds - t))
                value = max(-1, min(1, (texture + drone) * amplitude * fade))
                samples.append(round(value * 32767))
            if sys.byteorder != "little":
                samples.byteswap()
            output.writeframes(samples.tobytes())
