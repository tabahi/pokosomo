# Pokosomo Studio

A private research workspace in the browser, built for a non-programmers and non-technical researchers, to let the AI agents do the grind work.
User organises work into **projects**, reads and edits documents, and asks an **AI assistant**
(Claude Code, OpenAI Codex, or Antigravity, running headlessly) to do the grind work: summarise papers, run
statistics, make figures, draft, analyze data, and proofread text. 

It is designed to use Claude Code, Antigravity, or Codex with an account subscription, instead of a token-based API, although API accounts can also be used. Sign in once using `claude auth login`, `codex login`, or `agy`.

## What the user sees

| Area | What it does |
|---|---|
| **Projects** home | One card per folder in `workspace/`. Create, rename, delete (deletes go to `workspace/.trash/`). |
| **Files** (left) | Project files. Upload by button or drag-and-drop, new notes/folders, rename, move (drag onto a folder), download. |
| **Document** (middle) | Opens whatever is selected: **notes** (Markdown) in a writing editor with toolbar, Title/Author/Date fields and **Make PDF** (pandoc + XeLaTeX) or Word export; PDFs; Word/PowerPoint previews (LibreOffice) with “Edit as note”; CSV/Excel tables; images; plain text/code. Autosaves. |
| **Assistant** (right) | Chat with the agent. Shows its steps in plain language (“Read data.csv”, “Edited notes.md”) with links to open the files it touched. Chats are saved per project. Stop button, attachments, “Try again”. |

On phones the three areas become bottom tabs. A terminal (xterm.js) is available behind
**Settings → Advanced** for technical users.

## Setup (Windows recommended)

Pokosomo runs in a Linux container so you don't have to install Python, Node, LaTeX, R, or
document tools yourself. You do not need to use PowerShell or type commands for the normal setup.

**Research data and privacy:** Pokosomo stores projects on your laptop. When an AI assistant works
on a project, your prompts and relevant project content it reads may be sent to that provider (for
example, Anthropic or OpenAI). Do not use identifiable participant data or other restricted
information unless your institution has approved that provider and use.

### Windows with Docker Desktop (easiest on windows)

