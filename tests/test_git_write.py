"""Tests for git_sidecar.tools.git_write."""

import pathlib
import shutil
import stat
from unittest.mock import patch

import pytest

from git_sidecar import auth, executor
from git_sidecar.config import SidecarConfig
from git_sidecar.executor import ExecResult
from git_sidecar.tools import git_write
from git_sidecar.tools.git_lfs import LFS_TIMEOUT
from git_sidecar.validation import ValidationError

PREFIXES = ["task/", "feat/"]

CONFIG = SidecarConfig(
    projects_dir="/projects",
    allowed_branch_prefixes=PREFIXES,
)

REPO_PATH = pathlib.Path("/projects/my-org/my-repo")

OK_RESULT = ExecResult(returncode=0, stdout="ok", stderr="")
FAIL_RESULT = ExecResult(returncode=1, stdout="", stderr="error")


@pytest.fixture(autouse=True)
def setup_config():
    """Initialize git_write with test config before each test."""
    git_write.init(CONFIG)


def make_run_result(returncode=0, stdout="", stderr=""):
    """Build an ExecResult for testing."""
    return ExecResult(returncode=returncode, stdout=stdout, stderr=stderr)


@pytest.fixture()
def mock_verify():
    """Patch auth.verify_token to return REPO_PATH."""
    with patch(
        "git_sidecar.tools.git_write.auth.verify_token", return_value=REPO_PATH
    ) as m:
        yield m


@pytest.fixture()
def mock_run():
    """Patch executor.run to return OK_RESULT by default."""
    with patch("git_sidecar.tools.git_write.executor.run", return_value=OK_RESULT) as m:
        yield m


class TestGitAdd:
    """Tests for git_add."""

    def test_stages_files(self, mock_verify, mock_run):
        """Calls git add with file list."""
        result = git_write.git_add("my-org/my-repo", "token", ["src/foo.py"])
        assert result["ok"] is True
        mock_run.assert_called_once_with(
            ["git", "add", "--", "src/foo.py"], cwd=str(REPO_PATH)
        )

    def test_blocks_path_traversal(self, mock_verify):
        """Rejects .. in file paths."""
        with pytest.raises(ValidationError, match="traversal"):
            git_write.git_add("my-org/my-repo", "token", ["../../etc/passwd"])

    def test_multiple_files(self, mock_verify, mock_run):
        """Passes all files to git add."""
        git_write.git_add("my-org/my-repo", "token", ["a.py", "b.py"])
        mock_run.assert_called_once_with(
            ["git", "add", "--", "a.py", "b.py"], cwd=str(REPO_PATH)
        )


class TestGitRm:
    """Tests for git_rm."""

    def test_removes_file(self, mock_verify, mock_run):
        """Calls git rm with file list."""
        result = git_write.git_rm("my-org/my-repo", "token", ["old.py"])
        assert result["ok"] is True
        mock_run.assert_called_once_with(
            ["git", "rm", "--", "old.py"], cwd=str(REPO_PATH)
        )

    def test_blocks_path_traversal(self, mock_verify):
        """Rejects .. in file paths."""
        with pytest.raises(ValidationError, match="traversal"):
            git_write.git_rm("my-org/my-repo", "token", ["../outside.py"])


