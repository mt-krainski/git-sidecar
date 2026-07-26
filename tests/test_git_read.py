"""Tests for git_sidecar.tools.git_read."""

import os
import pathlib
from unittest.mock import patch

import pytest

from git_sidecar import executor
from git_sidecar.config import SidecarConfig
from git_sidecar.executor import ExecResult
from git_sidecar.tools import git_read
from git_sidecar.validation import ValidationError

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def config(tmp_path):
    """SidecarConfig pointing at a temp projects directory."""
    return SidecarConfig(projects_dir=str(tmp_path))


@pytest.fixture(autouse=True)
def init_module(config):
    """Initialize the git_read module before each test."""
    git_read.init(config)


@pytest.fixture()
def repo_path(tmp_path):
    """Create a fake repository directory and write a token file."""
    repo = tmp_path / "my-org" / "my-repo"
    repo.mkdir(parents=True)
    (repo / ".git-sidecar-token").write_text("test-token")
    return repo


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

GOOD_RESULT = ExecResult(returncode=0, stdout="output", stderr="")
REPO = "my-org/my-repo"
TOKEN = "test-token"


def _mock_verify(repo_path: pathlib.Path):
    """Return a patcher that makes verify_token return repo_path."""
    return patch(
        "git_sidecar.tools.git_read.verify_token",
        return_value=repo_path,
    )


def _mock_run(result: ExecResult = GOOD_RESULT):
    """Return a patcher that makes executor.run return result."""
    return patch("git_sidecar.tools.git_read.executor.run", return_value=result)


# ---------------------------------------------------------------------------
# git_status
# ---------------------------------------------------------------------------


class TestGitStatus:
    """Tests for git_status."""

    def test_calls_git_status(self, repo_path):
        """Correct git command is issued."""
        with _mock_verify(repo_path), _mock_run() as mock_run:
            result = git_read.git_status(REPO, TOKEN)

        mock_run.assert_called_once_with(["git", "status"], cwd=str(repo_path))
        assert result == GOOD_RESULT.to_dict()

    def test_auth_called(self, repo_path):
        """verify_token is called with config, repo, and token."""
        with _mock_verify(repo_path) as mock_verify, _mock_run():
            git_read.git_status(REPO, TOKEN)

        mock_verify.assert_called_once_with(git_read._config, REPO, TOKEN)


# ---------------------------------------------------------------------------
# git_diff
# ---------------------------------------------------------------------------


class TestGitDiff:
    """Tests for git_diff."""

    def test_plain_diff(self, repo_path):
        """Plain diff with no options."""
        with _mock_verify(repo_path), _mock_run() as mock_run:
            git_read.git_diff(REPO, TOKEN)

        mock_run.assert_called_once_with(["git", "diff"], cwd=str(repo_path))

    def test_staged_diff(self, repo_path):
        """Staged diff includes --cached."""
        with _mock_verify(repo_path), _mock_run() as mock_run:
            git_read.git_diff(REPO, TOKEN, staged=True)

        args = mock_run.call_args[0][0]
        assert "--cached" in args

    def test_diff_with_ref(self, repo_path):
        """Ref is appended to args."""
        with _mock_verify(repo_path), _mock_run() as mock_run:
            git_read.git_diff(REPO, TOKEN, ref="HEAD~1")

        args = mock_run.call_args[0][0]
        assert "HEAD~1" in args

    def test_diff_with_files(self, repo_path):
        """Files are appended after separator."""
        with _mock_verify(repo_path), _mock_run() as mock_run:
            git_read.git_diff(REPO, TOKEN, files=["src/main.py"])

        args = mock_run.call_args[0][0]
        assert "--" in args
        assert "src/main.py" in args

    def test_path_traversal_in_files_rejected(self, repo_path):
        """Path traversal in files list raises ValidationError."""
        with _mock_verify(repo_path), _mock_run():
            with pytest.raises(ValidationError, match="traversal"):
                git_read.git_diff(REPO, TOKEN, files=["../secret"])


# ---------------------------------------------------------------------------
# git_diff(output=...) — writing a diff to a path is filesystem behaviour, so
# these run against a real repository rather than a mocked executor.
# ---------------------------------------------------------------------------

GIT_IDENTITY = {
    "GIT_AUTHOR_NAME": "Test",
    "GIT_AUTHOR_EMAIL": "test@example.com",
    "GIT_COMMITTER_NAME": "Test",
    "GIT_COMMITTER_EMAIL": "test@example.com",
}

