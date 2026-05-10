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

# Pre-trust github.com host keys so ssh doesn't prompt or fail on first use.
RUN ssh-keyscan -t rsa,ecdsa,ed25519 github.com > /etc/ssh/ssh_known_hosts

# Install uv for fast dependency resolution
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Create non-root user. UID/GID are build args so the in-container user
# can be aligned with the host user/group that owns the bind-mounted
# projects directory — files written by the container then land on the
# host with the expected ownership instead of orphan numeric IDs.
ARG UID=1000
ARG GID=1000
RUN groupadd --gid ${GID} sidecar && \
    useradd --uid ${UID} --gid sidecar --create-home sidecar && \
    mkdir -p /projects /home/sidecar/.ssh /home/sidecar/.config/gh && \
    chown -R sidecar:sidecar /projects /home/sidecar/.ssh /home/sidecar/.config/gh && \
    git config --system safe.directory '/projects/*'

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

CMD ["uv", "run", "python", "-m", "git_sidecar"]
