"""Environment capture utilities for test runs."""

import subprocess

from rue.testing.models import RunEnvironment


def _get_git_info() -> tuple[str | None, str | None, bool | None]:
    """Capture git metadata if available."""
    try:
        subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            check=True,
            capture_output=True,
            timeout=1,
        )

        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            timeout=1,
        ).stdout.strip()

        branch = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            timeout=1,
        ).stdout.strip()

        status = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            check=True,
            timeout=1,
        ).stdout.strip()
        dirty = bool(status)

        return commit, branch, dirty

    except (subprocess.SubprocessError, FileNotFoundError):
        return None, None, None


def capture_environment() -> RunEnvironment:
    """Capture current environment metadata."""
    commit, branch, dirty = _get_git_info()

    return RunEnvironment(commit_hash=commit, branch=branch, dirty=dirty)