class TestGitCommit:
    """Tests for git_commit."""

    def _make_commit_run(self, user_name="Agent", user_email="agent@example.com"):
        """Return a side_effect list simulating a successful commit sequence."""
        name_result = make_run_result(0, user_name)
        email_result = make_run_result(0, user_email)
        staged_result = make_run_result(1)  # returncode 1 = has staged changes
        commit_result = make_run_result(0, "1 file changed")
        return [name_result, email_result, staged_result, commit_result]

    def test_successful_commit(self, mock_verify):
        """Commits with author env vars set from git config."""
        with patch(
            "git_sidecar.tools.git_write.executor.run",
            side_effect=self._make_commit_run(),
        ) as mock_run:
            result = git_write.git_commit("my-org/my-repo", "token", "my message")

        assert result["ok"] is True
        # Last call should be the actual commit
        commit_call = mock_run.call_args_list[-1]
        assert commit_call.args[0] == ["git", "commit", "-m", "my message"]
        env = commit_call.kwargs["env"]
        assert env["GIT_AUTHOR_NAME"] == "Agent"
        assert env["GIT_AUTHOR_EMAIL"] == "agent@example.com"
        assert env["GIT_COMMITTER_NAME"] == "Agent"
        assert env["GIT_COMMITTER_EMAIL"] == "agent@example.com"

    def test_fails_if_user_name_not_set(self, mock_verify):
        """Returns error if git config user.name is empty."""
        with patch(
            "git_sidecar.tools.git_write.executor.run",
            side_effect=[make_run_result(1, "")],  # git config user.name fails
        ):
            result = git_write.git_commit("my-org/my-repo", "token", "msg")

        assert result["ok"] is False
        assert "user.name" in result["stderr"]

    def test_fails_if_user_email_not_set(self, mock_verify):
        """Returns error if git config user.email is empty."""
        with patch(
            "git_sidecar.tools.git_write.executor.run",
            side_effect=[
                make_run_result(0, "Agent"),  # user.name ok
                make_run_result(1, ""),  # user.email fails
            ],
        ):
            result = git_write.git_commit("my-org/my-repo", "token", "msg")

        assert result["ok"] is False
        assert "user.email" in result["stderr"]

    def test_fails_if_nothing_staged(self, mock_verify):
        """Returns error if there are no staged changes."""
        with patch(
            "git_sidecar.tools.git_write.executor.run",
            side_effect=[
                make_run_result(0, "Agent"),
                make_run_result(0, "agent@example.com"),
                make_run_result(0),  # returncode 0 = nothing staged
            ],
        ):
            result = git_write.git_commit("my-org/my-repo", "token", "msg")

        assert result["ok"] is False
        assert "nothing staged" in result["stderr"]

    def test_reads_git_config_in_cwd(self, mock_verify):
        """Passes repo path as cwd when reading git config."""
        calls = []

        def capturing_run(args, **kwargs):
            calls.append((args, kwargs))
            if args == ["git", "config", "--get", "user.name"]:
                return make_run_result(0, "Agent")
            if args == ["git", "config", "--get", "user.email"]:
                return make_run_result(0, "agent@example.com")
            if args == ["git", "diff", "--cached", "--quiet"]:
                return make_run_result(1)
            return make_run_result(0, "committed")

        with patch(
            "git_sidecar.tools.git_write.executor.run", side_effect=capturing_run
        ):
            git_write.git_commit("my-org/my-repo", "token", "msg")

        for _, kwargs in calls:
            assert kwargs["cwd"] == str(REPO_PATH)


class TestGitRestore:
    """Tests for git_restore."""

    def test_restore_files(self, mock_verify, mock_run):
        """Calls git restore with files."""
        git_write.git_restore("my-org/my-repo", "token", ["src/foo.py"])
        mock_run.assert_called_once_with(
            ["git", "restore", "--", "src/foo.py"], cwd=str(REPO_PATH)
        )

    def test_restore_staged(self, mock_verify, mock_run):
        """Includes --staged when staged=True."""
        git_write.git_restore("my-org/my-repo", "token", ["src/foo.py"], staged=True)
        mock_run.assert_called_once_with(
            ["git", "restore", "--staged", "--", "src/foo.py"], cwd=str(REPO_PATH)
        )

    def test_blocks_path_traversal(self, mock_verify):
        """Rejects .. in file paths."""
        with pytest.raises(ValidationError, match="traversal"):
            git_write.git_restore("my-org/my-repo", "token", ["../../secret"])


class TestGitStash:
    """Tests for git_stash."""

    def test_push(self, mock_verify, mock_run):
        """Default push action calls git stash push."""
        git_write.git_stash("my-org/my-repo", "token")
        mock_run.assert_called_once_with(["git", "stash", "push"], cwd=str(REPO_PATH))

    def test_push_with_message(self, mock_verify, mock_run):
        """Push with message adds -m flag."""
        git_write.git_stash("my-org/my-repo", "token", action="push", message="wip")
        mock_run.assert_called_once_with(
            ["git", "stash", "push", "-m", "wip"], cwd=str(REPO_PATH)
        )

    def test_pop(self, mock_verify, mock_run):
        """Pop action calls git stash pop."""
        git_write.git_stash("my-org/my-repo", "token", action="pop")
        mock_run.assert_called_once_with(["git", "stash", "pop"], cwd=str(REPO_PATH))

    def test_pop_with_index(self, mock_verify, mock_run):
        """Pop with index appends stash ref."""
        git_write.git_stash("my-org/my-repo", "token", action="pop", index=2)
        mock_run.assert_called_once_with(
            ["git", "stash", "pop", "stash@{2}"], cwd=str(REPO_PATH)
        )

    def test_drop(self, mock_verify, mock_run):
        """Drop action calls git stash drop."""
        git_write.git_stash("my-org/my-repo", "token", action="drop", index=0)
        mock_run.assert_called_once_with(
            ["git", "stash", "drop", "stash@{0}"], cwd=str(REPO_PATH)
        )

    def test_show(self, mock_verify, mock_run):
        """Show action is allowed."""
        git_write.git_stash("my-org/my-repo", "token", action="show")
        mock_run.assert_called_once_with(["git", "stash", "show"], cwd=str(REPO_PATH))

    def test_invalid_action(self, mock_verify):
        """Invalid action raises ValidationError."""
        with pytest.raises(ValidationError, match="Invalid stash action"):
            git_write.git_stash("my-org/my-repo", "token", action="delete")

    def test_all_valid_actions(self, mock_verify, mock_run):
        """All declared valid actions are accepted."""
        for action in git_write.ALLOWED_STASH_ACTIONS:
            git_write.git_stash("my-org/my-repo", "token", action=action)


