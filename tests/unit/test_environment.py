"""Unit tests for the `Environment` resource and its supporting modules."""

from __future__ import annotations

import asyncio
import os
import pickle
import subprocess
import sys
from pathlib import Path, PurePosixPath
from uuid import uuid4

import pytest

from rue.context.models import ScopeOwner
from rue.context.scopes import CurrentProcessKind, Scope
from rue.environment import (
    DirSource,
    EmptySource,
    Environment,
    EnvironmentSyncState,
    EnvironmentVars,
    GitSource,
)
from rue.environment.checkpoint import Checkpoint, Diff
from rue.environment.sources import (
    dir as env_dir,
    empty as env_empty,
    git as env_git,
)
from rue.environment.storage import (
    EnvironmentStorage,
    clone_tree,
    empty_tree,
)


@pytest.fixture
def env_root(tmp_path: Path) -> Path:
    root = tmp_path / "env"
    root.mkdir()
    return root


@pytest.fixture
def env(env_root: Path) -> Environment:
    return Environment._build(root=env_root, scope=Scope.TEST)


def test_path_resolves_under_root(env: Environment, env_root: Path) -> None:
    target = env.path("a/b.txt")
    assert target == (env_root / "a" / "b.txt").resolve()


def test_path_rejects_relative_traversal(env: Environment) -> None:
    with pytest.raises(ValueError, match="resolves outside"):
        env.path("../../etc/passwd")


def test_path_rejects_absolute_outside(env: Environment) -> None:
    with pytest.raises(ValueError, match="resolves outside"):
        env.path("/etc/passwd")


def test_path_rejects_symlink_pointing_outside(
    env: Environment, env_root: Path, tmp_path: Path
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (env_root / "link").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="resolves outside"):
        env.path("link/secret.txt")


def test_environment_vars_overlay_basic() -> None:
    overlay = EnvironmentVars()
    overlay["A"] = "1"
    assert overlay["A"] == "1"
    assert dict(overlay) == {"A": "1"}
    del overlay["A"]
    with pytest.raises(KeyError):
        overlay["A"]


def test_environment_vars_unset_and_restore() -> None:
    overlay = EnvironmentVars()
    overlay["A"] = "override"
    overlay.unset("A")
    assert "A" in overlay.hidden
    assert overlay.merged({"A": "base", "B": "stay"}) == {"B": "stay"}
    overlay.restore("A")
    assert "A" not in overlay.hidden
    assert overlay.merged({"A": "base"}) == {"A": "base"}


def test_environment_vars_merged_layers_correctly() -> None:
    overlay = EnvironmentVars()
    overlay["X"] = "ovl"
    overlay.unset("Y")
    merged = overlay.merged({"X": "base", "Y": "base", "Z": "base"})
    assert merged == {"X": "ovl", "Z": "base"}


def test_environment_vars_pickles() -> None:
    overlay = EnvironmentVars()
    overlay["A"] = "1"
    overlay.unset("B")
    restored: EnvironmentVars = pickle.loads(pickle.dumps(overlay))
    assert restored["A"] == "1"
    assert restored.hidden == frozenset({"B"})


def test_diff_added_modified_deleted(env_root: Path) -> None:
    (env_root / "kept.txt").write_text("same")
    (env_root / "modified.txt").write_text("before")
    (env_root / "removed.txt").write_text("bye")
    baseline = Checkpoint.from_root(env_root)
    (env_root / "modified.txt").write_text("after-after")
    (env_root / "removed.txt").unlink()
    (env_root / "added.txt").write_text("hi")
    current = Checkpoint.from_root(env_root)
    diff = Diff.from_checkpoints(baseline, current)
    assert diff.added == (PurePosixPath("added.txt"),)
    assert diff.modified == (PurePosixPath("modified.txt"),)
    assert diff.deleted == (PurePosixPath("removed.txt"),)


def test_diff_detects_symlink_target_change(env_root: Path) -> None:
    target_a = env_root / "a.txt"
    target_b = env_root / "b.txt"
    target_a.write_text("a")
    target_b.write_text("b")
    (env_root / "link").symlink_to("a.txt")
    baseline = Checkpoint.from_root(env_root)
    (env_root / "link").unlink()
    (env_root / "link").symlink_to("b.txt")
    current = Checkpoint.from_root(env_root)
    diff = Diff.from_checkpoints(baseline, current)
    assert diff.modified == (PurePosixPath("link"),)


def test_diff_uses_hash_when_mtime_differs_across_trees(
    tmp_path: Path,
) -> None:
    """Hash fallback breaks size/mtime ties between two distinct roots."""
    parent_root = tmp_path / "parent"
    parent_root.mkdir()
    worker_root = tmp_path / "worker"
    worker_root.mkdir()
    (parent_root / "x.txt").write_text("aaaa")
    (worker_root / "x.txt").write_text("aaaa")
    new_mtime = (
        Checkpoint.from_root(parent_root)
        .entries[PurePosixPath("x.txt")]
        .mtime_ns
        + 1_000_000
    )
    os.utime(worker_root / "x.txt", ns=(new_mtime, new_mtime))
    parent = Checkpoint.from_root(parent_root)
    worker = Checkpoint.from_root(worker_root)
    assert Diff.from_checkpoints(parent, worker).modified == ()


