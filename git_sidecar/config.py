"""Configuration for the git-sidecar MCP server."""

import os
from dataclasses import dataclass, field

# The transports the sidecar serves. The SDK also offers "stdio", which this
# server does not accept: host and port mean nothing to it, and a sidecar
# reached over stdio cannot serve more than the one process that spawned it.
SUPPORTED_TRANSPORTS = ("sse", "streamable-http")


class ConfigError(Exception):
    """Raised when the environment holds a value the server cannot use."""


def _parse_prefixes(value: str) -> list[str]:
    """Parse comma-separated branch prefixes, stripping whitespace."""
    return [p.strip() for p in value.split(",") if p.strip()]


def _parse_transport(value: str) -> str:
    """Validate a transport name against the ones the sidecar serves.

    Args:
        value: Raw transport name from the environment.

    Returns:
        The transport name, stripped of surrounding whitespace.

    Raises:
        ConfigError: If the name is not one the sidecar serves.
    """
    transport = value.strip()

    if transport not in SUPPORTED_TRANSPORTS:
        supported = ", ".join(SUPPORTED_TRANSPORTS)
        raise ConfigError(f"Unsupported transport '{value}'. Supported: {supported}")

    return transport


@dataclass(frozen=True)
class SidecarConfig:
    """Immutable configuration loaded from environment variables."""

    projects_dir: str = "/projects"
    allowed_branch_prefixes: list[str] = field(
        default_factory=lambda: ["task/", "dependabot/"]
    )
    token_filename: str = ".git-sidecar-token"  # noqa: S105
    host: str = "0.0.0.0"  # noqa: S104
    port: int = 8900
    transport: str = "sse"

    @classmethod
    def from_env(cls) -> "SidecarConfig":
        """Build configuration from environment variables.

        Returns:
            Configuration built from the environment.

        Raises:
            ConfigError: If SIDECAR_TRANSPORT names a transport the sidecar
                does not serve.
        """
        projects_dir = os.environ.get("PROJECTS_DIR", "/projects")
        prefixes_raw = os.environ.get("ALLOWED_BRANCH_PREFIXES", "task/,dependabot/")
        token_filename = os.environ.get("SIDECAR_TOKEN_FILENAME", ".git-sidecar-token")
        host = os.environ.get("SIDECAR_HOST", "0.0.0.0")  # noqa: S104
        port = int(os.environ.get("SIDECAR_PORT", "8900"))
        transport = _parse_transport(os.environ.get("SIDECAR_TRANSPORT", "sse"))

        return cls(
            projects_dir=projects_dir,
            allowed_branch_prefixes=_parse_prefixes(prefixes_raw),
            token_filename=token_filename,
            host=host,
            port=port,
            transport=transport,
        )