# The convention is the contract, so the tests spell it out rather than
# importing it: an agent and a repository both expect this exact directory.
SIDECAR_DIR = ".git-sidecar"

# Longer than the 80 columns git assumes when it is not writing to a terminal,
# which is where it starts eliding the middle of a path in --stat output.
LONG_PATH = (
    "src/a-very/deeply/nested/directory/structure/that/goes/on/"
    "and/on/for/quite/a/while/module_name.py"
)


def run_git(repo: pathlib.Path, *args: str) -> ExecResult:
    """Run a git command in a repository and require it to succeed."""
    result = executor.run(["git", *args], cwd=str(repo), env=GIT_IDENTITY)
    assert result.ok, result.stderr
    return result


def _bypass_check(path: pathlib.Path):
    """Return the path check's answer from before a swap, leaving the write alone.

    A real swap between the check and the open is a race no test should depend
    on; patching the check reproduces its outcome — a stale answer — every run.
    """
    return patch(
        "git_sidecar.tools.git_read.resolve_output_path",
        return_value=path,
    )


@pytest.fixture()
def real_repo(repo_path):
    """Real git repository: two tracked files, and no entry for the sidecar dir.

    The committed .gitignore covers the token file only — every assertion that
    git stays quiet about .git-sidecar/ has to come from the directory itself.
    """
    run_git(repo_path, "init", "-q", "-b", "main", ".")
    (repo_path / ".gitignore").write_text(".git-sidecar-token\n")
    (repo_path / "one.txt").write_text("one\n")
    (repo_path / "two.txt").write_text("two\n")
    run_git(repo_path, "add", ".gitignore", "one.txt", "two.txt")
    run_git(repo_path, "commit", "-q", "-m", "init")
    return repo_path


@pytest.fixture()
def dirty_repo(real_repo):
    """Repository with an unstaged edit to each tracked file."""
    (real_repo / "one.txt").write_text("one\nedited\n")
    (real_repo / "two.txt").write_text("two\nedited\n")
    return real_repo


