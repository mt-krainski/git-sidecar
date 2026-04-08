"""CLI tool to create git-sidecar token files."""

import argparse
import pathlib
import secrets
import sys


def main() -> None:
    """Generate a .git-sidecar-token file in a project directory."""
    parser = argparse.ArgumentParser(
        description="Create a git-sidecar authentication token for a project.",
    )
    parser.add_argument(
        "directory",
        type=pathlib.Path,
        help="Project directory to create the token in.",
    )
    parser.add_argument(
        "--filename",
        default=".git-sidecar-token",
        help="Token filename (default: .git-sidecar-token).",
    )
    parser.add_argument(
        "--no-gitignore",
        action="store_true",
        help="Skip adding the token file to .gitignore.",
    )
    args = parser.parse_args()

    directory: pathlib.Path = args.directory.resolve()
    if not directory.is_dir():
        print(f"Error: {directory} is not a directory", file=sys.stderr)  # noqa: T201
        sys.exit(1)

    token_path = directory / args.filename
    if token_path.exists():
        print(  # noqa: T201
            f"Error: {token_path} already exists. "
            "Remove it first to generate a new token.",
            file=sys.stderr,
        )
        sys.exit(1)

    token = secrets.token_urlsafe(32)
    token_path.write_text(token)
    print(f"Token written to {token_path}")  # noqa: T201

    if not args.no_gitignore:
        _add_to_gitignore(directory, args.filename)


def _add_to_gitignore(directory: pathlib.Path, filename: str) -> None:
    """Append the token filename to .gitignore if not already present."""
    gitignore = directory / ".gitignore"

    if gitignore.exists():
        content = gitignore.read_text()
        if filename in content.splitlines():
            return
        # Ensure we start on a new line
        if content and not content.endswith("\n"):
            content += "\n"
        content += filename + "\n"
        gitignore.write_text(content)
    else:
        gitignore.write_text(filename + "\n")

    print(f"Added {filename} to {gitignore}")  # noqa: T201


if __name__ == "__main__":
    main()