1. Install and open [Docker Desktop](https://www.docker.com/products/docker-desktop/). Wait for it
   to show that its engine is running.
2. Download and extract the Pokosomo folder, then double-click [`start.bat`](start.bat). The first
   run downloads the ready-made image, asks you to create a password and connect an authenticator
   app, then opens the studio in your browser. If the image cannot be downloaded, it tries to build
   it locally instead.
3. To connect an AI assistant, double-click [`setup-agent.bat`](setup-agent.bat), choose Claude or
   Codex, and follow the sign-in instructions. Then select it in **Settings → Assistant**. Both
   assistants are included; you do not need to install them on Windows.

The studio runs in the background, so you can close the start window. Double-click [`stop.bat`](stop.bat)
to stop it; double-click `start.bat` again to resume. Projects and sign-ins are saved across stops.
If Docker Desktop is not running, open it and wait for the engine to start before trying again.

### Windows with WSL containers (optional, light on windows)

To run without Docker Desktop, install WSL and update it in PowerShell with `wsl --update`.
[`wslc`](https://learn.microsoft.com/en-us/windows/wsl/wsl-container) requires WSL 2.9.3 or newer;
check with `wsl --version` and `wslc version`. Then double-click [`start-wslc.bat`](start-wslc.bat)
and open **http://localhost:8001**. The first run downloads the ready-made image and asks you to set
a password and connect an authenticator app. Use [`setup-agent-wslc.bat`](setup-agent-wslc.bat) to
sign in, and [`stop-wslc.bat`](stop-wslc.bat) to stop it.

## Setup (Linux)

```bash
./scripts/install_deps.sh   # installs system and Python tools, plus Claude Code and Codex (needs sudo)
./setup_auth.sh             # choose a password and scan the QR code with an authenticator app
./run.sh                    # http://localhost:8001   (PORT=8080 ./run.sh to change)
```

`run.sh` runs `setup_auth.sh` automatically the first time if it's started from a terminal.
If an earlier Pokosomo run is still using the chosen port, `run.sh` safely stops that same app
instance and reuses the port. It will not stop an unrelated program.

Sign in to Claude or Codex once with `claude auth login` or `codex login`. Antigravity remains
available when installed separately (`agy`). Settings in the UI choose the assistant and model for
new chats.

## Security

- **Password + TOTP 2FA.** `secrets.json` holds an scrypt hash of the password and the TOTP secret
  (`{"login": {...}}`; other top-level keys are preserved). Codes can't be reused; 5 failed attempts per
  IP lock sign-in for 15 minutes.
- **Sessions** are server-side (`data/sessions.json`, only token hashes stored), cookie is `HttpOnly`,
  `SameSite=Lax`, and `Secure` when served over HTTPS.
  “Remember me” → 30-day cookie. Unticked → browser-session cookie, plus a 12-hour idle limit on the server.
- Every HTTP route, static file and WebSocket requires a session (except the login page). Cross-site
  POSTs and WebSocket handshakes are rejected by Origin check.
- Files are served with `nosniff`; HTML and other active content is download-only, SVGs are sandboxed.
- `./setup_auth.sh logout-all` (or Settings → “Sign out on all devices”) revokes every session.
  Re-running `./setup_auth.sh` changes the password and also signs everyone out.

**Use HTTPS when it's reachable beyond localhost** (e.g. Caddy, Tailscale, or a Cloudflare tunnel in
front). Over plain HTTP the password and session cookie can be read by anyone on the network path.
Behind a proxy on another host, set `FORWARDED_ALLOW_IPS` so the HTTPS flag is trusted.

## How the agents are confined

Claude and Antigravity run with full permissions (`--dangerously-skip-permissions`). Codex uses its
`workspace-write` sandbox, limited to the open project. The assistants are **instructed** to stay in
the project: each starts in the project folder, `TMPDIR` points at `tmp/<project>/`, and
[`server/agent_instructions.md`](server/agent_instructions.md) is appended to its system prompt
(stay inside the project, use `$TMPDIR` for scratch, never delete her files, plain-language replies,
save analyses as re-runnable scripts, never invent data or references…). Edit that file to change
how the assistant behaves. For Windows Docker users, the container is the isolation boundary.

## Layout

```
run.sh, setup_auth.sh          start the server / configure login
Dockerfile, compose.yaml       container build recipe and prebuilt image configuration
start*.bat, stop*.bat           Windows start / stop shortcuts (Docker Desktop or WSL containers)
setup-agent*.bat                Windows Claude / Codex sign-in shortcuts
scripts/install_deps.sh        system + Python dependencies (reproducible container setup)
server/
  app.py                       FastAPI routes + WebSockets
  auth.py                      password/TOTP, sessions, auth middleware, setup CLI
  chat_manager.py              runs Claude Code / Codex / agy, converts their event streams, chat history
  agent_instructions.md        system-prompt addendum for the assistant
  documents.py                 Markdown→PDF/Word, LaTeX→PDF, Word→Markdown, Office previews, table previews
  templates/pdf-header.tex     LaTeX packages for every note PDF (siunitx, mhchem, float, …)
  workspace_manager.py         projects and safe file operations (path-confined, trash instead of delete)
  terminal_manager.py          PTY terminals for the advanced view
static/
  index.html, login.html       app shell and sign-in page
  js/                          main (routing, home, settings), files, viewer, chat, terminal, util
  css/app.css                  light/dark theme, responsive layout
workspace/<project>/           her projects; chat history in <project>/.studio/chats/
tmp/                           scratch for agents and document builds
data/                          sessions and settings (git-ignored)
```

## Useful environment variables

| Variable | Default | Purpose |
|---|---|---|
| `PORT`, `HOST` | `8001`, `0.0.0.0` | where `run.sh` listens; Docker publishes to `localhost` only |
| `FORWARDED_ALLOW_IPS` | `127.0.0.1` | proxies trusted for `X-Forwarded-*` |
| `POKOSOMO_VENV` | `.venv` | Python environment (`/opt/venv` in Docker) |
| `POKOSOMO_SECRETS`, `POKOSOMO_DATA` | `secrets.json`, `data/` | alternative locations (handy for testing) |
| `POKOSOMO_CLAUDE_BIN`, `POKOSOMO_AGY_BIN` | `claude`, `agy` | agent executables |
| `POKOSOMO_CODEX_BIN` | `codex` | Codex CLI executable |

