FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive \
    POKOSOMO_VENV=/opt/venv \
    POKOSOMO_SECRETS=/app/data/secrets.json \
    HOST=0.0.0.0 \
    PORT=8001 \
    PATH=/root/.local/bin:/opt/venv/bin:${PATH}

WORKDIR /app

# Heavy dependencies first, in their own layer: code changes below don't trigger a reinstall.
COPY requirements.txt /app/requirements.txt
COPY scripts/install_deps.sh /app/scripts/install_deps.sh
RUN chmod +x ./scripts/install_deps.sh \
    && ./scripts/install_deps.sh \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* /root/.cache /root/.npm

COPY . /app
RUN chmod +x ./run.sh ./setup_auth.sh ./scripts/install_deps.sh \
    && mkdir -p /root/.codex-auth /root/.claude-auth /root/.gemini

# Sign-in state lives in separate folders that compose mounts as volumes. They must not overlap the
# tool install locations (/root/.codex holds the Codex program itself), or the volume hides the tools.
ENV CODEX_HOME=/root/.codex-auth \
    CLAUDE_CONFIG_DIR=/root/.claude-auth

# The studio runs as root inside the container, which is the isolation boundary. Claude Code refuses
# --dangerously-skip-permissions as root unless it is told it is in a sandbox.
ENV IS_SANDBOX=1

EXPOSE 8001
CMD ["./run.sh"]