class TestGitPull:
    """Tests for git_pull."""

    def test_pull(self, mock_verify, mock_run):
        """Calls git pull."""
        result = git_write.git_pull("my-org/my-repo", "token")
        assert result["ok"] is True
        mock_run.assert_called_once_with(["git", "pull"], cwd=str(REPO_PATH))


class TestGitMerge:
    """Tests for git_merge."""

    def test_merge(self, mock_verify, mock_run):
        """Calls git merge with branch name."""
        git_write.git_merge("my-org/my-repo", "token", "task/feature")
        mock_run.assert_called_once_with(
            ["git", "merge", "task/feature"], cwd=str(REPO_PATH)
        )


# ---------------------------------------------------------------------------
# Worktree fixtures — provisioning is filesystem behaviour, so these build real
# directories (and, where the point is what git itself writes, a real repo).
# ---------------------------------------------------------------------------

WORKTREE_REPO = "my-org/my-repo"
WORKTREE_NAME = "my-worktree"
WORKTREE_TOKEN = "worktree-token"

GIT_IDENTITY = {
    "GIT_AUTHOR_NAME": "Test",
    "GIT_AUTHOR_EMAIL": "test@example.com",
    "GIT_COMMITTER_NAME": "Test",
    "GIT_COMMITTER_EMAIL": "test@example.com",
}


def init_git_repo(repo: pathlib.Path, ignore: str | None = None) -> None:
    """Initialize a real git repository with a single commit.

    Args:
        repo: Directory to initialize.
        ignore: Filename to write into a committed .gitignore. A worktree of
            this repository then stays clean when that file appears in it,
            which is what `git worktree remove` needs and what production,
            where the token file is gitignored, actually has.
    """
    executor.run(["git", "init", "-q", "-b", "main", "."], cwd=str(repo))
    (repo / "README.md").write_text("hello\n")
    tracked = ["README.md"]

    if ignore is not None:
        (repo / ".gitignore").write_text(ignore + "\n")
        tracked.append(".gitignore")

    executor.run(["git", "add", *tracked], cwd=str(repo))
    executor.run(["git", "commit", "-q", "-m", "init"], cwd=str(repo), env=GIT_IDENTITY)


@pytest.fixture()
def worktree_config(tmp_path):
    """Config rooted at a temp projects dir, with a non-default token filename."""
    return SidecarConfig(
        projects_dir=str(tmp_path),
        allowed_branch_prefixes=PREFIXES,
        token_filename=".custom-token",  # noqa: S106 — proves it is not hardcoded
    )


@pytest.fixture()
def fake_repo(worktree_config, tmp_path):
    """Repo directory with a token file, pointed at by git_write (no real git)."""
    repo = tmp_path / "my-org" / "my-repo"
    repo.mkdir(parents=True)
    (repo / worktree_config.token_filename).write_text(WORKTREE_TOKEN + "\n")
    git_write.init(worktree_config)
    return repo


@pytest.fixture()
def fake_worktree(fake_repo, tmp_path):
    """Directory git would just have created for a new worktree."""
    worktree = tmp_path / "my-org" / WORKTREE_NAME
    worktree.mkdir()
    return worktree


@pytest.fixture()
def main_repo(worktree_config, tmp_path):
    """Real git repo with a commit and a token file, pointed at by git_write."""
    repo = tmp_path / "my-org" / "my-repo"
    repo.mkdir(parents=True)
    init_git_repo(repo, ignore=worktree_config.token_filename)
    (repo / worktree_config.token_filename).write_text(WORKTREE_TOKEN + "\n")
    git_write.init(worktree_config)
    return repo


@pytest.fixture()
def added_worktree(main_repo, tmp_path):
    """Worktree created through the tool against a real repo."""
    worktree = tmp_path / "my-org" / WORKTREE_NAME
    result = git_write.git_worktree(
        WORKTREE_REPO,
        WORKTREE_TOKEN,
        action="add",
        path=str(worktree),
        branch="task/new-feature",
    )
    assert result["ok"] is True, result["stderr"]
    return worktree


