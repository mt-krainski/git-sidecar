# git-sidecar

> [!WARNING]
> **Work in progress — security is not guaranteed.** Effective isolation depends substantially on your individual host setup: Docker group membership, file ownership and umask, SSH key permissions, and which user accounts can `docker exec` into the running container all materially change what a compromised agent can reach. The design is meant to be hardenable (rootless Docker, dedicated unprivileged user, no Docker socket access for the agent), but that polish isn't here yet. For one example of how those pieces can fit together, see [the deployment runbook](docs/runbooks/shared-sidecar-isolated-agents.md). Don't point this at credentials you can't afford to lose.

A containerized MCP server that provides secure, credential-isolated Git and GitHub operations for AI agents running in sandboxed environments.

The sidecar holds SSH keys and GitHub credentials; the agent never sees them. Communication happens via MCP tools over SSE, with each operation scoped to a specific repository and authorized via a shared secret token file.

## Quick start

Build the image, aligning the in-container user with the host user/group that owns the projects directory. This makes files written by the sidecar land on the host with the expected ownership:

```bash
docker build \
  --build-arg UID=$(id -u <agent-user>) \
  --build-arg GID=$(getent group <shared-group> | cut -d: -f3) \
  -t git-sidecar .
```

Run, publishing the SSE endpoint to host loopback so a host-side MCP client can reach it. SSH keys and `gh` credentials live in named volumes so they survive container restarts and stay isolated from host user keys:

```bash
docker run -d \
  --name git-sidecar \
  --restart unless-stopped \
  -p 127.0.0.1:8900:8900 \
  -v /home/<agent-user>/Projects:/projects \
  -v ~/.gitconfig:/home/sidecar/.gitconfig:ro \
  -v sidecar-ssh:/home/sidecar/.ssh \
  -v gh-config:/home/sidecar/.config/gh \
  -e ALLOWED_BRANCH_PREFIXES=task/,dependabot/ \
  git-sidecar
```

The MCP client connects to `http://127.0.0.1:8900/sse`.

If the MCP client also runs in a container, replace `-p 127.0.0.1:8900:8900` with a shared bridge network (`docker network create git-sidecar-net` once, then `--network git-sidecar-net` on both containers).

To register the sidecar with Claude, run:

```bash
claude mcp add --transport sse git-sidecar http://127.0.0.1:8900/sse
```

### First-run setup

Authenticate `gh` once — choose SSH as the protocol and let it generate and upload a dedicated SSH key for you. The key lands in `~/.ssh/` and gh credentials in `~/.config/gh/`, both held by named volumes so they survive restarts:

```bash
docker exec -it git-sidecar gh auth login
```

GitHub host keys are pre-baked into `/etc/ssh/ssh_known_hosts` at image build, so `git fetch`/`push` won't prompt or fail on first use.

## Authentication

Each project that an agent should access needs a `.git-sidecar-token` file in its root directory. The agent must be able to read it — either generate the token as the agent user, or adjust file permissions afterwards so the agent has read access.

Generate with the included CLI tool:

```bash
uv tool install .
git-sidecar-token ~/Projects/my-repo
```

The agent provides this token with every tool call. The sidecar verifies it using timing-safe comparison before executing any operation.

## MCP tools

39 tools across four categories:

**Git read** (12): `git_status`, `git_diff`, `git_log`, `git_show`, `git_branch`, `git_rev_parse`, `git_ls_files`, `git_stash_list`, `git_remote`, `git_blame`, `git_tag`, `git_config_get`

**Git write** (11): `git_add`, `git_rm`, `git_commit`, `git_restore`, `git_stash`, `git_fetch`, `git_pull`, `git_merge`, `git_worktree`, `git_checkout`, `git_push`

**Git LFS** (6): `git_lfs_track`, `git_lfs_untrack`, `git_lfs_ls_files`, `git_lfs_status`, `git_lfs_fetch`, `git_lfs_pull`

