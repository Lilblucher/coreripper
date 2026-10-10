#!/usr/bin/env bash
#
# Local-dev launcher for the CoreRipper static frontend, used by .claude/launch.json.
#
# The `cd` is load-bearing, not tidiness. _nocache_server.py wraps http.server,
# which serves the CURRENT WORKING DIRECTORY - so launching it from the repo root
# would publish backend/ (including .env) and .git/ over HTTP, not just frontend/.
# Always enter frontend/ first; everything below this line serves from here.
#
# Only stdlib http.server is used, so any python3 works - no venv needed, unlike
# backend/run_local.sh.
set -euo pipefail

cd "$(dirname "$0")"

echo "run_local.sh: serving $(pwd) on port ${PORT:-5501} (no-store cache headers)"

exec python3 _nocache_server.py "${PORT:-5501}"
