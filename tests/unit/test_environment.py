"""Unit tests for the `Environment` resource and its supporting modules."""

from __future__ import annotations

import asyncio
import difflib
import json
import os
import pickle
import subprocess
import sys
from pathlib import Path, PurePosixPath
from uuid import uuid4

import pytest

import bsdiff4
from rue.context.models import ScopeOwner
from rue.context.scopes import CurrentProcessKind, Scope
from rue.environment import (
    DirSource,
    EmptySource,
    Environment,
    EnvironmentSyncState,
    EnvironmentVars,
    FileDiff,
    GitSource,
    UpdatedPath,
)
from rue.environment.checkpoint import Checkpoint
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
    return Environment(root=env_root, scope=Scope.TEST)


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
    before = Checkpoint.from_root(env_root)
    (env_root / "modified.txt").write_text("after-after")
    (env_root / "removed.txt").unlink()
    (env_root / "added.txt").write_text("hi")
    diff = before.compare(Checkpoint.from_root(env_root))

    assert diff.added == (PurePosixPath("added.txt"),)
    assert diff.modified == (PurePosixPath("modified.txt"),)
    assert diff.deleted == (PurePosixPath("removed.txt"),)


def test_diff_detects_symlink_target_change(env_root: Path) -> None:
    target_a = env_root / "a.txt"
    target_b = env_root / "b.txt"
    target_a.write_text("a")
    target_b.write_text("b")
    (env_root / "link").symlink_to("a.txt")
    before = Checkpoint.from_root(env_root)
    (env_root / "link").unlink()
    (env_root / "link").symlink_to("b.txt")

    assert before.compare(Checkpoint.from_root(env_root)).modified == (
        PurePosixPath("link"),
    )


def test_checkpoint_is_value_snapshot(
    env_root: Path,
) -> None:
    target = env_root / "x.txt"
    target.write_text("aaaa")
    before = Checkpoint.from_root(env_root)
    target.write_text("zzzz")
    after = Checkpoint.from_root(env_root)

    assert before.compare(after).modified == (PurePosixPath("x.txt"),)


def test_checkpoint_from_root_emits_only_changed_paths(
    tmp_path: Path,
) -> None:
    baseline = tmp_path / "baseline"
    current = tmp_path / "current"
    baseline.mkdir()
    current.mkdir()
    (baseline / "same.txt").write_text("same")
    (current / "same.txt").write_text("same")
    (baseline / "changed.txt").write_text("before")
    (current / "changed.txt").write_text("after")

    checkpoint = Checkpoint.from_root(current, baseline)

    assert tuple(path.path for path in checkpoint.updated_paths) == (
        PurePosixPath("changed.txt"),
    )


def test_checkpoint_mode_only_change_has_no_bsdiff_patch(
    tmp_path: Path,
) -> None:
    baseline = tmp_path / "baseline"
    current = tmp_path / "current"
    baseline.mkdir()
    current.mkdir()
    baseline_file = baseline / "script.sh"
    current_file = current / "script.sh"
    baseline_file.write_text("echo hi\n")
    current_file.write_text("echo hi\n")
    os.chmod(baseline_file, 0o644)
    os.chmod(current_file, 0o755)

    checkpoint = Checkpoint.from_root(current, baseline)

    assert checkpoint.updated_paths == (
        UpdatedPath.file(
            path=PurePosixPath("script.sh"),
            mode=0o755,
            bsdiff_patch=None,
        ),
    )


def test_checkpoint_byte_change_payload_round_trips_with_bsdiff(
    tmp_path: Path,
) -> None:
    baseline = tmp_path / "baseline"
    current = tmp_path / "current"
    baseline.mkdir()
    current.mkdir()
    baseline_bytes = b"before"
    current_bytes = b"after-after"
    (baseline / "file.txt").write_bytes(baseline_bytes)
    (current / "file.txt").write_bytes(current_bytes)

    checkpoint = Checkpoint.from_root(current, baseline)
    updated_path = checkpoint.updated_paths[0]

    assert isinstance(updated_path.bsdiff_patch, bytes)
    assert (
        bsdiff4.patch(baseline_bytes, updated_path.bsdiff_patch)
        == current_bytes
    )