class TestGitWorktree:
    """Tests for git_worktree."""

    def test_list(self, mock_verify, mock_run):
        """List action calls git worktree list."""
        git_write.git_worktree("my-org/my-repo", "token")
        mock_run.assert_called_once_with(
            ["git", "worktree", "list"], cwd=str(REPO_PATH)
        )

    def test_remove(self, mock_verify, mock_run):
        """Remove action calls git worktree remove with the resolved path."""
        wt_path = "/projects/my-org/my-wt"
        git_write.git_worktree("my-org/my-repo", "token", action="remove", path=wt_path)
        mock_run.assert_called_once_with(
            ["git", "worktree", "remove", wt_path], cwd=str(REPO_PATH)
        )

    def test_remove_resolves_a_relative_path(self, mock_verify, mock_run):
        """Remove takes a path from the projects root down and resolves it."""
        git_write.git_worktree(
            "my-org/my-repo", "token", action="remove", path="my-org/my-wt"
        )
        mock_run.assert_called_once_with(
            ["git", "worktree", "remove", "/projects/my-org/my-wt"],
            cwd=str(REPO_PATH),
        )

    def test_add(self, fake_repo, fake_worktree, mock_run):
        """Add action calls git worktree add with path."""
        result = git_write.git_worktree(
            WORKTREE_REPO, WORKTREE_TOKEN, action="add", path=str(fake_worktree)
        )
        assert result["ok"] is True
        mock_run.assert_called_once_with(
            ["git", "worktree", "add", str(fake_worktree)], cwd=str(fake_repo)
        )

    def test_add_with_branch(self, fake_repo, fake_worktree, mock_run):
        """Add action with branch calls git worktree add with -b flag."""
        result = git_write.git_worktree(
            WORKTREE_REPO,
            WORKTREE_TOKEN,
            action="add",
            path=str(fake_worktree),
            branch="task/new-feature",
        )
        assert result["ok"] is True
        mock_run.assert_called_once_with(
            ["git", "worktree", "add", "-b", "task/new-feature", str(fake_worktree)],
            cwd=str(fake_repo),
        )

    def test_projects_root_relative_path_is_resolved(
        self, fake_repo, fake_worktree, mock_run
    ):
        """A path from the projects root down reaches git as an absolute path."""
        result = git_write.git_worktree(
            WORKTREE_REPO,
            WORKTREE_TOKEN,
            action="add",
            path=f"my-org/{WORKTREE_NAME}",
        )

        assert result["ok"] is True
        mock_run.assert_called_once_with(
            ["git", "worktree", "add", str(fake_worktree)], cwd=str(fake_repo)
        )

    def test_path_escaping_the_projects_root_is_refused(self, fake_repo, mock_run):
        """A path outside the projects root raises, and git is never called."""
        with pytest.raises(auth.AuthError, match="escapes"):
            git_write.git_worktree(
                WORKTREE_REPO, WORKTREE_TOKEN, action="add", path="../elsewhere"
            )

        mock_run.assert_not_called()

    def test_path_inside_the_repository_is_refused(self, fake_repo, mock_run):
        """A worktree nested in its own repository raises before git runs."""
        with pytest.raises(ValidationError, match="inside the repository"):
            git_write.git_worktree(
                WORKTREE_REPO,
                WORKTREE_TOKEN,
                action="add",
                path=f"{WORKTREE_REPO}/{WORKTREE_NAME}",
            )

        mock_run.assert_not_called()

    def test_add_attaches_an_existing_branch(self, fake_repo, fake_worktree, mock_run):
        """create_branch=False puts the branch after the path, without -b."""
        result = git_write.git_worktree(
            WORKTREE_REPO,
            WORKTREE_TOKEN,
            action="add",
            path=str(fake_worktree),
            branch="task/new-feature",
            create_branch=False,
        )

        assert result["ok"] is True
        mock_run.assert_called_once_with(
            ["git", "worktree", "add", "--", str(fake_worktree), "task/new-feature"],
            cwd=str(fake_repo),
        )

    def test_invalid_action(self, mock_verify):
        """Arbitrary invalid action is blocked."""
        with pytest.raises(ValidationError, match="Invalid worktree action"):
            git_write.git_worktree("my-org/my-repo", "token", action="prune")

    def test_list_does_not_copy_the_token(
        self, fake_worktree, worktree_config, mock_run
    ):
        """List action provisions nothing."""
        result = git_write.git_worktree(WORKTREE_REPO, WORKTREE_TOKEN, action="list")

        assert result["ok"] is True
        assert not (fake_worktree / worktree_config.token_filename).exists()

    def test_remove_does_not_copy_the_token(
        self, fake_worktree, worktree_config, mock_run
    ):
        """Remove action provisions nothing."""
        result = git_write.git_worktree(
            WORKTREE_REPO, WORKTREE_TOKEN, action="remove", path=str(fake_worktree)
        )

        assert result["ok"] is True
        assert not (fake_worktree / worktree_config.token_filename).exists()

    def test_failed_add_does_not_copy_the_token(self, fake_worktree, worktree_config):
        """A failed git worktree add is returned as-is, with nothing provisioned."""
        with patch(
            "git_sidecar.tools.git_write.executor.run", return_value=FAIL_RESULT
        ):
            result = git_write.git_worktree(
                WORKTREE_REPO, WORKTREE_TOKEN, action="add", path=str(fake_worktree)
            )

        assert result["ok"] is False
        assert result["stderr"] == "error"
        assert not (fake_worktree / worktree_config.token_filename).exists()

    def test_add_reports_provisioning_failure(self, fake_repo, tmp_path, mock_run):
        """Provisioning failure surfaces to the caller, not a success-looking result."""
        missing = tmp_path / "my-org" / "never-created"

        result = git_write.git_worktree(
            WORKTREE_REPO, WORKTREE_TOKEN, action="add", path=str(missing)
        )

        assert result["ok"] is False
        assert result["returncode"] != 0
        assert "provision" in result["stderr"]
        assert WORKTREE_TOKEN not in result["stderr"]


