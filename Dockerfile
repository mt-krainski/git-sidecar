FROM python:3.12-slim

# Install git and gh CLI
RUN apt-get update && \
    apt-get install -y --no-install-recommends git openssh-client curl && \
    curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
        -o /usr/share/keyrings/githubcli-archive-keyring.gpg && \
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
        > /etc/apt/sources.list.d/github-cli.list && \
    apt-get update && \
    apt-get install -y --no-install-recommends gh && \
    rm -rf /var/lib/apt/lists/*

# Install uv for fast dependency resolution
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Create non-root user
RUN groupadd --gid 1000 sidecar && \
    useradd --uid 1000 --gid sidecar --create-home sidecar && \
    mkdir -p /projects /home/sidecar/.ssh /home/sidecar/.config/gh && \
    chown -R sidecar:sidecar /projects /home/sidecar/.ssh /home/sidecar/.config/gh

WORKDIR /app

# Copy project files and install as root, then hand off ownership
COPY pyproject.toml uv.lock README.md ./
COPY git_sidecar/ ./git_sidecar/
RUN uv sync --frozen --no-dev && \
    chown -R sidecar:sidecar /app

# Default configuration
ENV PROJECTS_DIR=/projects
ENV SIDECAR_HOST=0.0.0.0
ENV SIDECAR_PORT=8900

EXPOSE 8900

USER sidecar

CMD ["uv", "run", "git-sidecar"]