def test_diff_detects_real_change_across_trees(tmp_path: Path) -> None:
    parent_root = tmp_path / "parent"
    parent_root.mkdir()
    worker_root = tmp_path / "worker"
    worker_root.mkdir()
    (parent_root / "x.txt").write_text("aaaa")
    (worker_root / "x.txt").write_text("zzzz")
    parent_mtime = (
        Checkpoint.from_root(parent_root)
        .entries[PurePosixPath("x.txt")]
        .mtime_ns
    )
    os.utime(
        worker_root / "x.txt",
        ns=(parent_mtime + 1_000_000, parent_mtime + 1_000_000),
    )
    parent = Checkpoint.from_root(parent_root)
    worker = Checkpoint.from_root(worker_root)
    diff = Diff.from_checkpoints(parent, worker)
    assert diff.modified == (PurePosixPath("x.txt"),)


def test_environment_diff_falls_back_to_load_baseline(
    env: Environment, env_root: Path
) -> None:
    (env_root / "out.txt").write_text("hi")
    diff = env.diff
    assert PurePosixPath("out.txt") in diff.added


def test_environment_diff_uses_consumer_baseline(
    env: Environment, env_root: Path
) -> None:
    (env_root / "shared.txt").write_text("shared")

    spec = type("FakeSpec", (), {})()
    env._mark_consumer_baseline(spec)

    (env_root / "after.txt").write_text("after")
    diff = env.diff
    assert PurePosixPath("after.txt") in diff.added
    assert PurePosixPath("shared.txt") not in diff.added


