#!/usr/bin/env bash
# Install the local server as a per-user macOS login service.
set -euo pipefail
PROJECT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PLIST_DST="$HOME/Library/LaunchAgents/com.jev.serve.plist"
LABEL=com.jev.serve
[[ "$(uname -s)" == Darwin ]] || { echo 'launchd requires macOS' >&2; exit 2; }
case "${1:-install}" in
    uninstall)
        launchctl bootout "gui/$(id -u)" "$PLIST_DST" 2>/dev/null || true
        rm -f "$PLIST_DST"
        echo "uninstalled $LABEL"
        exit 0 ;;
    install) ;;
    *) echo 'Usage: bash deploy/install_launchd.sh [install|uninstall]' >&2; exit 2 ;;
esac
[[ -x "$PROJECT/.venv/bin/python" ]] || { echo 'Run bash scripts/setup.sh first.' >&2; exit 1; }
mkdir -p "$PROJECT/private/logs" "$HOME/Library/LaunchAgents"
GENERATED="$(mktemp)"
trap 'rm -f "$GENERATED"' EXIT
"$PROJECT/.venv/bin/python" - "$PROJECT" "$GENERATED" <<'PY'
import os
import plistlib
import sys
from pathlib import Path
project, output = Path(sys.argv[1]), Path(sys.argv[2])
env = {k: v for k, v in os.environ.items() if k.startswith('JEV_')}
plist = {
    'Label': 'com.jev.serve',
    'ProgramArguments': [str(project / '.venv/bin/python'), str(project / 'scripts/serve_jev.py')],
    'WorkingDirectory': str(project),
    'EnvironmentVariables': env,
    'RunAtLoad': True,
    'KeepAlive': {'SuccessfulExit': False},
    'StandardOutPath': str(project / 'private/logs/jev-serve.log'),
    'StandardErrorPath': str(project / 'private/logs/jev-serve.err.log'),
    'ProcessType': 'Interactive',
}
output.write_bytes(plistlib.dumps(plist))
PY
launchctl bootout "gui/$(id -u)" "$PLIST_DST" 2>/dev/null || true
install -m 600 "$GENERATED" "$PLIST_DST"
launchctl bootstrap "gui/$(id -u)" "$PLIST_DST"
echo "installed and started $LABEL"
echo "logs: $PROJECT/private/logs/jev-serve.log"
echo "check: curl http://127.0.0.1:${JEV_PORT:-8077}/ready"