def test_checkpoint_added_empty_file_reconstructs_from_empty_baseline(
    tmp_path: Path,
) -> None:
    empty = tmp_path / "empty"
    current = tmp_path / "current"
    empty.mkdir()
    current.mkdir()
    (current / "empty.txt").touch()

    assert Checkpoint.from_root(empty).compare(
        Checkpoint.from_root(current)
    ).added == (PurePosixPath("empty.txt"),)


def test_checkpoint_compare_uses_reconstructed_final_state(
    tmp_path: Path,
) -> None:
    baseline_a = tmp_path / "baseline-a"
    current_a = tmp_path / "current-a"
    baseline_b = tmp_path / "baseline-b"
    current_b = tmp_path / "current-b"
    for directory in (baseline_a, current_a, baseline_b, current_b):
        directory.mkdir()
    (baseline_a / "same.txt").write_text("same")
    (current_a / "same.txt").write_text("same")
    (current_b / "same.txt").write_text("same")

    checkpoint_a = Checkpoint.from_root(current_a, baseline_a)
    checkpoint_b = Checkpoint.from_root(current_b, baseline_b)

    assert checkpoint_a.updated_paths == ()
    assert checkpoint_b.updated_paths
    assert checkpoint_a.compare(checkpoint_b).empty


def test_diff_content_returns_after_state_for_added(env_root: Path) -> None:
    before = Checkpoint.from_root(env_root)
    (env_root / "added.txt").write_bytes(b"new content")

    diff = before.compare(Checkpoint.from_root(env_root))

    assert diff.content("added.txt") == b"new content"


def test_diff_content_returns_after_state_for_modified(env_root: Path) -> None:
    (env_root / "f.txt").write_bytes(b"before")
    before = Checkpoint.from_root(env_root)
    (env_root / "f.txt").write_bytes(b"after-after")

    diff = before.compare(Checkpoint.from_root(env_root))

    assert diff.content("f.txt") == b"after-after"


def test_diff_content_returns_before_state_for_deleted(env_root: Path) -> None:
    (env_root / "gone.txt").write_bytes(b"will be gone")
    before = Checkpoint.from_root(env_root)
    (env_root / "gone.txt").unlink()

    diff = before.compare(Checkpoint.from_root(env_root))

    assert diff.content("gone.txt") == b"will be gone"


def test_diff_content_raises_keyerror_for_unchanged_path(
    env_root: Path,
) -> None:
    (env_root / "kept.txt").write_bytes(b"same")
    before = Checkpoint.from_root(env_root)
    (env_root / "added.txt").write_bytes(b"new")

    diff = before.compare(Checkpoint.from_root(env_root))

    with pytest.raises(KeyError):
        diff.content("kept.txt")


def test_diff_diff_raises_keyerror_for_unchanged_path(env_root: Path) -> None:
    (env_root / "kept.txt").write_bytes(b"same")
    before = Checkpoint.from_root(env_root)
    (env_root / "added.txt").write_bytes(b"new")

    diff = before.compare(Checkpoint.from_root(env_root))

    with pytest.raises(KeyError):
        diff.diff("kept.txt")


def test_filediff_unified_matches_difflib_output(env_root: Path) -> None:
    (env_root / "doc.txt").write_text("line one\nline two\n")
    before = Checkpoint.from_root(env_root)
    (env_root / "doc.txt").write_text("line one\nline TWO\n")

    diff = before.compare(Checkpoint.from_root(env_root))
    expected = "".join(
        difflib.unified_diff(
            "line one\nline two\n".splitlines(keepends=True),
            "line one\nline TWO\n".splitlines(keepends=True),
            fromfile="doc.txt",
            tofile="doc.txt",
        )
    )

    assert diff.diff("doc.txt").unified == expected


