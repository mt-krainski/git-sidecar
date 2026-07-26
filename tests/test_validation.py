"""Tests for git_sidecar.validation."""

import pytest

from git_sidecar.validation import (
    ValidationError,
    resolve_output_path,
    validate_branch_prefix,
    validate_checkout_target,
    validate_file_args,
    validate_no_force_flags,
    validate_push_branch,
)

PREFIXES = ["task/", "feat/", "kan-"]


class TestValidateBranchPrefix:
    """Tests for validate_branch_prefix."""

    def test_matching_prefix(self):
        """Branch with valid prefix passes."""
        validate_branch_prefix("task/add-feature", PREFIXES)

    def test_no_match(self):
        """Branch without valid prefix is rejected."""
        with pytest.raises(ValidationError, match="does not match"):
            validate_branch_prefix("hotfix/urgent", PREFIXES)

    def test_empty_branch(self):
        """Empty branch name is rejected."""
        with pytest.raises(ValidationError, match="cannot be empty"):
            validate_branch_prefix("", PREFIXES)

    def test_exact_prefix(self):
        """Branch that is exactly a prefix still matches."""
        validate_branch_prefix("task/", PREFIXES)

    def test_case_sensitive(self):
        """Prefix matching is case-sensitive."""
        with pytest.raises(ValidationError):
            validate_branch_prefix("Task/something", PREFIXES)


class TestValidatePushBranch:
    """Tests for validate_push_branch."""

    def test_valid_push(self):
        """Push to allowed branch passes."""
        validate_push_branch("task/my-feature", PREFIXES)

    def test_block_main(self):
        """Push to main is blocked."""
        with pytest.raises(ValidationError, match="protected"):
            validate_push_branch("main", PREFIXES)

    def test_block_master(self):
        """Push to master is blocked."""
        with pytest.raises(ValidationError, match="protected"):
            validate_push_branch("master", PREFIXES)

    def test_block_wrong_prefix(self):
        """Push to branch with wrong prefix is blocked."""
        with pytest.raises(ValidationError, match="does not match"):
            validate_push_branch("release/1.0", PREFIXES)


class TestValidateCheckoutTarget:
    """Tests for validate_checkout_target."""

    def test_checkout_main(self):
        """Checkout of main is allowed."""
        validate_checkout_target("main", PREFIXES)

    def test_checkout_master(self):
        """Checkout of master is allowed."""
        validate_checkout_target("master", PREFIXES)

    def test_create_valid_branch(self):
        """Creating a branch with valid prefix is allowed."""
        validate_checkout_target("task/new-thing", PREFIXES, create=True)

    def test_create_invalid_prefix(self):
        """Creating a branch with wrong prefix is blocked."""
        with pytest.raises(ValidationError):
            validate_checkout_target("release/1.0", PREFIXES, create=True)

    def test_checkout_existing_valid(self):
        """Checking out an existing branch with valid prefix is allowed."""
        validate_checkout_target("feat/existing", PREFIXES)

    def test_checkout_existing_invalid(self):
        """Checking out a branch with invalid prefix is blocked."""
        with pytest.raises(ValidationError):
            validate_checkout_target("release/old", PREFIXES)


class TestValidateNoForceFlags:
    """Tests for validate_no_force_flags."""

    def test_no_flags(self):
        """Normal args pass."""
        validate_no_force_flags(["origin", "task/x"])

    def test_force(self):
        """--force is blocked."""
        with pytest.raises(ValidationError, match="--force"):
            validate_no_force_flags(["--force", "origin"])

    def test_short_force(self):
        """-f is blocked."""
        with pytest.raises(ValidationError, match="-f"):
            validate_no_force_flags(["-f", "origin"])

    def test_force_with_lease(self):
        """--force-with-lease is blocked."""
        with pytest.raises(ValidationError, match="force-with-lease"):
            validate_no_force_flags(["--force-with-lease"])


class TestValidateFileArgs:
    """Tests for validate_file_args."""

    def test_normal_paths(self):
        """Normal relative paths pass."""
        validate_file_args(["src/main.py", "tests/test_foo.py"])

    def test_dotdot_blocked(self):
        """Path traversal with .. is blocked."""
        with pytest.raises(ValidationError, match="traversal"):
            validate_file_args(["../../../etc/passwd"])

    def test_dotdot_in_middle(self):
        """.. in the middle of a path is blocked."""
        with pytest.raises(ValidationError, match="traversal"):
            validate_file_args(["src/../../secrets"])

    def test_double_dot_in_name(self):
        """File names containing .. as part of the name are fine."""
        validate_file_args(["file..name.txt"])

    def test_empty_list(self):
        """Empty file list passes."""
        validate_file_args([])


