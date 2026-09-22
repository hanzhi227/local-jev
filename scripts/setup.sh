#!/usr/bin/env bash
set -euo pipefail
PROJECT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND="${1:-auto}"
if [[ "$BACKEND" == auto ]]; then
    if [[ "$(uname -s)" == Darwin && "$(uname -m)" == arm64 ]]; then
        BACKEND=mlx
    else
        BACKEND=llamacpp
    fi
fi
case "$BACKEND" in
    mlx|llamacpp) ;;
    *) echo 'Usage: bash scripts/setup.sh [auto|mlx|llamacpp]' >&2; exit 2 ;;
esac
if [[ "$BACKEND" == mlx && ( "$(uname -s)" != Darwin || "$(uname -m)" != arm64 ) ]]; then
    echo 'MLX requires an Apple Silicon Mac. Use llamacpp on this hardware.' >&2
    exit 2
fi
command -v uv >/dev/null || { echo 'Install uv: https://docs.astral.sh/uv/' >&2; exit 1; }
if [[ ! -x "$PROJECT/.venv/bin/python" ]]; then
    uv venv "$PROJECT/.venv" --python 3.12
fi
uv pip install --python "$PROJECT/.venv/bin/python" -e "$PROJECT[$BACKEND]"
echo "Start: $PROJECT/.venv/bin/jev --backend $BACKEND"
