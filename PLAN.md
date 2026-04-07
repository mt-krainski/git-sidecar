# Git Sidecar MCP Server — Development Plan

## Overview

A containerized MCP server (Python, HTTP/SSE) that acts as a security isolation layer between an AI agent running in a dev container and Git/GitHub operations running on the host. The sidecar holds SSH keys and GitHub credentials; the agent never sees them. The agent communicates via MCP tools, each scoped to a specific repository and authorized via a shared secret file on disk.

## Architecture

```
┌─────────────────────┐       MCP over HTTP/SSE        ┌─────────────────────┐
│   Dev Container     │  ─────────────────────────►     │  Git Sidecar        │
│   (AI Agent)        │   "commit these files"          │  Container          │
│                     │   "push to branch X"            │                     │
│   NO SSH keys       │                                 │   ~/.ssh mounted    │
│   NO gh auth        │                                 │   ~/projects mounted│
└─────────────────────┘                                 └─────────────────────┘
          │                                                       │
          └───────── same Docker network (sidecar-net) ───────────┘
```

## Authorization Model

Each project directory contains a secret file (default: `.git-sidecar-token`). On every MCP call, the agent passes:
- `repo` — path relative to the mounted projects directory
- `token` — contents of the secret file it read from its own mount

The sidecar reads the actual file from disk and compares values. Match = authorized. This proves the agent has legitimate access to that working directory.

## Configuration (Environment Variables)

| Variable | Default | Description |
|---|---|---|
| `PROJECTS_DIR` | `/projects` | Mount point for project directories |
| `ALLOWED_BRANCH_PREFIXES` | `task/,dependabot/` | Comma-separated prefixes allowed for push/checkout |
| `SIDECAR_TOKEN_FILENAME` | `.git-sidecar-token` | Name of the per-project secret file |
| `SIDECAR_HOST` | `0.0.0.0` | Bind address |
| `SIDECAR_PORT` | `8900` | Bind port |

## MCP Tool Inventory

### Git — Read-Only

| Tool | Wraps | Notes |
|---|---|---|
| `git_status` | `git status` | |
| `git_diff` | `git diff` | Args: staged, files, ref |
| `git_log` | `git log` | Args: count, format, ref |
| `git_show` | `git show <ref>` | |
| `git_branch` | `git branch` | List branches |
| `git_rev_parse` | `git rev-parse` | Resolve refs |
| `git_ls_files` | `git ls-files` | |
| `git_stash_list` | `git stash list/show` | |
| `git_remote` | `git remote -v / get-url / show` | |
| `git_blame` | `git blame <file>` | |
| `git_tag` | `git tag -l` / `git show <tag>` | Read-only |
| `git_config_get` | `git config --get <key>` | Read-only |

### Git — Write (Safe)

| Tool | Wraps | Notes |
|---|---|---|
| `git_add` | `git add <files>` | |
| `git_rm` | `git rm <files>` | |
| `git_commit` | `git commit -m <msg>` | Validates author from git config |
| `git_restore` | `git restore <files>` | |
| `git_stash` | `git stash push/pop/apply/drop` | |
| `git_fetch` | `git fetch` | |
| `git_pull` | `git pull` | |
| `git_merge` | `git merge <branch>` | |
| `git_worktree` | `git worktree list/remove` | No add (too complex) |

### Git — Write (Restricted)

| Tool | Wraps | Restrictions |
|---|---|---|
| `git_checkout` | `git checkout` | Only allowed branch prefixes, main, master |
| `git_push` | `git push -u origin <branch>` | Only allowed prefixes, no --force, no main/master |

### GitHub — Pull Requests

| Tool | Wraps | Notes |
|---|---|---|
| `gh_pr_create` | `gh pr create` | Args: base, title, body |
| `gh_pr_view` | `gh pr view` | By number or branch |
| `gh_pr_list` | `gh pr list` | Optional head filter |
| `gh_pr_fetch` | `gh api` (3 endpoints) | Returns inline comments, reviews, conversation |
| `gh_pr_reply` | `gh api` | Top-level or inline thread reply |
| `gh_pr_checks` | `gh pr checks` | Includes failed run logs |
| `gh_pr_close` | `gh pr close` | Optional comment, delete-branch |

### GitHub — Workflow Runs

| Tool | Wraps | Notes |
|---|---|---|
| `gh_run_view` | `gh run view` | Optional --log-failed |
| `gh_run_list` | `gh run list` | |

## Project Structure

```
git-sidecar/
├── inspiration/                # existing, unchanged
├── git_sidecar/
│   ├── __init__.py
│   ├── server.py               # FastMCP server setup, SSE transport
│   ├── auth.py                 # token verification logic
│   ├── config.py               # env var config (dataclass)
│   ├── executor.py             # safe subprocess runner (no shell=True)
│   ├── tools/
│   │   ├── __init__.py         # tool registration
│   │   ├── git_read.py         # read-only git tools
│   │   ├── git_write.py        # safe + restricted write tools
│   │   └── github.py           # gh CLI wrapper tools
│   └── validation.py           # branch name validation, input sanitization
├── tests/
│   ├── test_auth.py
│   ├── test_config.py
│   ├── test_executor.py
│   ├── test_validation.py
│   ├── test_git_read.py
│   ├── test_git_write.py
│   └── test_github.py
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml
├── PLAN.md
└── README.md
```

## Development Phases

### Phase 1: Foundation ✅

- [x] Set up `config.py` — dataclass reading env vars with defaults
- [x] Set up `auth.py` — token file verification logic
- [x] Set up `executor.py` — safe subprocess wrapper (argument lists, cwd, timeout, structured output)
- [x] Set up `validation.py` — branch name prefix checks, path sanitization (no `..` escapes)
- [x] Tests for all of the above

### Phase 2: Git Read-Only Tools ✅

- [x] Implement all read-only git tools in `git_read.py` (12 tools)
- [x] Register them with the MCP server in `server.py` (basic FastMCP setup)
- [x] Each tool: auth check → validate input → execute → return structured result
- [x] Tests for each tool (27 tests, mock subprocess)

### Phase 3: Git Write Tools ✅

- [x] Implement safe write tools in `git_write.py` (add, rm, commit, restore, stash, fetch, pull, merge, worktree)
- [x] Implement restricted write tools (checkout, push) with branch validation
- [x] `git_commit` — author/committer from git config (ported logic from agent-utils)
- [x] `git_push` — enforce prefix rules, block force push, block main/master
- [x] Tests for each tool, especially restriction enforcement (40 tests)

### Phase 4: GitHub Tools ✅

- [x] Implement PR tools in `github.py` (create, view, list, fetch, reply, checks, close)
- [x] Implement run tools (view, list)
- [x] GitHub owner/repo derived from `git remote` in the target repo (not env vars — multi-project)
- [x] Tests for each tool (37 tests)

### Phase 5: Server & Transport ✅

- [x] Wire up FastMCP with SSE/HTTP transport
- [x] Add `__main__.py` entry point for `python -m git_sidecar`
- [x] Add script entry point in `pyproject.toml`
- [ ] End-to-end smoke test (start server, call a tool, verify response)

### Phase 6: Containerization ✅

- [x] Write `Dockerfile` (Python base, install gh CLI, install package)
- [x] Write `docker-compose.yml` (sidecar + shared network, volume mounts)
- [ ] Document the `gh auth login` flow (user execs into container)
- [ ] Test container build and basic operation

### Not In Scope (Future)

- Per-project branch prefix configuration
- Rate limiting / audit logging
- Multiple auth schemes
- Web UI / dashboard
- npm/npx command proxying (could be added as separate tools later)
