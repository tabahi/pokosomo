#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."
export PATH="$HOME/.local/bin:$PATH"

container_running=""
if command -v docker >/dev/null 2>&1 \
  && docker compose version >/dev/null 2>&1 \
  && docker info >/dev/null 2>&1; then
  if ! container_running="$(docker compose ps --status running --quiet studio)"; then
    echo "Could not check whether the Pokosomo container is running." >&2
    exit 1
  fi
fi

echo "Choose which account to connect:"
echo "  1. Claude"
echo "  2. OpenAI Codex"
echo "  3. Antigravity (Google)"
read -r -p "Enter 1, 2 or 3: " choice

case "$choice" in
  1)
    agent=(claude auth login)
    if [[ -n "$container_running" ]]; then
      agent=(docker compose exec studio "${agent[@]}")
    elif ! command -v claude >/dev/null 2>&1; then
      echo "Claude is not installed on this computer. Run ./linux/start.sh and choose a setup option first." >&2
      exit 1
    fi
    if ! "${agent[@]}"; then
      echo "Claude sign-in failed. Check the message above and try again." >&2
      exit 1
    fi
    ;;
  2)
    agent=(codex login)
    if [[ -n "$container_running" ]]; then
      agent=(docker compose exec studio "${agent[@]}")
    elif ! command -v codex >/dev/null 2>&1; then
      echo "Codex is not installed on this computer. Run ./linux/start.sh and choose a setup option first." >&2
      exit 1
    fi
    if ! "${agent[@]}"; then
      echo "Codex sign-in failed. Check the message above and try again." >&2
      exit 1
    fi
    ;;
  3)
    echo
    echo "Antigravity opens next. To sign in:"
    echo "  1. Choose \"Sign in\" and open the link it shows in your browser."
    echo "  2. Sign in with your Google account."
    echo "  3. Paste the code (or the full address of the page you land on) back here and press Enter."
    echo "  4. When it says you are signed in, type /exit and press Enter."
    echo
    # agy has no separate login command: the interactive session shows the sign-in on first run.
    agent=(agy)
    if [[ -n "$container_running" ]]; then
      agent=(docker compose exec studio "${agent[@]}")
    elif ! command -v agy >/dev/null 2>&1; then
      echo "Antigravity is not installed on this computer. Run ./linux/start.sh and choose a setup option first." >&2
      exit 1
    fi
    # Leaving agy with Ctrl+C returns an error code, so check for the saved sign-in instead.
    "${agent[@]}" || true
    if [[ -n "$container_running" ]]; then
      token_check=(docker compose exec -T studio sh -c 'test -s "$HOME/.gemini/antigravity-cli/antigravity-oauth-token"')
    else
      token_check=(test -s "$HOME/.gemini/antigravity-cli/antigravity-oauth-token")
    fi
    if ! "${token_check[@]}"; then
      echo "Antigravity is not signed in yet. Run ./linux/setup-agent.sh and choose 3 to try again." >&2
      exit 1
    fi
    ;;
  *)
    echo "Please enter 1, 2 or 3." >&2
    exit 1
    ;;
esac

echo "Sign-in complete. Choose this assistant in Studio Settings."
