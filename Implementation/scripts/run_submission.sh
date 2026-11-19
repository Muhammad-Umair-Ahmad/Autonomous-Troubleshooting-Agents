#!/bin/sh
set -eu
NETA_PROJECT_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$NETA_PROJECT_ROOT"
export DYLD_LIBRARY_PATH="/opt/homebrew/opt/expat/lib${DYLD_LIBRARY_PATH:+:$DYLD_LIBRARY_PATH}"
export MPLCONFIGDIR="$NETA_PROJECT_ROOT/.cache/matplotlib"
export XDG_CACHE_HOME="$NETA_PROJECT_ROOT/.cache"
export PYTHONUNBUFFERED=1
exec "$NETA_PROJECT_ROOT/.venv/bin/python" "$NETA_PROJECT_ROOT/scripts/submission.py" "$@"