class TestGitDiffToPath:
    """Tests for git_diff writing its body to a path."""

    def test_writes_the_diff_to_the_output_path(self, dirty_repo):
        """The file holds exactly what git diff prints."""
        expected = run_git(dirty_repo, "diff").stdout
        assert "edited" in expected

        result = git_read.git_diff(REPO, TOKEN, output="review/diff.patch")

        assert result["ok"] is True
        written = dirty_repo / SIDECAR_DIR / "review" / "diff.patch"
        assert written.read_text() == expected

    def test_result_omits_the_diff_body(self, dirty_repo):
        """Nothing of the body comes back to the caller."""
        result = git_read.git_diff(REPO, TOKEN, output="diff.patch")

        assert "stdout" not in result
        assert not any("edited" in str(value) for value in result.values())

    def test_result_carries_the_resolved_path(self, dirty_repo):
        """The path is absolute and points at the file just written."""
        result = git_read.git_diff(REPO, TOKEN, output="review/diff.patch")

        written = pathlib.Path(result["path"])
        assert written.is_absolute()
        assert written == dirty_repo / SIDECAR_DIR / "review" / "diff.patch"
        assert written.is_file()

    def test_stat_is_gits_own_summary_for_the_selection(self, dirty_repo):
        """The stat comes from git, not from parsing the diff that was written."""
        expected = run_git(dirty_repo, "diff", "--stat=1000,900").stdout

        result = git_read.git_diff(REPO, TOKEN, output="diff.patch")

        assert result["stat"] == expected

    def test_stat_counts_match_the_written_diff(self, dirty_repo):
        """The stat describes the same selection as the body written beside it."""
        result = git_read.git_diff(REPO, TOKEN, output="diff.patch")
        body = (dirty_repo / SIDECAR_DIR / "diff.patch").read_text()

        assert body.count("diff --git ") == 2
        assert "one.txt" in result["stat"]
        assert "two.txt" in result["stat"]
        assert "2 files changed, 2 insertions(+)" in result["stat"]

    def test_stat_keeps_long_paths_whole(self, real_repo):
        """A long path is not elided, so it can be matched against the diff."""
        target = real_repo / LONG_PATH
        target.parent.mkdir(parents=True)
        target.write_text("x\n")
        run_git(real_repo, "add", LONG_PATH)

        result = git_read.git_diff(REPO, TOKEN, staged=True, output="diff.patch")

        assert LONG_PATH in result["stat"]

    def test_overwrites_an_existing_file(self, dirty_repo):
        """A stale package at the path is replaced, not appended to or refused."""
        target = dirty_repo / SIDECAR_DIR / "diff.patch"
        target.parent.mkdir()
        target.write_text("stale package\n")

        result = git_read.git_diff(REPO, TOKEN, output="diff.patch")

        assert result["ok"] is True
        assert target.read_text() == run_git(dirty_repo, "diff").stdout
        assert "stale" not in target.read_text()

    def test_empty_diff_writes_an_empty_file(self, real_repo):
        """A selection with no changes still writes, so the path is never stale."""
        target = real_repo / SIDECAR_DIR / "diff.patch"
        target.parent.mkdir()
        target.write_text("stale package\n")

        result = git_read.git_diff(REPO, TOKEN, output="diff.patch")

        assert result["ok"] is True
        assert target.read_text() == ""
        assert result["stat"] == ""

    def test_failed_diff_writes_nothing(self, dirty_repo):
        """A git failure comes back in today's shape, with no file left behind."""
        result = git_read.git_diff(REPO, TOKEN, ref="no-such-ref", output="diff.patch")

        assert result["ok"] is False
        assert result["stdout"] == ""
        assert result["stderr"]
        assert not (dirty_repo / SIDECAR_DIR).exists()

    def test_failed_stat_writes_nothing(self, dirty_repo):
        """The stat runs before the write, so a half package is never produced."""
        runs = [GOOD_RESULT, ExecResult(returncode=1, stdout="", stderr="stat failed")]
        with patch("git_sidecar.tools.git_read.executor.run", side_effect=runs):
            result = git_read.git_diff(REPO, TOKEN, output="diff.patch")

        assert result["ok"] is False
        assert result["stderr"] == "stat failed"
        assert not (dirty_repo / SIDECAR_DIR).exists()

    def test_unwritable_target_is_reported(self, dirty_repo):
        """A path that cannot be written fails the call instead of raising."""
        (dirty_repo / SIDECAR_DIR / "review").mkdir(parents=True)

        result = git_read.git_diff(REPO, TOKEN, output="review")

        assert result["ok"] is False
        assert result["returncode"] != 0
        assert "review" in result["stderr"]

    def test_output_omitted_is_unchanged(self, dirty_repo):
        """Without output the body comes back and nothing is written."""
        result = git_read.git_diff(REPO, TOKEN)

        assert "edited" in result["stdout"]
        assert "path" not in result
        assert "stat" not in result
        assert not (dirty_repo / SIDECAR_DIR).exists()


class TestGitDiffOutputDirectory:
    """Tests for the .git-sidecar/ directory the output lands in."""

    def test_directory_is_created_ignoring_itself(self, dirty_repo):
        """First use creates the directory and a .gitignore matching everything."""
        result = git_read.git_diff(REPO, TOKEN, output="diff.patch")

        sidecar = dirty_repo / SIDECAR_DIR
        assert pathlib.Path(result["path"]) == sidecar / "diff.patch"
        assert (sidecar / ".gitignore").read_text() == "*\n"

    def test_repository_stays_clean(self, dirty_repo):
        """Git reports nothing new — and no repository needs an entry for it.

        This one has a .gitignore that does not mention the directory; the
        directory ignoring itself is the whole mechanism.
        """
        entries = (dirty_repo / ".gitignore").read_text().split()
        assert SIDECAR_DIR not in entries
        assert f"{SIDECAR_DIR}/" not in entries
        before = run_git(dirty_repo, "status", "--porcelain").stdout

        git_read.git_diff(REPO, TOKEN, output="diff.patch")

        assert run_git(dirty_repo, "status", "--porcelain").stdout == before
        assert SIDECAR_DIR not in git_read.git_status(REPO, TOKEN)["stdout"]

    def test_existing_gitignore_is_left_as_found(self, dirty_repo):
        """A .gitignore we did not write is never rewritten."""
        sidecar = dirty_repo / SIDECAR_DIR
        sidecar.mkdir()
        (sidecar / ".gitignore").write_text("# mine\n")

        result = git_read.git_diff(REPO, TOKEN, output="diff.patch")

        assert result["ok"] is True
        assert (sidecar / ".gitignore").read_text() == "# mine\n"

    def test_existing_directory_is_not_repaired(self, dirty_repo):
        """An existing directory without a .gitignore is left without one."""
        sidecar = dirty_repo / SIDECAR_DIR
        sidecar.mkdir()

        result = git_read.git_diff(REPO, TOKEN, output="diff.patch")

        assert result["ok"] is True
        assert not (sidecar / ".gitignore").exists()

    def test_nested_output_creates_intermediate_directories(self, dirty_repo):
        """Directories on the way to a nested package are created."""
        result = git_read.git_diff(REPO, TOKEN, output="packages/x.diff")

        sidecar = dirty_repo / SIDECAR_DIR
        assert result["ok"] is True
        assert (sidecar / "packages" / "x.diff").is_file()
        assert (sidecar / ".gitignore").read_text() == "*\n"


