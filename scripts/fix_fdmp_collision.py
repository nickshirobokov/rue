"""Hotfix for fast-diff-match-patch's site-packages collision.

The fast-diff-match-patch wheel ships a top-level ``tests`` package into
site-packages, colliding with the project's own ``tests/`` namespace. Run this
script after ``uv sync`` to scrub the polluted directory. Idempotent.
"""

import shutil
import sysconfig
from pathlib import Path


def main() -> None:
    """Remove the colliding ``tests`` package from the active site-packages."""
    site_packages = Path(sysconfig.get_paths()["purelib"])
    polluted = site_packages / "tests"
    fdmp_present = any(site_packages.glob("fast_diff_match_patch*"))
    if polluted.is_dir() and fdmp_present:
        shutil.rmtree(polluted)
        print(f"removed {polluted}")
    else:
        print("no collision")


if __name__ == "__main__":
    main()