class TestGitWorktreeAddProvisioning:
    """Tests for the token file a new worktree needs but never inherits."""

    def test_worktree_is_usable_by_git(self, added_worktree):
        """Git runs inside the new worktree — e.g. a suite shelling out to git."""
        result = executor.run(["git", "ls-files"], cwd=str(added_worktree))

        assert result.ok, result.stderr
        assert "README.md" in result.stdout

    def test_worktree_requires_one_absolute_path_for_every_user(
        self, added_worktree, tmp_path
    ):
        """Pins the deployment requirement: one tree, one absolute path.

        `git worktree add` records absolute paths in both of a worktree's
        pointer files, so a worktree is usable only under the prefix it was
        created with. The sidecar and the agent must therefore see the
        repository at the same absolute path; a container that mounts it
        elsewhere breaks every worktree it creates for the other user, and no
        post-processing in this module can compensate for that.
        """
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        shutil.move(tmp_path / "my-org", elsewhere / "my-org")
        moved = elsewhere / "my-org" / WORKTREE_NAME

        result = executor.run(["git", "ls-files"], cwd=str(moved))

        assert not result.ok
        assert "not a git repository" in result.stderr

    def test_worktree_is_not_prunable_after_add(self, main_repo, added_worktree):
        """The main clone's worktree bookkeeping is left intact.

        Guards against reintroducing a pointer rewrite here: making the reverse
        pointer relative breaks this on git < 2.48, where the worktree reads as
        prunable and `git worktree prune` proposes deleting its admin metadata
        out from under whoever is working in it.
        """
        listed = executor.run(
            ["git", "worktree", "list", "--porcelain"], cwd=str(main_repo)
        )
        pruned = executor.run(
            ["git", "worktree", "prune", "-n", "-v"], cwd=str(main_repo)
        )

        # "prunable" is a porcelain annotation line, not a substring match —
        # pytest's tmp_path is named after this test and contains the word.
        annotations = [
            line for line in listed.stdout.splitlines() if line.startswith("prunable")
        ]

        assert str(added_worktree) in listed.stdout
        assert annotations == []
        assert pruned.stdout.strip() == ""

    def test_token_file_is_copied(self, main_repo, added_worktree, worktree_config):
        """The gitignored token file travels, under the configured filename."""
        copied = added_worktree / worktree_config.token_filename

        assert copied.is_file()
        assert (
            copied.read_text()
            == (main_repo / worktree_config.token_filename).read_text()
        )

    def test_token_file_is_group_writable(self, added_worktree, worktree_config):
        """Mode 0o660 — the sidecar and the agent are different users, same group."""
        copied = added_worktree / worktree_config.token_filename

        assert stat.S_IMODE(copied.stat().st_mode) == 0o660

    def test_sidecar_calls_against_the_worktree_authorize(
        self, added_worktree, worktree_config
    ):
        """verify_token succeeds in the new worktree without a manual token drop."""
        resolved = auth.verify_token(
            worktree_config, f"my-org/{WORKTREE_NAME}", WORKTREE_TOKEN
        )

        assert resolved == added_worktree.resolve()

    def test_relative_path_is_resolved_against_the_projects_root(
        self, main_repo, tmp_path, worktree_config
    ):
        """A projects-root-relative path is provisioned, not just an absolute one."""
        result = git_write.git_worktree(
            WORKTREE_REPO,
            WORKTREE_TOKEN,
            action="add",
            path=f"my-org/{WORKTREE_NAME}",
            branch="task/relative",
        )
        worktree = tmp_path / "my-org" / WORKTREE_NAME

        assert result["ok"] is True, result["stderr"]
        assert (worktree / "README.md").is_file()
        assert (worktree / worktree_config.token_filename).is_file()

    def test_option_looking_branch_is_not_parsed_as_one(self, main_repo, tmp_path):
        """An attached branch reaches git as a name, not as the flag it resembles.

        A trailing positional to `git worktree add` is still option-parsed, so
        `--detach` in the branch slot detaches the new worktree instead of
        failing. Git refuses to name a branch with a leading dash, so a
        separator's worst case here is a lookup that finds nothing.
        """
        result = git_write.git_worktree(
            WORKTREE_REPO,
            WORKTREE_TOKEN,
            action="add",
            path=f"my-org/{WORKTREE_NAME}",
            branch="--detach",
            create_branch=False,
        )
        worktree = tmp_path / "my-org" / WORKTREE_NAME

        assert result["ok"] is False
        assert not worktree.exists()

    def test_a_removed_worktree_is_added_back_on_its_own_branch(
        self, main_repo, added_worktree, tmp_path
    ):
        """The recovery path: drop a worktree, reattach its branch elsewhere."""
        again = tmp_path / "my-org" / f"{WORKTREE_NAME}-again"
        before = executor.run(
            ["git", "rev-parse", "task/new-feature"], cwd=str(main_repo)
        )

        removed = git_write.git_worktree(
            WORKTREE_REPO, WORKTREE_TOKEN, action="remove", path=str(added_worktree)
        )
        readded = git_write.git_worktree(
            WORKTREE_REPO,
            WORKTREE_TOKEN,
            action="add",
            path=f"my-org/{WORKTREE_NAME}-again",
            branch="task/new-feature",
            create_branch=False,
        )
        after = executor.run(
            ["git", "rev-parse", "task/new-feature"], cwd=str(main_repo)
        )
        on_branch = executor.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=str(again)
        )

        assert removed["ok"] is True, removed["stderr"]
        assert readded["ok"] is True, readded["stderr"]
        assert after.stdout.strip() == before.stdout.strip()
        assert on_branch.stdout.strip() == "task/new-feature"
        assert (again / "README.md").is_file()