class TestGitDiffToPathConfinement:
    """Tests for confining the output path to .git-sidecar/."""

    def test_traversal_rejected(self, dirty_repo):
        """'..' cannot walk out of the directory."""
        with pytest.raises(ValidationError, match="escapes"):
            git_read.git_diff(REPO, TOKEN, output="../../escape.patch")

        assert not (dirty_repo.parent / "escape.patch").exists()

    def test_tracked_source_cannot_be_overwritten(self, dirty_repo):
        """Nothing outside the directory is writable, tracked files included."""
        before = (dirty_repo / "one.txt").read_text()

        with pytest.raises(ValidationError, match="escapes"):
            git_read.git_diff(REPO, TOKEN, output="../one.txt")

        assert (dirty_repo / "one.txt").read_text() == before

    def test_absolute_path_rejected(self, dirty_repo, tmp_path):
        """An absolute path is rejected: output is relative to the directory."""
        escape = tmp_path / "escape.patch"

        with pytest.raises(ValidationError, match="must be relative"):
            git_read.git_diff(REPO, TOKEN, output=str(escape))

        assert not escape.exists()

    def test_symlink_escape_rejected(self, dirty_repo, tmp_path):
        """A symlink inside the directory cannot land the diff outside it."""
        outside = tmp_path / "outside"
        outside.mkdir()
        sidecar = dirty_repo / SIDECAR_DIR
        sidecar.mkdir()
        (sidecar / "link").symlink_to(outside)

        with pytest.raises(ValidationError, match="escapes"):
            git_read.git_diff(REPO, TOKEN, output="link/escape.patch")

        assert not (outside / "escape.patch").exists()

    def test_symlinked_directory_rejected(self, dirty_repo, tmp_path):
        """A .git-sidecar/ that is itself a symlink out is an escape too."""
        outside = tmp_path / "outside"
        outside.mkdir()
        (dirty_repo / SIDECAR_DIR).symlink_to(outside)

        with pytest.raises(ValidationError, match="escapes"):
            git_read.git_diff(REPO, TOKEN, output="escape.patch")

        assert not (outside / "escape.patch").exists()

    def test_empty_output_rejected(self, dirty_repo):
        """An empty path is rejected rather than read as 'omitted'."""
        with pytest.raises(ValidationError, match="cannot be empty"):
            git_read.git_diff(REPO, TOKEN, output="")

    def test_directory_itself_rejected(self, dirty_repo):
        """A path naming the directory rather than a file in it is rejected."""
        with pytest.raises(ValidationError, match="must name a file"):
            git_read.git_diff(REPO, TOKEN, output=".")

    def test_symlink_loop_rejected(self, dirty_repo):
        """An unresolvable path fails validation, not with a bare RuntimeError."""
        sidecar = dirty_repo / SIDECAR_DIR
        sidecar.mkdir()
        (sidecar / "loop").symlink_to("loop")

        with pytest.raises(ValidationError, match="cannot be resolved"):
            git_read.git_diff(REPO, TOKEN, output="loop")

    def test_null_byte_rejected(self, dirty_repo):
        """An embedded null fails validation, not with a bare ValueError."""
        with pytest.raises(ValidationError, match="null byte"):
            git_read.git_diff(REPO, TOKEN, output="diff\0.patch")