class TestResolveOutputPath:
    """Tests for resolve_output_path.

    The base is the directory an output path is confined to — a resolved
    absolute path the caller supplies.
    """

    @pytest.fixture()
    def base(self, tmp_path):
        """Resolved base directory that does not exist yet."""
        return tmp_path.resolve() / "repo" / ".git-sidecar"

    def test_relative_path(self, base):
        """A relative path resolves against the base."""
        assert resolve_output_path(base, "diff.patch") == base / "diff.patch"

    def test_path_need_not_exist_yet(self, base):
        """Neither the base nor the directories under it need exist."""
        assert resolve_output_path(base, "packages/2026/diff.patch") == (
            base / "packages" / "2026" / "diff.patch"
        )

    def test_empty_rejected(self, base):
        """An empty path is rejected rather than resolving to the base itself."""
        with pytest.raises(ValidationError, match="cannot be empty"):
            resolve_output_path(base, "")

    def test_traversal_rejected(self, base):
        """'..' cannot walk out of the base."""
        with pytest.raises(ValidationError, match="escapes"):
            resolve_output_path(base, "../README.md")

    def test_traversal_that_lands_inside_is_allowed(self, base):
        """The rule is where the path lands, not how it is spelled."""
        assert resolve_output_path(base, "packages/../diff.patch") == (
            base / "diff.patch"
        )

    def test_absolute_rejected(self, base):
        """An absolute path is rejected: output is relative to the base."""
        with pytest.raises(ValidationError, match="must be relative"):
            resolve_output_path(base, "/etc/passwd")

    def test_absolute_inside_the_base_rejected(self, base):
        """An absolute path that lands inside is rejected too — the contract is relative."""  # noqa: E501
        with pytest.raises(ValidationError, match="must be relative"):
            resolve_output_path(base, str(base / "diff.patch"))

    def test_base_itself_rejected(self, base):
        """A path naming the base rather than a file below it is rejected."""
        with pytest.raises(ValidationError, match="must name a file"):
            resolve_output_path(base, ".")

    def test_null_byte_rejected(self, base):
        """An embedded null is a validation failure, not a bare ValueError."""
        with pytest.raises(ValidationError, match="null byte"):
            resolve_output_path(base, "diff\0.patch")

    def test_unresolvable_path_rejected(self, tmp_path):
        """A symlink loop is a validation failure, not a bare RuntimeError."""
        base = tmp_path.resolve() / ".git-sidecar"
        base.mkdir()
        (base / "loop").symlink_to("loop")

        with pytest.raises(ValidationError, match="cannot be resolved"):
            resolve_output_path(base, "loop")

    def test_error_names_the_directory(self, base):
        """The message tells an agent which directory it has to stay inside."""
        with pytest.raises(ValidationError, match=r"\.git-sidecar"):
            resolve_output_path(base, "../README.md")

    def test_symlinked_directory_escape_rejected(self, tmp_path):
        """A symlinked directory inside the base cannot land the file outside."""
        base = tmp_path.resolve() / ".git-sidecar"
        base.mkdir()
        outside = tmp_path.resolve() / "outside"
        outside.mkdir()
        (base / "link").symlink_to(outside)

        with pytest.raises(ValidationError, match="escapes"):
            resolve_output_path(base, "link/escape.patch")

    def test_symlinked_file_escape_rejected(self, tmp_path):
        """A symlink at the path itself is followed before the check."""
        base = tmp_path.resolve() / ".git-sidecar"
        base.mkdir()
        outside = tmp_path.resolve() / "outside.patch"
        outside.write_text("")
        (base / "diff.patch").symlink_to(outside)

        with pytest.raises(ValidationError, match="escapes"):
            resolve_output_path(base, "diff.patch")

    def test_symlinked_base_rejected(self, tmp_path):
        """A base that is itself a symlink elsewhere is an escape, not a shortcut."""
        outside = tmp_path.resolve() / "outside"
        outside.mkdir()
        base = tmp_path.resolve() / ".git-sidecar"
        base.symlink_to(outside)

        with pytest.raises(ValidationError, match="escapes"):
            resolve_output_path(base, "diff.patch")

    def test_sibling_sharing_a_name_prefix_rejected(self, tmp_path):
        """Confinement is component-wise, not a string prefix.

        A sibling directory whose name merely starts with the base's is outside
        the base — a startswith() comparison would admit it.
        """
        base = tmp_path.resolve() / "packages"
        base.mkdir()
        sibling = tmp_path.resolve() / "packages-backup"
        sibling.mkdir()
        (base / "link").symlink_to(sibling)

        with pytest.raises(ValidationError, match="escapes"):
            resolve_output_path(base, "link/escape.patch")