**GitHub** (10): `gh_pr_create`, `gh_pr_edit`, `gh_pr_view`, `gh_pr_list`, `gh_pr_fetch`, `gh_pr_reply`, `gh_pr_checks`, `gh_pr_close`, `gh_run_view`, `gh_run_list`

### Diffs written to a file

`git_diff` takes an optional `output` path and writes the diff body there instead of returning it. Git writes the bytes, so nothing re-types them and a review-sized diff never enters the calling agent's context. The result carries the path written and a `--stat` summary of the same selection — a convenience overview from a second git call, not a check on the file.

`output` is relative to `<repo>/.git-sidecar/` and confined to it: `..`, absolute paths, and symlinks leading out are rejected, so no tracked file can be overwritten. The write does not lean on that check alone — it opens every component with `O_NOFOLLOW` relative to the open directory, so a component swapped afterwards cannot redirect it, and refuses a target that is not a plain unaliased file. The directory is created on first use with a `.gitignore` of `*` — it ignores everything it holds, itself included, so git stays quiet about it and no repository needs an ignore entry of its own.

### Git LFS

The image bundles `git-lfs` with its smudge/clean filters registered system-wide, so checkouts and pulls in LFS repositories resolve pointer files automatically. `git_push` uploads LFS objects for the current branch before pushing refs — this works even in repositories that lack the repo-local LFS pre-push hook (e.g. cloned before LFS was installed), and refs are never pushed if the object upload fails. LFS transfers get a 10-minute timeout instead of the 60-second default.

## Configuration

All configuration is via environment variables:

| Variable                  | Default              | Description                                            |
| ------------------------- | -------------------- | ------------------------------------------------------ |
| `PROJECTS_DIR`            | `/projects`          | Mount point for project directories                    |
| `SIDECAR_HOST`            | `0.0.0.0`            | Server bind address                                    |
| `SIDECAR_PORT`            | `8900`               | Server port                                            |
| `ALLOWED_BRANCH_PREFIXES` | `task/,dependabot/`  | Comma-separated branch prefixes agents can create/push |
| `SIDECAR_TOKEN_FILENAME`  | `.git-sidecar-token` | Name of the per-project token file                     |

## Volume mounts

| Mount                                      | Purpose                                                         |
| ------------------------------------------ | --------------------------------------------------------------- |
| `~/Projects:/projects`                     | Project directories the agent can access                        |
| `~/.gitconfig:/home/sidecar/.gitconfig:ro` | Git user config (name, email, SSH command) — read from host     |
| `sidecar-ssh:/home/sidecar/.ssh`           | Dedicated SSH key + known_hosts, generated and held by sidecar  |
| `gh-config:/home/sidecar/.config/gh`       | Persistent GitHub CLI credentials                               |

Adjust the projects directory to match your setup.

## Security model

- Agent runs in an untrusted container without any credentials
- All Git/GitHub operations are proxied through the sidecar
- No `shell=True` anywhere — all subprocess calls use argument lists
- Protected branches (main/master) cannot be pushed to
- Force-push flags are rejected
- Path traversal is blocked at multiple layers
- Branch names must match configured prefixes

## Deployment models

The quick start above is the simplest setup: one sidecar on one user's Docker daemon, serving one agent. It is not the only way to run git-sidecar — how much isolation you get depends on how you deploy it.

For one example of a hardened multi-agent setup — one shared sidecar on the administrator's rootful Docker daemon, serving several mutually-isolated agent users that each get a private home, their own rootless Docker daemon, and group-scoped file access — see [the deployment runbook](docs/runbooks/shared-sidecar-isolated-agents.md). Treat runbooks as worked examples, not prescriptions or guarantees.

## Development

```bash
./scripts/configure.sh  # install dependencies and pre-commit hooks
uv run pytest            # run tests
uv run ruff check .      # lint
```
