"""Entry point for python -m git_sidecar."""

from git_sidecar.config import SidecarConfig
from git_sidecar.server import create_server


def main() -> None:
    """Start the git-sidecar MCP server."""
    config = SidecarConfig.from_env()
    server = create_server(config)
    server.run(transport="sse")


if __name__ == "__main__":
    main()
