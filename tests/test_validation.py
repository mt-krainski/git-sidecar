"""Tests for git_sidecar.validation."""

import pytest

from git_sidecar.validation import (
    ValidationError,
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
