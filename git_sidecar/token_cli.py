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


if __name__ == "__main__":
    main()