# ---------------------------------------------------------------------------
# Fetch fixtures — a remote is only configured on a real repository, so these
# build one with a second remote and a real repository behind it to fetch from.
# ---------------------------------------------------------------------------

UNCONFIGURED_REMOTE = "backup"
REMOTE_URL = "https://example.com/other/repo.git"
REMOTE_OPTION = "--upload-pack=/bin/sh"
OPTION_NAMED_REMOTE = "--upload-pack=false"


@pytest.fixture()
def origin_repo(tmp_path):
    """Real repository standing in for the fork's own origin."""
    origin = tmp_path / "remotes" / "origin"
    origin.mkdir(parents=True)
    init_git_repo(origin)
    return origin


@pytest.fixture()
def upstream_repo(tmp_path):
    """Real repository standing in for the reference repo a fork mirrors."""
    upstream = tmp_path / "remotes" / "upstream"
    upstream.mkdir(parents=True)
    init_git_repo(upstream)
    return upstream


@pytest.fixture()
def fetch_repo(main_repo, origin_repo, upstream_repo):
    """Real repo configured with an origin and a non-origin remote."""
    for name, remote_path in (("origin", origin_repo), ("upstream", upstream_repo)):
        added = executor.run(
            ["git", "remote", "add", name, str(remote_path)], cwd=str(main_repo)
        )
        assert added.ok, added.stderr
    return main_repo


