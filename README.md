# git-sidecar

A containerized MCP server that provides secure, credential-isolated Git and GitHub operations for AI agents running in sandboxed environments.

The sidecar holds SSH keys and GitHub credentials; the agent never sees them. Communication happens via MCP tools over SSE, with each operation scoped to a specific repository and authorized via a shared secret token file.

## Quick start

Create the shared Docker network (once):

```bash
docker network create git-sidecar-net
```

Build and run:

```bash
docker build -t git-sidecar .

docker run -d \
  --name git-sidecar \
  --restart unless-stopped \
  --network git-sidecar-net \
  -v ~/Projects:/projects \
  -v ~/.gitconfig:/home/sidecar/.gitconfig:ro \
  -v ~/.ssh/id_ed25519:/home/sidecar/.ssh/id_ed25519:ro \
  -v ~/.ssh/known_hosts:/home/sidecar/.ssh/known_hosts:ro \
  -v gh-config:/home/sidecar/.config/gh \
  -e ALLOWED_BRANCH_PREFIXES=task/,dependabot/ \
  git-sidecar
```

## Authentication

Each project that an agent should access needs a `.git-sidecar-token` file in its root directory. Generate one with the included CLI tool:

```bash
uv tool install .
git-sidecar-token ~/Projects/my-repo
```

The agent provides this token with every tool call. The sidecar verifies it using timing-safe comparison before executing any operation.

## MCP tools

32 tools across three categories:

**Git read** (12): `git_status`, `git_diff`, `git_log`, `git_show`, `git_branch`, `git_rev_parse`, `git_ls_files`, `git_stash_list`, `git_remote`, `git_blame`, `git_tag`, `git_config_get`

**Git write** (11): `git_add`, `git_rm`, `git_commit`, `git_restore`, `git_stash`, `git_fetch`, `git_pull`, `git_merge`, `git_worktree`, `git_checkout`, `git_push`

**GitHub** (9): `gh_pr_create`, `gh_pr_view`, `gh_pr_list`, `gh_pr_fetch`, `gh_pr_reply`, `gh_pr_checks`, `gh_pr_close`, `gh_run_view`, `gh_run_list`

## Configuration

All configuration is via environment variables:

| Variable | Default | Description |
|---|---|---|
| `PROJECTS_DIR` | `/projects` | Mount point for project directories |
| `SIDECAR_HOST` | `0.0.0.0` | Server bind address |
| `SIDECAR_PORT` | `8900` | Server port |
| `ALLOWED_BRANCH_PREFIXES` | `task/,dependabot/` | Comma-separated branch prefixes agents can create/push |
| `SIDECAR_TOKEN_FILENAME` | `.git-sidecar-token` | Name of the per-project token file |

## Volume mounts

| Mount | Purpose |
|---|---|
| `~/Projects:/projects` | Project directories the agent can access |
| `~/.gitconfig:/home/sidecar/.gitconfig:ro` | Git user config (name, email, SSH command) |
| `~/.ssh/id_ed25519:/home/sidecar/.ssh/id_ed25519:ro` | SSH private key for git operations |
| `~/.ssh/known_hosts:/home/sidecar/.ssh/known_hosts:ro` | SSH known hosts |
| `gh-config:/home/sidecar/.config/gh` | Persistent GitHub CLI credentials |

Adjust SSH key paths and project directories to match your setup.

## Security model

- Agent runs in an untrusted container without any credentials
- All Git/GitHub operations are proxied through the sidecar
- No `shell=True` anywhere — all subprocess calls use argument lists
- Protected branches (main/master) cannot be pushed to
- Force-push flags are rejected
- Path traversal is blocked at multiple layers
- Branch names must match configured prefixes

## GitHub CLI setup

After first launch, authenticate the GitHub CLI inside the sidecar:

```bash
docker exec -it git-sidecar gh auth login
```

Credentials persist in the `gh-config` volume across container rebuilds.

## Development

```bash
./scripts/configure.sh  # install dependencies and pre-commit hooks
uv run pytest            # run tests
uv run ruff check .      # lint
```