def test_activation_binds_environ_and_cwd(
    env: Environment, env_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RUE_TEST_BASE", "base")
    env.vars["RUE_TEST_OVERRIDE"] = "ovl"
    env.vars.unset("RUE_TEST_BASE")
    saved_cwd = os.getcwd()
    with env:
        assert os.getcwd() == str(env_root)
        assert os.environ["RUE_TEST_OVERRIDE"] == "ovl"
        assert "RUE_TEST_BASE" not in os.environ
    assert os.getcwd() == saved_cwd
    assert os.environ["RUE_TEST_BASE"] == "base"
    assert "RUE_TEST_OVERRIDE" not in os.environ


def test_activation_rejects_reentry(env: Environment, env_root: Path) -> None:
    other = Environment._build(root=env_root.parent / "other", scope=Scope.TEST)
    (env_root.parent / "other").mkdir()
    with env:
        with pytest.raises(RuntimeError, match="already active"):
            other.__enter__()


@pytest.mark.asyncio
async def test_exec_runs_with_overlay(env: Environment, env_root: Path) -> None:
    env.vars["RUE_EXEC_VAR"] = "value-x"
    result = await env.exec(
        [
            sys.executable,
            "-c",
            "import os, sys; sys.stdout.write(os.environ['RUE_EXEC_VAR'])",
        ]
    )
    assert result.returncode == 0
    assert result.stdout == b"value-x"


@pytest.mark.asyncio
async def test_exec_runs_in_env_cwd(env: Environment, env_root: Path) -> None:
    (env_root / "marker.txt").write_text("ok")
    result = await env.exec(
        [
            sys.executable,
            "-c",
            "import os, sys; sys.stdout.write(','.join(sorted(os.listdir())))",
        ]
    )
    assert result.returncode == 0
    assert b"marker.txt" in result.stdout


@pytest.mark.asyncio
async def test_exec_inherit_os_false_strips_host_vars(
    env: Environment, env_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RUE_HOST_ONLY", "host-value")
    result = await env.exec(
        [
            sys.executable,
            "-c",
            "import os, sys; "
            "sys.stdout.write(str('RUE_HOST_ONLY' in os.environ))",
        ],
        inherit_os=False,
        env={"PATH": os.environ.get("PATH", "")},
    )
    assert result.stdout == b"False"


@pytest.mark.asyncio
async def test_exec_check_raises_on_nonzero(env: Environment) -> None:
    with pytest.raises(subprocess.CalledProcessError):
        await env.exec(
            [sys.executable, "-c", "import sys; sys.exit(3)"], check=True
        )


def test_clone_tree_apfs_or_fallback(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.txt").write_text("hi")
    (src / "sub").mkdir()
    (src / "sub" / "b.txt").write_text("bye")
    (src / "link").symlink_to("a.txt")
    dst = tmp_path / "dst"
    clone_tree(src, dst)
    assert (dst / "a.txt").read_text() == "hi"
    assert (dst / "sub" / "b.txt").read_text() == "bye"
    assert (dst / "link").is_symlink()


def test_empty_tree_recreates_fresh(tmp_path: Path) -> None:
    target = tmp_path / "x"
    target.mkdir()
    (target / "a.txt").write_text("hi")
    empty_tree(target)
    assert target.is_dir()
    assert list(target.iterdir()) == []


@pytest.mark.asyncio
async def test_materialize_dir_source_caches_and_dedupes(
    tmp_path: Path,
) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "file.txt").write_text("source-payload")
    cache_root = tmp_path / "cache"
    dst1 = tmp_path / "dst1"
    dst2 = tmp_path / "dst2"
    source = DirSource(path=src)
    await asyncio.gather(
        source.materialize(cache_root=cache_root, dst=dst1),
        source.materialize(cache_root=cache_root, dst=dst2),
    )
    assert (dst1 / "file.txt").read_text() == "source-payload"
    assert (dst2 / "file.txt").read_text() == "source-payload"
    cache_dirs = [child for child in cache_root.iterdir() if child.is_dir()]
    assert len(cache_dirs) == 1


@pytest.mark.asyncio
async def test_materialize_empty_source(tmp_path: Path) -> None:
    cache_root = tmp_path / "cache"
    dst = tmp_path / "dst"
    await EmptySource().materialize(cache_root=cache_root, dst=dst)
    assert dst.is_dir()
    assert list(dst.iterdir()) == []


def test_environment_storage_allocate_and_release(tmp_path: Path) -> None:
    storage = EnvironmentStorage(base_dir=tmp_path)
    suite_id = uuid4()
    test_id = uuid4()
    owner = ScopeOwner(
        scope=Scope.TEST,
        test_execution_id=test_id,
        suite_execution_id=suite_id,
    )
    root = storage.allocate(suite_id, owner)
    assert root.is_dir()
    assert root.exists()
    storage.release(root)
    assert not root.exists()
    EnvironmentStorage.release_suite(suite_id, base_dir=tmp_path)


def test_environment_storage_worker_path_differs_from_main(
    tmp_path: Path,
) -> None:
    storage = EnvironmentStorage(base_dir=tmp_path)
    suite_id = uuid4()
    owner = ScopeOwner(
        scope=Scope.MODULE,
        suite_execution_id=suite_id,
        module_path=Path("/fake/module.py"),
    )
    main_root = storage.allocate(
        suite_id, owner, process_kind=CurrentProcessKind.MAIN
    )
    worker_root = storage.allocate(
        suite_id, owner, process_kind=CurrentProcessKind.TEST_SUBPROCESS
    )
    assert main_root != worker_root
    assert main_root.parent == worker_root.parent
    EnvironmentStorage.release_suite(suite_id, base_dir=tmp_path)


def test_gc_stale_removes_unlocked_dirs(tmp_path: Path) -> None:
    storage = EnvironmentStorage(base_dir=tmp_path)
    storage.run_dir.mkdir(parents=True, exist_ok=True)
    stale = storage.run_dir / str(uuid4())
    stale.mkdir()
    (stale / "lock").write_text("")
    (stale / "scratch").mkdir()

    held_suite_id = uuid4()
    held_owner = ScopeOwner(scope=Scope.SUITE, suite_execution_id=held_suite_id)
    held_root = storage.allocate(held_suite_id, held_owner)
    assert held_root.is_dir()

    removed = storage.gc_stale()
    assert stale in removed
    assert not stale.exists()
    held_dir = storage.suite_dir(held_suite_id)
    assert held_dir.exists()
    EnvironmentStorage.release_suite(held_suite_id, base_dir=tmp_path)


def test_environment_sync_round_trip(tmp_path: Path) -> None:
    parent_root = tmp_path / "parent"
    parent_root.mkdir()
    (parent_root / "kept.txt").write_text("kept")
    parent = Environment._build(root=parent_root, scope=Scope.MODULE)
    parent.vars["X"] = "ovl"

    state = parent.get_sync_state()

    worker_root = tmp_path / "worker"
    worker_root.mkdir()
    worker = Environment._build(root=worker_root, scope=Scope.MODULE)
    worker.from_sync_state(state)

    assert (worker_root / "kept.txt").read_text() == "kept"
    assert worker.vars["X"] == "ovl"

    (worker_root / "added.txt").write_text("from-worker")
    (worker_root / "kept.txt").write_text("changed")

    update = worker.get_sync_state()
    assert update.deltas

    parent.merge_sync_states(state, update)
    assert (parent_root / "added.txt").read_text() == "from-worker"
    assert (parent_root / "kept.txt").read_text() == "changed"


def test_environment_sync_state_apply_transfer_is_noop() -> None:
    state = EnvironmentSyncState(
        parent_root=Path("/nonexistent"),
        baseline_manifest=(),
    )
    state.apply_transfer()


def test_env_namespace_constructors() -> None:
    assert isinstance(env_empty(), EmptySource)
    src = env_dir("/tmp/example")
    assert isinstance(src, DirSource)
    assert src.path == Path("/tmp/example")
    git_src = env_git("https://example.com/repo", ref="main", subpath="docs")
    assert isinstance(git_src, GitSource)
    assert git_src.url == "https://example.com/repo"
    assert git_src.ref == "main"
    assert git_src.subpath == Path("docs")