class TestGitFetch:
    """Tests for git_fetch."""

    def test_fetch_defaults_to_origin(self, mock_verify, mock_run):
        """Omitting remote fetches origin, and looks nothing up on the way."""
        result = git_write.git_fetch("my-org/my-repo", "token")

        assert result["ok"] is True
        mock_run.assert_called_once_with(
            ["git", "fetch", "--", "origin"], cwd=str(REPO_PATH)
        )

    def test_fetches_a_configured_remote(self, fetch_repo, upstream_repo):
        """A non-origin remote is fetched for real — its new commit lands as a ref."""
        executor.run(
            ["git", "commit", "-q", "--allow-empty", "-m", "upstream work"],
            cwd=str(upstream_repo),
            env=GIT_IDENTITY,
        )
        head = executor.run(["git", "rev-parse", "HEAD"], cwd=str(upstream_repo))

        result = git_write.git_fetch(WORKTREE_REPO, WORKTREE_TOKEN, remote="upstream")

        fetched = executor.run(
            ["git", "rev-parse", "refs/remotes/upstream/main"], cwd=str(fetch_repo)
        )
        assert result["ok"] is True, result["stderr"]
        assert fetched.stdout.strip() == head.stdout.strip()

    def test_option_looking_name_is_resolved_not_parsed(
        self, fetch_repo, upstream_repo
    ):
        """A remote named like an option is fetched as a name.

        Git permits a remote called `--upload-pack=…`, so the configured-set
        rule admits one, and `git fetch <name>` without a `--` separator reads
        it as the option it resembles — running that command. The separator
        makes the worst case a lookup of a remote the operator configured
        themselves: drop it and this fetch dies in `false` instead.
        """
        added = executor.run(
            ["git", "remote", "add", "--", OPTION_NAMED_REMOTE, str(upstream_repo)],
            cwd=str(fetch_repo),
        )
        assert added.ok, added.stderr

        result = git_write.git_fetch(
            WORKTREE_REPO, WORKTREE_TOKEN, remote=OPTION_NAMED_REMOTE
        )

        fetched = executor.run(
            ["git", "rev-parse", f"refs/remotes/{OPTION_NAMED_REMOTE}/main"],
            cwd=str(fetch_repo),
        )
        assert result["ok"] is True, result["stderr"]
        assert fetched.ok, fetched.stderr

    def test_rejects_an_unconfigured_remote(self, fetch_repo):
        """A name this repository does not have is refused."""
        with pytest.raises(ValidationError, match="not configured"):
            git_write.git_fetch(
                WORKTREE_REPO, WORKTREE_TOKEN, remote=UNCONFIGURED_REMOTE
            )

    def test_rejects_a_url(self, fetch_repo):
        """A well-formed URL is refused: git would fetch it, the sidecar will not."""
        with pytest.raises(ValidationError, match="not configured"):
            git_write.git_fetch(WORKTREE_REPO, WORKTREE_TOKEN, remote=REMOTE_URL)

    def test_rejects_an_option(self, fetch_repo):
        """An option-looking value is refused."""
        with pytest.raises(ValidationError, match="not configured"):
            git_write.git_fetch(WORKTREE_REPO, WORKTREE_TOKEN, remote=REMOTE_OPTION)

    def test_rejects_an_empty_remote(self, fetch_repo):
        """An empty string is refused, not quietly treated as the default."""
        with pytest.raises(ValidationError, match="not configured"):
            git_write.git_fetch(WORKTREE_REPO, WORKTREE_TOKEN, remote="")

    def test_rejects_before_any_fetch_runs(self, fetch_repo):
        """The refusal lands before git fetch — no connection is ever attempted."""
        with patch(
            "git_sidecar.tools.git_write.executor.run", wraps=executor.run
        ) as spy:
            with pytest.raises(ValidationError):
                git_write.git_fetch(WORKTREE_REPO, WORKTREE_TOKEN, remote=REMOTE_URL)

        commands = [call.args[0] for call in spy.call_args_list]
        assert ["git", "remote"] in commands
        assert not any(command[:2] == ["git", "fetch"] for command in commands)


class TestGitCheckout:
    """Tests for git_checkout."""

    def test_checkout_main(self, mock_verify, mock_run):
        """Checking out main is allowed."""
        git_write.git_checkout("my-org/my-repo", "token", "main")
        mock_run.assert_called_once_with(
            ["git", "checkout", "main"], cwd=str(REPO_PATH)
        )

    def test_checkout_master(self, mock_verify, mock_run):
        """Checking out master is allowed."""
        git_write.git_checkout("my-org/my-repo", "token", "master")
        mock_run.assert_called_once_with(
            ["git", "checkout", "master"], cwd=str(REPO_PATH)
        )

    def test_checkout_valid_prefix(self, mock_verify, mock_run):
        """Checking out a branch with valid prefix is allowed."""
        git_write.git_checkout("my-org/my-repo", "token", "task/my-feature")
        mock_run.assert_called_once_with(
            ["git", "checkout", "task/my-feature"], cwd=str(REPO_PATH)
        )

    def test_checkout_invalid_prefix(self, mock_verify):
        """Checking out a branch with invalid prefix is blocked."""
        with pytest.raises(ValidationError):
            git_write.git_checkout("my-org/my-repo", "token", "release/1.0")

    def test_create_valid_branch(self, mock_verify, mock_run):
        """Creating a branch with valid prefix uses -b flag."""
        git_write.git_checkout("my-org/my-repo", "token", "task/new", create=True)
        mock_run.assert_called_once_with(
            ["git", "checkout", "-b", "task/new"], cwd=str(REPO_PATH)
        )

    def test_create_invalid_prefix(self, mock_verify):
        """Creating a branch with invalid prefix is blocked."""
        with pytest.raises(ValidationError):
            git_write.git_checkout(
                "my-org/my-repo", "token", "hotfix/urgent", create=True
            )


