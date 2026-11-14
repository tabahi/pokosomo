FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive \
    POKOSOMO_VENV=/opt/venv \
    POKOSOMO_SECRETS=/app/data/secrets.json \
    CODEX_HOME=/root/.codex \
    CLAUDE_CONFIG_DIR=/root/.claude \
    HOST=0.0.0.0 \
    PORT=8001 \
    PATH=/root/.local/bin:/opt/venv/bin:${PATH}

WORKDIR /app
COPY . /app

RUN chmod +x ./run.sh ./setup_auth.sh ./scripts/install_deps.sh \
    && ./scripts/install_deps.sh \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

EXPOSE 8001
CMD ["./run.sh"]