class TestGitDiffOutputWriteRefusals:
    """Tests for what the write refuses on its own, without help from the check.

    Two git subprocesses run between resolving the path and opening it, so a
    path can be swapped in that window; and a hardlink is an alias no path
    check can see at all. These plant each case and require the write to
    refuse. Where the swap would land after the check, the check is patched to
    return what it saw beforehand — the point is that the write does not depend
    on it.
    """

    def test_hardlinked_target_is_refused(self, dirty_repo, tmp_path):
        """A hardlink aliases another file's inode; truncating it would corrupt it.

        Nothing here is raced or patched: the path resolves inside the
        directory, because the alias is the file.
        """
        victim = tmp_path / "other-repo" / "victim.py"
        victim.parent.mkdir()
        victim.write_text("victim contents\n")
        sidecar = dirty_repo / SIDECAR_DIR
        sidecar.mkdir()
        os.link(victim, sidecar / "report.diff")

        result = git_read.git_diff(REPO, TOKEN, output="report.diff")

        assert result["ok"] is False
        assert "hard link" in result["stderr"]
        assert victim.read_text() == "victim contents\n"

    def test_symlinked_target_planted_after_the_check_is_refused(
        self, dirty_repo, tmp_path
    ):
        """A symlink at the final component fails the open instead of redirecting."""
        outside = tmp_path / "outside.py"
        outside.write_text("outside contents\n")
        sidecar = dirty_repo / SIDECAR_DIR
        sidecar.mkdir()
        (sidecar / "report.diff").symlink_to(outside)

        with _bypass_check(sidecar / "report.diff"):
            result = git_read.git_diff(REPO, TOKEN, output="report.diff")

        assert result["ok"] is False
        assert outside.read_text() == "outside contents\n"

    def test_symlinked_intermediate_planted_after_the_check_is_refused(
        self, dirty_repo, tmp_path
    ):
        """A swapped intermediate directory cannot redirect the write either.

        mkdir(exist_ok=True) accepts a symlink to a directory; opening the
        component with O_NOFOLLOW does not.
        """
        outside = tmp_path / "outside"
        outside.mkdir()
        sidecar = dirty_repo / SIDECAR_DIR
        sidecar.mkdir()
        (sidecar / "packages").symlink_to(outside)

        with _bypass_check(sidecar / "packages" / "report.diff"):
            result = git_read.git_diff(REPO, TOKEN, output="packages/report.diff")

        assert result["ok"] is False
        assert list(outside.iterdir()) == []

    def test_symlinked_directory_planted_after_the_check_is_refused(
        self, dirty_repo, tmp_path
    ):
        """The sidecar directory itself is opened with O_NOFOLLOW, not followed."""
        outside = tmp_path / "outside"
        outside.mkdir()
        sidecar = dirty_repo / SIDECAR_DIR
        sidecar.symlink_to(outside)

        with _bypass_check(sidecar / "report.diff"):
            result = git_read.git_diff(REPO, TOKEN, output="report.diff")

        assert result["ok"] is False
        assert list(outside.iterdir()) == []

    def test_non_regular_target_is_refused(self, dirty_repo):
        """A fifo at the path is refused rather than written through."""
        sidecar = dirty_repo / SIDECAR_DIR
        sidecar.mkdir()
        os.mkfifo(sidecar / "report.diff")
        # A reader makes the non-blocking open succeed, so the refusal has to
        # come from the descriptor check rather than from ENXIO.
        reader = os.open(sidecar / "report.diff", os.O_RDONLY | os.O_NONBLOCK)
        try:
            result = git_read.git_diff(REPO, TOKEN, output="report.diff")
        finally:
            os.close(reader)

        assert result["ok"] is False
        assert "regular file" in result["stderr"]


