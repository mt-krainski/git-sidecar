FROM mcr.microsoft.com/devcontainers/python:3.12-bookworm

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    git \
    jq \
    && rm -rf /var/lib/apt/lists/*

# Python tooling
RUN pip install --no-cache-dir \
    ruff \
    mypy \
    pytest \
    pytest-cov \
    ipython \
    pre-commit \
    httpx \
    python-dotenv

# Set up non-root user (vscode is built into the base image)
USER vscode
WORKDIR /workspaces

RUN curl -LsSf https://astral.sh/uv/install.sh | sh
RUN curl -fsSL https://claude.ai/install.sh | bash -s 2.1.77

ENV PATH="/home/node/.local/bin:/home/node/.cargo/bin:${PATH}"