def test_filediff_words_returns_dmp_tuples(env_root: Path) -> None:
    (env_root / "msg.txt").write_text("hello world")
    before = Checkpoint.from_root(env_root)
    (env_root / "msg.txt").write_text("hello earth")

    diff = before.compare(Checkpoint.from_root(env_root))
    words = diff.diff("msg.txt").words

    assert isinstance(words, tuple)
    assert ("-", "world") in words
    assert ("+", "earth") in words
    assert ("=", "hello ") in words
    assert "".join(text for op, text in words if op != "+") == "hello world"
    assert "".join(text for op, text in words if op != "-") == "hello earth"


def test_filediff_json_returns_rfc6902_patch(env_root: Path) -> None:
    (env_root / "data.json").write_text(json.dumps({"a": 1, "b": 2}))
    before = Checkpoint.from_root(env_root)
    (env_root / "data.json").write_text(json.dumps({"a": 1, "b": 3}))

    diff = before.compare(Checkpoint.from_root(env_root))

    assert diff.diff("data.json").json == [
        {"op": "replace", "path": "/b", "value": 3}
    ]


def test_filediff_json_on_added_file_uses_null_before(env_root: Path) -> None:
    before = Checkpoint.from_root(env_root)
    (env_root / "data.json").write_text(json.dumps({"hello": "world"}))

    diff = before.compare(Checkpoint.from_root(env_root))

    assert diff.diff("data.json").json == [
        {"op": "replace", "path": "", "value": {"hello": "world"}}
    ]


def test_filediff_json_raises_on_invalid_json(env_root: Path) -> None:
    (env_root / "f.txt").write_text("not json at all")
    before = Checkpoint.from_root(env_root)
    (env_root / "f.txt").write_text("still not json")

    file_diff = before.compare(Checkpoint.from_root(env_root)).diff("f.txt")

    with pytest.raises(json.JSONDecodeError):
        _ = file_diff.json


def test_filediff_unified_raises_on_binary(env_root: Path) -> None:
    (env_root / "bin").write_bytes(b"\xff\xfe\x00\x01")
    before = Checkpoint.from_root(env_root)
    (env_root / "bin").write_bytes(b"\xff\xfe\x00\x02")

    file_diff = before.compare(Checkpoint.from_root(env_root)).diff("bin")

    with pytest.raises(UnicodeDecodeError):
        _ = file_diff.unified


def test_diff_content_handles_symlink_target(env_root: Path) -> None:
    (env_root / "a.txt").write_text("a")
    (env_root / "b.txt").write_text("b")
    (env_root / "link").symlink_to("a.txt")
    before = Checkpoint.from_root(env_root)
    (env_root / "link").unlink()
    (env_root / "link").symlink_to("b.txt")

    diff = before.compare(Checkpoint.from_root(env_root))

    assert diff.content("link") == b"b.txt"
    file_diff = diff.diff("link")
    assert isinstance(file_diff, FileDiff)
    assert file_diff.before == b"a.txt"
    assert file_diff.after == b"b.txt"


def test_environment_get_checkpoint_is_side_effect_free(
    env: Environment, env_root: Path
) -> None:
    (env_root / "before.txt").write_text("before")
    before = env.get_checkpoint()
    assert before.compare(env.get_checkpoint()).empty
    (env_root / "after.txt").write_text("after")

    assert before.compare(env.get_checkpoint()).added == (
        PurePosixPath("after.txt"),
    )


def test_environment_reset_leaves_fresh_checkpoint(env: Environment) -> None:
    env.path("before.txt").write_text("before")
    env.reset()

    assert env.get_checkpoint().updated_paths == ()


@pytest.mark.asyncio
async def test_environment_get_checkpoint_uses_loaded_cache_baseline(
    env: Environment,
    tmp_path: Path,
) -> None:
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "seed.txt").write_text("seed")
    await env.load(DirSource(path=source_dir))
    env.path("seed.txt").write_text("changed")

    checkpoint = env.get_checkpoint()

    assert checkpoint.baseline is not None
    assert (checkpoint.baseline / "seed.txt").read_text() == "seed"
    assert tuple(path.path for path in checkpoint.updated_paths) == (
        PurePosixPath("seed.txt"),
    )


