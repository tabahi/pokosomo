#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

if ! command -v docker >/dev/null 2>&1 || ! docker compose version >/dev/null 2>&1; then
  echo "Docker Engine and Docker Compose are required to stop Pokosomo." >&2
  exit 1
fi
if ! docker compose down; then
  echo "Could not stop Pokosomo. Check the Docker message above and try again." >&2
  exit 1
fi

echo "Pokosomo Studio has stopped. Your projects and sign-ins are saved."