class TestGitDiffToPathSelectors:
    """Tests that the selectors narrow both the written diff and the stat."""

    def test_files_selector(self, dirty_repo):
        """A file list narrows both."""
        result = git_read.git_diff(REPO, TOKEN, files=["one.txt"], output="diff.patch")
        body = (dirty_repo / SIDECAR_DIR / "diff.patch").read_text()

        assert "one.txt" in body
        assert "two.txt" not in body
        assert "one.txt" in result["stat"]
        assert "two.txt" not in result["stat"]
        assert "1 file changed" in result["stat"]

    def test_staged_selector(self, dirty_repo):
        """--cached narrows both to the index."""
        (dirty_repo / "three.txt").write_text("three\n")
        run_git(dirty_repo, "add", "three.txt")

        result = git_read.git_diff(REPO, TOKEN, staged=True, output="diff.patch")
        body = (dirty_repo / SIDECAR_DIR / "diff.patch").read_text()

        assert "three.txt" in body
        assert "one.txt" not in body
        assert "three.txt" in result["stat"]
        assert "one.txt" not in result["stat"]
        assert "1 file changed" in result["stat"]

    def test_ref_selector(self, real_repo):
        """A ref selects what both compare against."""
        (real_repo / "one.txt").write_text("one\nsecond commit\n")
        run_git(real_repo, "commit", "-q", "-a", "-m", "second")

        result = git_read.git_diff(REPO, TOKEN, ref="HEAD~1", output="diff.patch")
        body = (real_repo / SIDECAR_DIR / "diff.patch").read_text()

        assert "second commit" in body
        assert "one.txt" in result["stat"]
        assert "two.txt" not in result["stat"]
        assert "1 file changed" in result["stat"]

    def test_files_traversal_still_rejected(self, dirty_repo):
        """A file selector that escapes is rejected even with an output path."""
        with pytest.raises(ValidationError, match="traversal"):
            git_read.git_diff(REPO, TOKEN, files=["../secret"], output="diff.patch")

        assert not (dirty_repo / SIDECAR_DIR).exists()


# ---------------------------------------------------------------------------
# git_log
# ---------------------------------------------------------------------------


class TestGitLog:
    """Tests for git_log."""

    def test_default_log(self, repo_path):
        """Default log uses --max-count=20."""
        with _mock_verify(repo_path), _mock_run() as mock_run:
            git_read.git_log(REPO, TOKEN)

        args = mock_run.call_args[0][0]
        assert "--max-count=20" in args

    def test_custom_max_count(self, repo_path):
        """Custom max_count is applied."""
        with _mock_verify(repo_path), _mock_run() as mock_run:
            git_read.git_log(REPO, TOKEN, max_count=5)

        args = mock_run.call_args[0][0]
        assert "--max-count=5" in args

    def test_oneline(self, repo_path):
        """oneline=True adds --oneline flag."""
        with _mock_verify(repo_path), _mock_run() as mock_run:
            git_read.git_log(REPO, TOKEN, oneline=True)

        args = mock_run.call_args[0][0]
        assert "--oneline" in args

    def test_log_with_ref(self, repo_path):
        """Ref is appended when provided."""
        with _mock_verify(repo_path), _mock_run() as mock_run:
            git_read.git_log(REPO, TOKEN, ref="main")

        args = mock_run.call_args[0][0]
        assert "main" in args


# ---------------------------------------------------------------------------
# git_show
# ---------------------------------------------------------------------------


class TestGitShow:
    """Tests for git_show."""

    def test_default_ref(self, repo_path):
        """Default ref is HEAD."""
        with _mock_verify(repo_path), _mock_run() as mock_run:
            git_read.git_show(REPO, TOKEN)

        args = mock_run.call_args[0][0]
        assert args == ["git", "show", "HEAD"]

    def test_custom_ref(self, repo_path):
        """Custom ref is passed through."""
        with _mock_verify(repo_path), _mock_run() as mock_run:
            git_read.git_show(REPO, TOKEN, ref="abc1234")

        args = mock_run.call_args[0][0]
        assert "abc1234" in args


# ---------------------------------------------------------------------------
# git_branch
# ---------------------------------------------------------------------------


class TestGitBranch:
    """Tests for git_branch."""

    def test_local_branches(self, repo_path):
        """Without all=True, --all is not included."""
        with _mock_verify(repo_path), _mock_run() as mock_run:
            git_read.git_branch(REPO, TOKEN)

        args = mock_run.call_args[0][0]
        assert "--all" not in args

    def test_all_branches(self, repo_path):
        """all=True includes --all flag."""
        with _mock_verify(repo_path), _mock_run() as mock_run:
            git_read.git_branch(REPO, TOKEN, all=True)

        args = mock_run.call_args[0][0]
        assert "--all" in args


# ---------------------------------------------------------------------------
# git_rev_parse
# ---------------------------------------------------------------------------


class TestGitRevParse:
    """Tests for git_rev_parse."""

    def test_default_head(self, repo_path):
        """Default ref resolves HEAD."""
        with _mock_verify(repo_path), _mock_run() as mock_run:
            git_read.git_rev_parse(REPO, TOKEN)

        args = mock_run.call_args[0][0]
        assert args == ["git", "rev-parse", "HEAD"]

    def test_custom_ref(self, repo_path):
        """Custom ref is passed through."""
        with _mock_verify(repo_path), _mock_run() as mock_run:
            git_read.git_rev_parse(REPO, TOKEN, ref="main")

        args = mock_run.call_args[0][0]
        assert "main" in args


