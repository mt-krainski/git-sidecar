"""Entry point for python -m git_sidecar."""

import os

from git_sidecar.config import SidecarConfig
from git_sidecar.server import create_server


def main() -> None:
    """Start the git-sidecar MCP server."""
    # Files written into the bind-mounted projects directory must be
    # group-writable so the host's shared group can collaborate on them.
    os.umask(0o002)
    config = SidecarConfig.from_env()
    server = create_server(config)
    server.run(transport="sse")


if __name__ == "__main__":
    main()