class TestGitPush:
    """Tests for git_push."""

    def test_push_valid_branch(self, mock_verify):
        """Pushes current branch to origin."""
        branch_result = make_run_result(0, "task/my-feature\n")
        no_lfs_files = make_run_result(0, "")
        push_result = make_run_result(0, "pushed")
        with patch(
            "git_sidecar.tools.git_write.executor.run",
            side_effect=[branch_result, no_lfs_files, push_result],
        ) as mock_run:
            result = git_write.git_push("my-org/my-repo", "token")

        assert result["ok"] is True
        push_call = mock_run.call_args_list[-1]
        assert push_call.args[0] == ["git", "push", "-u", "origin", "task/my-feature"]

    def test_push_blocks_main(self, mock_verify):
        """Blocks push when current branch is main."""
        branch_result = make_run_result(0, "main\n")
        with patch(
            "git_sidecar.tools.git_write.executor.run",
            return_value=branch_result,
        ):
            with pytest.raises(ValidationError, match="protected"):
                git_write.git_push("my-org/my-repo", "token")

    def test_push_blocks_master(self, mock_verify):
        """Blocks push when current branch is master."""
        branch_result = make_run_result(0, "master\n")
        with patch(
            "git_sidecar.tools.git_write.executor.run",
            return_value=branch_result,
        ):
            with pytest.raises(ValidationError, match="protected"):
                git_write.git_push("my-org/my-repo", "token")

    def test_push_blocks_invalid_prefix(self, mock_verify):
        """Blocks push when branch doesn't match allowed prefixes."""
        branch_result = make_run_result(0, "release/1.0\n")
        with patch(
            "git_sidecar.tools.git_write.executor.run",
            return_value=branch_result,
        ):
            with pytest.raises(ValidationError, match="does not match"):
                git_write.git_push("my-org/my-repo", "token")

    def test_push_no_force_flags(self, mock_verify):
        """git_push never passes force flags to executor."""
        branch_result = make_run_result(0, "task/safe\n")
        no_lfs_files = make_run_result(0, "")
        push_result = make_run_result(0, "pushed")
        with patch(
            "git_sidecar.tools.git_write.executor.run",
            side_effect=[branch_result, no_lfs_files, push_result],
        ) as mock_run:
            git_write.git_push("my-org/my-repo", "token")

        push_call = mock_run.call_args_list[-1]
        push_args = push_call.args[0]
        assert "--force" not in push_args
        assert "-f" not in push_args
        assert "--force-with-lease" not in push_args

    def test_push_returns_error_if_rev_parse_fails(self, mock_verify):
        """Returns executor error if branch detection fails."""
        fail_result = make_run_result(128, "", "not a git repo")
        with patch(
            "git_sidecar.tools.git_write.executor.run",
            return_value=fail_result,
        ):
            result = git_write.git_push("my-org/my-repo", "token")

        assert result["ok"] is False

    def test_push_uploads_lfs_objects_first(self, mock_verify):
        """Pushes LFS objects before refs when the checkout tracks LFS files."""
        branch_result = make_run_result(0, "task/my-feature\n")
        lfs_files = make_run_result(0, "assets/model.bin\n")
        lfs_push = make_run_result(0, "")
        push_result = make_run_result(0, "pushed")
        with patch(
            "git_sidecar.tools.git_write.executor.run",
            side_effect=[branch_result, lfs_files, lfs_push, push_result],
        ) as mock_run:
            result = git_write.git_push("my-org/my-repo", "token")

        assert result["ok"] is True
        lfs_call = mock_run.call_args_list[2]
        assert lfs_call.args[0] == ["git", "lfs", "push", "origin", "task/my-feature"]
        assert lfs_call.kwargs["timeout"] == LFS_TIMEOUT
        push_call = mock_run.call_args_list[3]
        assert push_call.args[0] == ["git", "push", "-u", "origin", "task/my-feature"]

    def test_push_aborts_if_lfs_push_fails(self, mock_verify):
        """Does not push refs when LFS object upload fails."""
        branch_result = make_run_result(0, "task/my-feature\n")
        lfs_files = make_run_result(0, "assets/model.bin\n")
        lfs_push_fail = make_run_result(2, "", "upload failed")
        with patch(
            "git_sidecar.tools.git_write.executor.run",
            side_effect=[branch_result, lfs_files, lfs_push_fail],
        ) as mock_run:
            result = git_write.git_push("my-org/my-repo", "token")

        assert result["ok"] is False
        assert "upload failed" in result["stderr"]
        for call in mock_run.call_args_list:
            assert call.args[0][:2] != ["git", "push"]

    def test_push_skips_lfs_when_detection_fails(self, mock_verify):
        """Pushes refs normally when git-lfs is unavailable or errors."""
        branch_result = make_run_result(0, "task/my-feature\n")
        lfs_check_fail = make_run_result(1, "", "'lfs' is not a git command")
        push_result = make_run_result(0, "pushed")
        with patch(
            "git_sidecar.tools.git_write.executor.run",
            side_effect=[branch_result, lfs_check_fail, push_result],
        ) as mock_run:
            result = git_write.git_push("my-org/my-repo", "token")

        assert result["ok"] is True
        push_call = mock_run.call_args_list[-1]
        assert push_call.args[0] == ["git", "push", "-u", "origin", "task/my-feature"]