# ---------------------------------------------------------------------------
# git_ls_files
# ---------------------------------------------------------------------------


class TestGitLsFiles:
    """Tests for git_ls_files."""

    def test_ls_files(self, repo_path):
        """Correct command is issued."""
        with _mock_verify(repo_path), _mock_run() as mock_run:
            git_read.git_ls_files(REPO, TOKEN)

        mock_run.assert_called_once_with(["git", "ls-files"], cwd=str(repo_path))


# ---------------------------------------------------------------------------
# git_stash_list
# ---------------------------------------------------------------------------


class TestGitStashList:
    """Tests for git_stash_list."""

    def test_stash_list(self, repo_path):
        """Correct command is issued."""
        with _mock_verify(repo_path), _mock_run() as mock_run:
            git_read.git_stash_list(REPO, TOKEN)

        mock_run.assert_called_once_with(["git", "stash", "list"], cwd=str(repo_path))


# ---------------------------------------------------------------------------
# git_remote
# ---------------------------------------------------------------------------


class TestGitRemote:
    """Tests for git_remote."""

    def test_remote_verbose(self, repo_path):
        """Uses -v flag for URL output."""
        with _mock_verify(repo_path), _mock_run() as mock_run:
            git_read.git_remote(REPO, TOKEN)

        mock_run.assert_called_once_with(["git", "remote", "-v"], cwd=str(repo_path))


# ---------------------------------------------------------------------------
# git_blame
# ---------------------------------------------------------------------------


class TestGitBlame:
    """Tests for git_blame."""

    def test_blame_file(self, repo_path):
        """Correct command with the file argument."""
        with _mock_verify(repo_path), _mock_run() as mock_run:
            git_read.git_blame(REPO, TOKEN, file="src/main.py")

        mock_run.assert_called_once_with(
            ["git", "blame", "src/main.py"], cwd=str(repo_path)
        )

    def test_path_traversal_rejected(self, repo_path):
        """Path traversal in file raises ValidationError before auth."""
        with _mock_verify(repo_path), _mock_run():
            with pytest.raises(ValidationError, match="traversal"):
                git_read.git_blame(REPO, TOKEN, file="../etc/passwd")

    def test_validation_before_auth(self):
        """File validation happens before verify_token is called."""
        with (
            patch("git_sidecar.tools.git_read.verify_token") as mock_verify,
            _mock_run(),
        ):
            with pytest.raises(ValidationError):
                git_read.git_blame(REPO, TOKEN, file="../escape")

            mock_verify.assert_not_called()


# ---------------------------------------------------------------------------
# git_tag
# ---------------------------------------------------------------------------


class TestGitTag:
    """Tests for git_tag."""

    def test_tag_list(self, repo_path):
        """Correct command is issued."""
        with _mock_verify(repo_path), _mock_run() as mock_run:
            git_read.git_tag(REPO, TOKEN)

        mock_run.assert_called_once_with(["git", "tag"], cwd=str(repo_path))


# ---------------------------------------------------------------------------
# git_config_get
# ---------------------------------------------------------------------------


class TestGitConfigGet:
    """Tests for git_config_get."""

    def test_config_get(self, repo_path):
        """Correct command with key argument."""
        with _mock_verify(repo_path), _mock_run() as mock_run:
            git_read.git_config_get(REPO, TOKEN, key="user.email")

        mock_run.assert_called_once_with(
            ["git", "config", "--get", "user.email"], cwd=str(repo_path)
        )


# ---------------------------------------------------------------------------
# Init / config wiring
# ---------------------------------------------------------------------------


class TestInit:
    """Tests for module-level init."""

    def test_init_sets_config(self):
        """init() stores config for subsequent calls."""
        cfg = SidecarConfig(projects_dir="/tmp")  # noqa: S108
        git_read.init(cfg)
        assert git_read._config is cfg

    def test_uninitialised_raises(self):
        """Calling a tool before init raises RuntimeError."""
        original = git_read._config
        git_read._config = None
        try:
            with pytest.raises(RuntimeError, match="not initialized"):
                git_read.git_status("repo", "token")
        finally:
            git_read._config = original
