#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd -P)"
cd "$DIR"

PORT="${PORT:-8001}"
HOST="${HOST:-0.0.0.0}"
VENV="${POKOSOMO_VENV:-$DIR/.venv}"
PY="$VENV/bin/python"
UVICORN="$VENV/bin/uvicorn"

if [[ ! "$PORT" =~ ^[0-9]+$ ]] || (( PORT < 1 || PORT > 65535 )); then
  echo "PORT must be a number from 1 to 65535 (received: $PORT)." >&2
  exit 2
fi

if [[ ! -x "$PY" || ! -x "$UVICORN" ]]; then
  echo "Pokosomo's Python environment is missing. Run ./scripts/install_deps.sh first." >&2
  exit 1
fi

# Login must be configured before the studio is reachable.
if ! "$PY" -m server.auth status | grep -q "^Login configured"; then
  if [ -t 0 ]; then
    echo "Sign-in is not set up yet — let's do that first."
    "$PY" -m server.auth setup
  else
    echo "Sign-in is not set up. Run ./setup_auth.sh first (the site will only show a 'not set up' notice)." >&2
  fi
fi

# If this studio was left running, stop only that same app in this folder.
if ! command -v lsof >/dev/null 2>&1; then
  echo "Cannot check whether port $PORT is already in use (lsof is missing)." >&2
  echo "Run ./scripts/install_deps.sh, or use the Windows start.bat launcher." >&2
  exit 1
fi
mapfile -t LISTENERS < <(lsof -nP -t -iTCP:"$PORT" -sTCP:LISTEN 2>/dev/null | sort -u)
for pid in "${LISTENERS[@]}"; do
  cmd="$(ps -p "$pid" -o args= 2>/dev/null || true)"
  cwd="$(readlink -f "/proc/$pid/cwd" 2>/dev/null || true)"
  if [[ "$cwd" != "$DIR" || "$cmd" != *"server.app:app"* || "$cmd" != *"--port $PORT"* ]]; then
    echo "Port $PORT is already in use by another program (PID $pid). It was left running." >&2
    echo "Stop that program or choose another port with PORT=8080 ./run.sh." >&2
    exit 1
  fi
done
for pid in "${LISTENERS[@]}"; do
  echo "Stopping the previous Pokosomo server on port $PORT..."
  kill "$pid"
done
for pid in "${LISTENERS[@]}"; do
  for _ in {1..50}; do
    current="$(lsof -nP -t -iTCP:"$PORT" -sTCP:LISTEN 2>/dev/null || true)"
    grep -qx "$pid" <<<"$current" || break
    sleep 0.1
  done
  current="$(lsof -nP -t -iTCP:"$PORT" -sTCP:LISTEN 2>/dev/null || true)"
  if grep -qx "$pid" <<<"$current"; then
    echo "The previous Pokosomo server (PID $pid) did not stop. Close it and retry." >&2
    exit 1
  fi
done

echo "=========================================================="
echo "  Pokosomo Studio"
echo "  Projects: $DIR/workspace"
echo "  URL:      http://localhost:$PORT"
echo "=========================================================="

# --proxy-headers lets a reverse proxy (Caddy/nginx/Cloudflare) report HTTPS so cookies get the Secure flag.
exec "$UVICORN" server.app:app --host "$HOST" --port "$PORT" \
  --proxy-headers --forwarded-allow-ips="${FORWARDED_ALLOW_IPS:-127.0.0.1}"
