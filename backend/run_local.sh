#!/usr/bin/env bash
#
# Local-dev launcher for the CoreRipper backend, used by .claude/launch.json.
#
# Local dev only. The VPS runs gunicorn under systemd (coreripper-backend.service)
# behind nginx on a Unix socket - never start the live site this way, it dies with
# the SSH session that launched it (see the 2026-07-30 outage note in CLAUDE.md).
#
# The interpreter is resolved at run time rather than hardcoded. CLAUDE.md documents
# /home/clive/anaconda3/bin/python, but that install is gone from this box, so a
# hardcoded path is how this breaks again. Override with $CORERIPPER_PYTHON.
set -euo pipefail

cd "$(dirname "$0")"

pick_python() {
    local candidates=(
        "${CORERIPPER_PYTHON:-}"
        "./venv/bin/python"
        "../venv/bin/python"
        "$HOME/venv/bin/python"
        "/home/clive/anaconda3/bin/python"
        "$(command -v python3 || true)"
    )
    local p
    for p in "${candidates[@]}"; do
        [ -n "$p" ] && [ -x "$p" ] || continue
        if "$p" -c 'import django' 2>/dev/null; then
            printf '%s\n' "$p"
            return 0
        fi
    done
    return 1
}

if ! PY="$(pick_python)"; then
    cat >&2 <<'EOF'
run_local.sh: no Python with Django installed was found.

Tried, in order: $CORERIPPER_PYTHON, ./venv, ../venv, ~/venv,
the anaconda path in CLAUDE.md, and python3 on PATH.

Create one with:
    python3 -m venv venv && ./venv/bin/pip install -r requirements.txt

Or point at an existing interpreter:
    CORERIPPER_PYTHON=/path/to/python bash backend/run_local.sh
EOF
    exit 1
fi

echo "run_local.sh: $PY ($("$PY" -c 'import django; print("Django", django.get_version())'))"

exec "$PY" manage.py runserver "${PORT:-8000}"
