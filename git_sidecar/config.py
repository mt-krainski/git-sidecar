"""Configuration for the git-sidecar MCP server."""

import os
from dataclasses import dataclass, field


def _parse_prefixes(value: str) -> list[str]:
    """Parse comma-separated branch prefixes, stripping whitespace."""
    return [p.strip() for p in value.split(",") if p.strip()]


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

    @classmethod
    def from_env(cls) -> "SidecarConfig":
        """Build configuration from environment variables."""
        projects_dir = os.environ.get("PROJECTS_DIR", "/projects")
        prefixes_raw = os.environ.get("ALLOWED_BRANCH_PREFIXES", "task/,dependabot/")
        token_filename = os.environ.get("SIDECAR_TOKEN_FILENAME", ".git-sidecar-token")
        host = os.environ.get("SIDECAR_HOST", "0.0.0.0")  # noqa: S104
        port = int(os.environ.get("SIDECAR_PORT", "8900"))

        return cls(
            projects_dir=projects_dir,
            allowed_branch_prefixes=_parse_prefixes(prefixes_raw),
            token_filename=token_filename,
            host=host,
            port=port,
        )
