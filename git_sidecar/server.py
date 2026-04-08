"""MCP server wiring for git-sidecar."""

from mcp.server.fastmcp import FastMCP

from git_sidecar.config import SidecarConfig
from git_sidecar.tools import git_read, git_write, github

mcp: FastMCP | None = None

_READ_TOOLS = [
    "git_status",
    "git_diff",
    "git_log",
    "git_show",
    "git_branch",
    "git_rev_parse",
    "git_ls_files",
    "git_stash_list",
    "git_remote",
    "git_blame",
    "git_tag",
    "git_config_get",
]

_WRITE_TOOLS = [
    "git_add",
    "git_rm",
    "git_commit",
    "git_restore",
    "git_stash",
    "git_fetch",
    "git_pull",
    "git_merge",
    "git_worktree",
    "git_checkout",
    "git_push",
]

_GITHUB_TOOLS = [
    "gh_pr_create",
    "gh_pr_view",
    "gh_pr_list",
    "gh_pr_fetch",
    "gh_pr_reply",
    "gh_pr_checks",
    "gh_pr_close",
    "gh_run_view",
    "gh_run_list",
]


def _register_tools(module, names: list[str]) -> None:
    """Register tool functions from a module with the MCP server."""
    for name in names:
        fn = getattr(module, name)
        mcp.tool()(fn)


def create_server(config: SidecarConfig | None = None) -> FastMCP:
    """Initialize tools and return the configured MCP server.

    Args:
        config: Server configuration. If None, loads from environment.

    Returns:
        Configured FastMCP instance with all tools registered.
    """
    global mcp  # noqa: PLW0603

    if config is None:
        config = SidecarConfig.from_env()

    mcp = FastMCP("git-sidecar", host=config.host, port=config.port)

    git_read.init(config)
    git_write.init(config)
    github.init(config)

    _register_tools(git_read, _READ_TOOLS)
    _register_tools(git_write, _WRITE_TOOLS)
    _register_tools(github, _GITHUB_TOOLS)

    return mcp
