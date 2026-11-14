#!/usr/bin/env bash
# Set (or change) the studio password and connect an authenticator app.
#   ./setup_auth.sh             interactive setup
#   ./setup_auth.sh logout-all  sign out every browser
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
cd "$DIR"
PY="${POKOSOMO_VENV:-$DIR/.venv}/bin/python"
if [[ ! -x "$PY" ]]; then
  echo "Pokosomo's Python environment is missing. Run ./scripts/install_deps.sh first." >&2
  exit 1
fi
exec "$PY" -m server.auth "${1:-setup}"