@pytest.mark.asyncio
async def test_environment_reset_restores_loaded_cache_state(
    env: Environment,
    tmp_path: Path,
) -> None:
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "seed.txt").write_text("seed")
    await env.load(DirSource(path=source_dir))

    env.path("seed.txt").write_text("mutated")
    env.path("extra.txt").write_text("extra")
    env.reset()

    assert env.path("seed.txt").read_text() == "seed"
    assert not env.path("extra.txt").exists()


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
    other = Environment(root=env_root.parent / "other", scope=Scope.TEST)
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
    cache_paths = await asyncio.gather(
        source.materialize(cache_root=cache_root, dst=dst1),
        source.materialize(cache_root=cache_root, dst=dst2),
    )
    assert (dst1 / "file.txt").read_text() == "source-payload"
    assert (dst2 / "file.txt").read_text() == "source-payload"
    assert cache_paths[0] == cache_paths[1]
    cache_dirs = [child for child in cache_root.iterdir() if child.is_dir()]
    assert len(cache_dirs) == 1


@pytest.mark.asyncio
async def test_materialize_empty_source(tmp_path: Path) -> None:
    cache_root = tmp_path / "cache"
    dst = tmp_path / "dst"
    cache_path = await EmptySource().materialize(
        cache_root=cache_root,
        dst=dst,
    )
    assert dst.is_dir()
    assert list(dst.iterdir()) == []
    assert cache_path == cache_root / EmptySource().fingerprint()


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


def test_environment_storage_uses_shared_owner_roots_without_reallocating(
    tmp_path: Path,
) -> None:
    storage = EnvironmentStorage(base_dir=tmp_path)
    suite_id = uuid4()
    module_owner = ScopeOwner(
        scope=Scope.MODULE,
        suite_execution_id=suite_id,
        module_path=Path("/fake/module.py"),
    )
    main_root = storage.allocate(
        suite_id, module_owner, process_kind=CurrentProcessKind.MAIN
    )
    (main_root / "kept.txt").write_text("kept")
    worker_root = storage.allocate(
        suite_id, module_owner, process_kind=CurrentProcessKind.TEST_SUBPROCESS
    )

    assert main_root == worker_root
    assert (worker_root / "kept.txt").read_text() == "kept"

    assert storage.allocate(
        suite_id,
        ScopeOwner(
            scope=Scope.TEST,
            test_execution_id=uuid4(),
            suite_execution_id=suite_id,
        ),
    ) != storage.allocate(
        suite_id,
        ScopeOwner(
            scope=Scope.TEST,
            test_execution_id=uuid4(),
            suite_execution_id=suite_id,
        ),
    )
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


def test_environment_sync_shares_root_and_merges_object_state(
    tmp_path: Path,
) -> None:
    parent_root = tmp_path / "parent"
    parent_root.mkdir()
    (parent_root / "baseline.txt").write_text("baseline")
    parent = Environment(root=parent_root, scope=Scope.MODULE)
    parent.vars["X"] = "ovl"

    state = parent.get_sync_state()
    assert set(EnvironmentSyncState.__dataclass_fields__) == {
        "root",
        "overrides",
        "hidden",
        "cwd",
    }
    worker = Environment(
        root=tmp_path / "worker",
        scope=Scope.MODULE,
    )
    worker.from_sync_state(state)

    assert worker.root == parent_root.resolve()
    assert worker.vars["X"] == "ovl"

    worker.vars.restore("X")
    worker.vars["Y"] = "worker"
    (parent_root / "work").mkdir()
    worker.chdir("work")
    (parent_root / "work" / "added.txt").write_text("from-worker")

    update = worker.get_sync_state()
    assert not hasattr(update, "deltas")

    parent.merge_sync_states(state, update)
    assert (parent_root / "work" / "added.txt").read_text() == "from-worker"
    with pytest.raises(KeyError):
        _ = parent.vars["X"]
    assert parent.vars["Y"] == "worker"
    assert parent.cwd == parent.root / "work"


def test_environment_sync_state_apply_transfer_is_noop() -> None:
    state = EnvironmentSyncState(
        root=Path("/nonexistent"),
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
