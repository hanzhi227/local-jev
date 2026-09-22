# Local use cases

Start `.venv/bin/jev` in one terminal, then run the commands below from the
checkout in another. Only the Python standard library is needed by the clients.
The server needs the inference backend from the main setup instructions.

All commands support `--dry-run` (print the actual request, no inference or
writes) and `--url http://127.0.0.1:8077`. `JEV_URL` sets the default URL;
`JEV_API_KEY` supplies the bearer token if the server requires one. A custom URL
receives the supplied input and, for the pet, its recent memory. Requests time
out after 120 seconds and errors exit with status 1; there are no fake model
answers or automatic retries.

## Feed filter

```sh
.venv/bin/python -m jev_local.examples feed examples/feed.json \
  --interests "Practical local AI, reproducible results, little hype"
```

Provide a JSON array of objects, each with a nonempty `text` field. Optional
fields such as `title` and `url` are preserved. Up to 100 posts are processed
sequentially, one request per post, with three questions sharing that post's
state. Posts should stay short (at most 3,000 text characters).

The command prints all posts in ranked order, with raw answers and a suggested
`highlight`, `skim`, or `collapse` treatment. It never removes content. The
ranking formula is relevance (0–2) + substance (0–2) − 2 × promotion (0–1).
The cutoffs are illustrative preferences, not calibrated confidence thresholds.
Tune them against posts you have labeled yourself. Output is JSON and can be
redirected to a file or consumed by another application.

## Soundscape selector

```sh
.venv/bin/python -m jev_local.examples soundscape \
  "Soft ocean surf with a warm drone" \
  --seconds 30 --output private/examples/ocean.wav
afplay private/examples/ocean.wav  # macOS; other platforms can use a WAV player
```

Jev chooses a texture, intensity, and tonal layer. Python synthesizes a mono
22,050 Hz, 16-bit WAV with a fade at each end. The textures are basic procedural
rain, ocean, wind, and fireplace approximations, plus silence. Tonal choices
are none, warm, or eerie. This is a small audible demo, not a library of realistic
field recordings; unsupported requests are mapped to the closest available
option. The same plan always produces the same audio.

Duration is 1–120 seconds (15 by default). Existing files are never overwritten;
choose a fresh output path for each preview. The printed result includes the
plan, absolute file path, and complete decision response. Playback is manual.
To integrate with an audio app, reuse `soundscape_request()` and map its choices
to the app's existing loops instead of the demonstration synthesizer.

## Pet with memory

```sh
.venv/bin/python -m jev_local.examples pet "I bring you a toy and sit nearby."
.venv/bin/python -m jev_local.examples pet "I step back and give you space."
```

Each invocation is one interaction. Jev chooses a mood and an action; the
program displays a handwritten reaction and saves the mood plus the last five
message/action pairs to `private/examples/pet.json`. Messages are limited to
500 characters. Memory is supplied in the next request, so it persists across
processes without model training or server-side sessions.

Use `--memory private/examples/another-pet.json` for a separate pet or a fresh
start. Memory updates happen only after a successful, validated response and
use atomic replacement. Run one interaction at a time for each memory file.
This is a text demo; there are no animations, background monitoring, or generated
dialogue. Recent messages are stored in plain text in the memory file.

## Scope and validation

These examples target this repo's local API. They do not assume hosted Jev's
latency, quality, or calibration. Keep state compact: the server's 4,096-token
limit still applies, including questions and any extra post metadata. A length
error should be addressed by shortening the input.

Tests exercise all three workflows through a local HTTP server with a fake
scorer, plus ranking rules, WAV validity, authentication errors, failed memory
updates, and dry runs. They test integration, not model judgment quality:

```sh
.venv/bin/python -m unittest discover -s tests -v
```
