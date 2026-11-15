#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

# One-time user agreement. The answer is remembered in data/ so it is only asked once.
accept_terms() {
  local marker="data/.terms-accepted"
  [[ -f "$marker" ]] && return 0
  echo "=========================================================="
  echo "  Pokosomo Studio - user agreement"
  echo "=========================================================="
  echo "Pokosomo Studio is free software under the MIT License (see the LICENSE file)."
  echo
  echo "It is provided \"AS IS\", WITHOUT WARRANTY OF ANY KIND. The authors give no guarantees"
  echo "and accept no responsibility or liability for any damage, data loss, costs or other"
  echo "consequences of using it, including anything the AI assistants do on your computer,"
  echo "with your files or with your accounts."
  echo
  echo "You are responsible for your data, for your AI provider accounts and their terms of use,"
  echo "and for keeping the studio secure (for example, turning on two-factor sign-in on a public server)."
  echo
  if [[ ! -t 0 ]]; then
    echo "Run ./linux/start.sh in a terminal to read and accept the agreement first." >&2
    exit 1
  fi
  read -r -p "Do you accept these terms? [y/N]: " agree
  case "$agree" in
    y|Y|yes|YES|Yes) ;;
    *) echo "You did not accept the terms, so nothing was installed."; exit 1 ;;
  esac
  mkdir -p data
  date -u +"%Y-%m-%dT%H:%M:%SZ accepted" > "$marker"
  echo
}
accept_terms

start_container() {
  if ! command -v docker >/dev/null 2>&1; then
    echo "Docker Engine and Docker Compose are required. Install Docker for your Linux distribution, then try again." >&2
    return 1
  fi
  if ! docker compose version >/dev/null 2>&1; then
    echo "Docker Compose is missing. Install the Docker Compose plugin, then try again." >&2
    return 1
  fi
  if ! docker info >/dev/null 2>&1; then
    echo "Docker is not running or this account cannot access it. Start Docker and try again." >&2
    return 1
  fi

  mkdir -p data workspace tmp

  echo "Preparing Pokosomo Studio. The first download may take a while."
  if ! docker compose pull; then
    echo "The prebuilt image could not be pulled. Trying a local build instead."
    if ! docker compose build; then
      echo "Setup did not finish. Check the message above, then run ./linux/start.sh to try again." >&2
      return 1
    fi
  fi

  if ! status_output="$(docker compose run --rm -T studio python -m server.auth status)"; then
    echo "Could not check the studio login setup. Check the Docker message above and try again." >&2
    return 1
  fi
  if ! grep -qF "Login configured." <<<"$status_output"; then
    echo
    echo "First, create your studio password. You will be asked whether to turn on two-factor sign-in."
    if ! docker compose run --rm studio python -m server.auth setup; then
      echo "Login setup did not finish. Run ./linux/start.sh to try again." >&2
      return 1
    fi
  fi

  echo
  echo "Starting Pokosomo Studio in the background."
  if ! docker compose up -d; then
    echo "Pokosomo could not start. Check the Docker message above and try again." >&2
    return 1
  fi

  port_mapping="$(docker compose port studio 8001)"
  studio_port="${port_mapping##*:}"
  studio_url="http://localhost:${studio_port}"
  echo
  echo "Pokosomo Studio: ${studio_url}"
  echo "You can close this terminal. To stop the studio, run ./linux/stop.sh."
  if [[ -t 0 ]]; then
    echo
    read -r -p "Connect your Claude, Codex or Antigravity account now? [Y/n]: " connect
    case "${connect:-y}" in
      n|N|no|NO|No) echo "You can do this later with ./linux/setup-agent.sh." ;;
      *) "$(dirname "${BASH_SOURCE[0]}")/setup-agent.sh" || true ;;
    esac
  fi
  if command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$studio_url" >/dev/null 2>&1 || echo "Open ${studio_url} in your browser."
  else
    echo "Open ${studio_url} in your browser."
  fi
}

start_on_host() {
  echo "This installs Pokosomo's research and document tools on this computer."
  echo "The host installation currently supports Debian and Ubuntu."
  echo "It requires sudo and several gigabytes of disk space."
  read -r -p "Continue with the host installation? [y/N]: " confirm
  case "$confirm" in
    y|Y|yes|YES|Yes) ;;
    *)
      echo "Host installation cancelled."
      return 0
      ;;
  esac

  local venv="${POKOSOMO_VENV:-$PWD/.venv}"
  if [[ ! -f "$venv/.pokosomo-install-complete" ]]; then
    if ! ./scripts/install_deps.sh; then
      echo "Host installation did not finish. Check the message above and try again." >&2
      exit 1
    fi
    mkdir -p "$venv"
    touch "$venv/.pokosomo-install-complete"
  else
    echo "Host tools are already installed; skipping installation."
  fi
  exec ./run.sh
}

docker_ready() {
  command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1
}

# ./linux/start.sh --host  installs and runs the tools directly on this computer instead.
if [[ "${1:-}" == "--host" ]]; then
  start_on_host
elif docker_ready; then
  start_container
else
  echo "Docker is not installed, and it is the easiest way to run Pokosomo:"
  echo "  https://docs.docker.com/engine/install/  (install Docker Engine + the Compose plugin, then run this again)"
  echo
  echo "Or install the tools directly on this computer (Debian/Ubuntu only, needs sudo)."
  start_on_host
fi
