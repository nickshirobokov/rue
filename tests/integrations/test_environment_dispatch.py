"""Integration tests for the context-routed Environment dispatcher."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from rue.resources import DependencyResolver, registry
from rue.testing.execution.suite.executable import ExecutableSuite
from rue.testing.execution.test.models import TestStatus
from tests.helpers import make_suite_context, materialize_tests


@pytest.fixture(autouse=True)
def clean_registry():
    registry.reset()
    yield
    registry.reset()


def _failed(suite):
    rows = []
    pending = list(suite.result.test_executions)
    while pending:
        execution = pending.pop()
        if execution.result.status is not TestStatus.PASSED:
            rows.append(
                (
                    execution.definition.spec.name,
                    execution.result.status.value,
                    str(execution.result.error)
                    if execution.result.error
                    else None,
                )
            )
        pending.extend(execution.sub_test_executions)
    return rows


async def _run_module(module_path: Path, *, concurrency: int = 6):
    context = make_suite_context(otel=False, concurrency=concurrency)
    with context:
        suite = await ExecutableSuite(
            items=materialize_tests(module_path),
            suite_execution_id=context.suite_execution_id,
            resolver=DependencyResolver(registry),
        ).execute()
    return suite


@pytest.mark.asyncio
async def test_concurrent_envs_isolate_same_key_writes(tmp_path: Path):
    """Same-key writes from concurrent iterations stay isolated per env.

    Each iteration writes the SAME env var name and the SAME relative file
    path with a distinct value. The staggered sleeps force overlap so any
    leak between contexts surfaces as a wrong read-back.
    """
    module_path = tmp_path / "test_concurrent_dispatch.py"
    module_path.write_text(
        dedent(
            """
            import asyncio
            import os
            from pathlib import Path

            import rue


            @rue.test.iterate.params(
                "case,pause",
                [("left", 0.12), ("right", 0.04), ("center", 0.08)],
            )
            async def test_same_key_isolation(
                case, pause, environment: rue.Environment,
            ):
                key = "RUE_DISPATCH_SHARED_KEY"
                value = f"value-{case}"
                with environment:
                    os.environ[key] = value
                    Path("payload.txt").write_text(value)
                    await asyncio.sleep(pause)
                    assert os.environ[key] == value
                    assert os.getcwd() == str(environment.root)
                    assert Path("payload.txt").read_text() == value
                    assert (environment.root / "payload.txt").read_text() == (
                        value
                    )
            """
        )
    )

    suite = await _run_module(module_path)
    assert suite.result.passed == 1, _failed(suite)


@pytest.mark.asyncio
async def test_no_env_fastpath_matches_real_state(tmp_path: Path):
    """Outside any `with environment:` block, dispatchers pass through."""
    module_path = tmp_path / "test_no_env_fastpath.py"
    module_path.write_text(
        dedent(
            """
            import os

            import rue


            @rue.test
            def test_no_env(environment: rue.Environment):
                real_cwd = os.getcwd()
                # outside the with-block, no env is active in this context
                # even though `environment` is resolved
                assert os.getcwd() == real_cwd
                # routed environ reads still expose real keys when no env active
                os.environ.get("PATH", None)  # must not raise
            """
        )
    )

    suite = await _run_module(module_path)
    assert suite.result.passed == 1, _failed(suite)


@pytest.mark.asyncio
async def test_chdir_subdir_resolves_against_env_cwd(tmp_path: Path):
    """`os.chdir('sub')` inside env resolves against current env.cwd."""
    module_path = tmp_path / "test_chdir_resolution.py"
    module_path.write_text(
        dedent(
            """
            import os
            from pathlib import Path

            import rue


            @rue.test
            def test_nested_chdir(environment: rue.Environment):
                (environment.root / "a" / "b").mkdir(parents=True)
                with environment:
                    os.chdir("a")
                    assert os.getcwd() == str(environment.root / "a")
                    os.chdir("b")
                    assert os.getcwd() == str(environment.root / "a" / "b")
                    Path("leaf.txt").write_text("leaf")
                    assert (
                        environment.root / "a" / "b" / "leaf.txt"
                    ).read_text() == "leaf"
                    os.chdir("..")
                    assert os.getcwd() == str(environment.root / "a")
            """
        )
    )

    suite = await _run_module(module_path)
    assert suite.result.passed == 1, _failed(suite)


@pytest.mark.asyncio
async def test_chdir_does_not_mutate_real_process_cwd(tmp_path: Path):
    """Exiting `with environment:` leaves the real process cwd untouched."""
    module_path = tmp_path / "test_real_cwd_intact.py"
    module_path.write_text(
        dedent(
            """
            import os

            import rue


            @rue.test
            def test_real_cwd(environment: rue.Environment):
                # Capture the parent cwd outside the with-block. The dispatcher
                # only mutates env._cwd, not process cwd, so this stays valid.
                outer = os.getcwd()
                with environment:
                    os.chdir(environment.root)
                    assert os.getcwd() == str(environment.root)
                # After exit, the routed os.getcwd falls back to the real cwd,
                # which was never changed.
                assert os.getcwd() == outer
            """
        )
    )

    suite = await _run_module(module_path)
    assert suite.result.passed == 1, _failed(suite)


@pytest.mark.asyncio
async def test_environ_overlay_writes_do_not_leak_to_real_environ(
    tmp_path: Path,
):
    """`os.environ['X']='Y'` inside an env stays in the overlay only."""
    module_path = tmp_path / "test_environ_isolation.py"
    module_path.write_text(
        dedent(
            """
            import os

            import rue
            from rue.environment.dispatch.environ import real_environ


            @rue.test
            def test_overlay_only(environment: rue.Environment):
                key = "RUE_DISPATCH_LEAK_CHECK"
                assert key not in real_environ()
                with environment:
                    os.environ[key] = "overlay"
                    assert os.environ[key] == "overlay"
                    # Real environ untouched even while active
                    assert key not in real_environ()
                # Exit removes routing; routed reads now see the real environ
                assert key not in os.environ
            """
        )
    )

    suite = await _run_module(module_path)
    assert suite.result.passed == 1, _failed(suite)


@pytest.mark.asyncio
async def test_environ_overlay_reads_fall_back_to_real_environ(
    tmp_path: Path,
):
    """Reads inside an env fall back to real environ unless hidden."""
    module_path = tmp_path / "test_environ_fallback.py"
    module_path.write_text(
        dedent(
            """
            import os

            import rue


            @rue.test
            def test_fallback(environment: rue.Environment):
                # PATH should be present in the real process environ on every
                # supported platform.
                assert "PATH" in os.environ
                with environment:
                    assert "PATH" in os.environ
                    assert os.environ["PATH"] == os.environ.get("PATH")
                    environment.vars.unset("PATH")
                    assert "PATH" not in os.environ
                    environment.vars.restore("PATH")
                    assert "PATH" in os.environ
            """
        )
    )

    suite = await _run_module(module_path)
    assert suite.result.passed == 1, _failed(suite)


@pytest.mark.asyncio
async def test_symlink_target_literal_not_rebased(tmp_path: Path):
    """`os.symlink('/etc/passwd', 'link')` keeps target literal."""
    module_path = tmp_path / "test_symlink_literal.py"
    module_path.write_text(
        dedent(
            """
            import os

            import rue


            @rue.test
            def test_symlink_literal(environment: rue.Environment):
                with environment:
                    os.symlink("/etc/passwd", "link")
                    assert os.readlink("link") == "/etc/passwd"
                # Link itself lives under env.root
                assert (environment.root / "link").is_symlink()
            """
        )
    )

    suite = await _run_module(module_path)
    assert suite.result.passed == 1, _failed(suite)


@pytest.mark.asyncio
async def test_rename_rebases_both_paths(tmp_path: Path):
    """`os.rename('a', 'b')` resolves both args under env.cwd."""
    module_path = tmp_path / "test_rename_dispatch.py"
    module_path.write_text(
        dedent(
            """
            import os
            from pathlib import Path

            import rue


            @rue.test
            def test_rename(environment: rue.Environment):
                with environment:
                    Path("a.txt").write_text("a")
                    os.rename("a.txt", "b.txt")
                    assert not Path("a.txt").exists()
                    assert Path("b.txt").read_text() == "a"
                assert (environment.root / "b.txt").read_text() == "a"
                assert not (environment.root / "a.txt").exists()
            """
        )
    )

    suite = await _run_module(module_path)
    assert suite.result.passed == 1, _failed(suite)


@pytest.mark.asyncio
async def test_dir_fd_overrides_env_cwd_rebase(tmp_path: Path):
    """When `dir_fd` is passed, the dispatcher must not rebase the path.

    Setup: `env.root/sub/leaf.txt` exists; `env.root/leaf.txt` does NOT.
    Default env.cwd is env.root. Opening fd on `env.root/sub`, then calling
    `os.stat('leaf.txt', dir_fd=fd)` must resolve through the fd (succeeds)
    rather than rebasing under env.cwd (which would FileNotFoundError).
    """
    module_path = tmp_path / "test_dir_fd.py"
    module_path.write_text(
        dedent(
            """
            import os

            import pytest
            import rue


            @rue.test
            def test_dir_fd(environment: rue.Environment):
                (environment.root / "sub").mkdir()
                (environment.root / "sub" / "leaf.txt").write_text("via-fd")
                fd = os.open(environment.root / "sub", os.O_RDONLY)
                try:
                    with environment:
                        # Without dir_fd, "leaf.txt" rebases to env.root and
                        # raises because it's not there.
                        with pytest.raises(FileNotFoundError):
                            os.stat("leaf.txt")
                        # With dir_fd, the dispatcher must skip rebase and
                        # the kernel resolves "leaf.txt" relative to fd.
                        st = os.stat("leaf.txt", dir_fd=fd)
                        assert st.st_size == len(b"via-fd")
                finally:
                    os.close(fd)
            """
        )
    )

    suite = await _run_module(module_path)
    assert suite.result.passed == 1, _failed(suite)


@pytest.mark.asyncio
async def test_nested_with_environment_in_same_context(tmp_path: Path):
    """Nested `with env_a: with env_b:` routes to the innermost env."""
    module_path = tmp_path / "test_nested.py"
    module_path.write_text(
        dedent(
            """
            import os
            import shutil
            import tempfile
            from pathlib import Path

            import rue


            @rue.test
            def test_nested(environment: rue.Environment):
                outer_dir = tempfile.mkdtemp(prefix="rue-outer-")
                inner_dir = tempfile.mkdtemp(prefix="rue-inner-")
                try:
                    outer_env = rue.Environment(
                        root=Path(outer_dir), scope=environment.scope,
                    )
                    inner_env = rue.Environment(
                        root=Path(inner_dir), scope=environment.scope,
                    )
                    with outer_env:
                        assert os.getcwd() == str(outer_env.root)
                        with inner_env:
                            assert os.getcwd() == str(inner_env.root)
                        # Innermost popped; routing returns to outer
                        assert os.getcwd() == str(outer_env.root)
                    # Outermost popped; routing returns to no-env fast path
                finally:
                    shutil.rmtree(outer_dir, ignore_errors=True)
                    shutil.rmtree(inner_dir, ignore_errors=True)
            """
        )
    )

    suite = await _run_module(module_path)
    assert suite.result.passed == 1, _failed(suite)


@pytest.mark.asyncio
async def test_putenv_routes_to_overlay_and_does_not_leak_to_children(
    tmp_path: Path,
):
    """`os.putenv` inside an active env must not mutate the C-level environ.

    A child subprocess inheriting from the parent C environ MUST NOT see
    the key after exit. Before this routing was added, putenv leaked
    directly into all child processes.
    """
    module_path = tmp_path / "test_putenv_routing.py"
    module_path.write_text(
        dedent(
            """
            import os
            import subprocess

            import rue
            from rue.environment.dispatch.environ import real_environ


            @rue.test
            def test_putenv(environment: rue.Environment):
                key = "RUE_DISPATCH_PUTENV_CHECK"
                assert key not in real_environ()
                with environment:
                    os.putenv(key, "via-putenv")
                    # Routed read sees the overlay value
                    assert os.environ[key] == "via-putenv"
                    # Real environ still untouched
                    assert key not in real_environ()
                    os.unsetenv(key)
                    assert key not in os.environ
                # After exit, neither routed nor real environ has it
                assert key not in os.environ
                assert key not in real_environ()
                # And a child subprocess with inherited env doesn't either
                result = subprocess.run(
                    ["/usr/bin/env"],
                    capture_output=True,
                    check=True,
                    text=True,
                )
                assert key not in result.stdout


            @rue.test
            def test_unsetenv_hides_real_key(environment: rue.Environment):
                key = "RUE_DISPATCH_UNSETENV_BASE"
                real_environ()[key] = "base"
                try:
                    with environment:
                        assert os.environ[key] == "base"
                        os.unsetenv(key)
                        assert key not in os.environ
                    # Outside the env, real environ still has the base value
                    assert os.environ[key] == "base"
                finally:
                    real_environ().pop(key, None)
            """
        )
    )

    suite = await _run_module(module_path)
    assert suite.result.passed == 2, _failed(suite)


@pytest.mark.asyncio
async def test_fchdir_does_not_mutate_real_cwd(tmp_path: Path):
    """`os.fchdir(fd)` under active env updates env.cwd, not real cwd."""
    module_path = tmp_path / "test_fchdir.py"
    module_path.write_text(
        dedent(
            """
            import os
            from pathlib import Path

            import rue


            @rue.test
            def test_fchdir(environment: rue.Environment):
                (environment.root / "sub").mkdir()
                # Outside the env there's no routing, so os.getcwd returns
                # the real process cwd.
                real_cwd_before = os.getcwd()
                fd = os.open(environment.root / "sub", os.O_RDONLY)
                try:
                    with environment:
                        os.fchdir(fd)
                        assert os.getcwd() == str(environment.root / "sub")
                    # After exit, env binding is gone; the routed os.getcwd
                    # falls back to real getcwd, which was never mutated.
                    assert os.getcwd() == real_cwd_before
                finally:
                    os.close(fd)
            """
        )
    )

    suite = await _run_module(module_path)
    assert suite.result.passed == 1, _failed(suite)


@pytest.mark.asyncio
async def test_chdir_rejects_escape_outside_env_root(tmp_path: Path):
    """`os.chdir('/etc')` inside env raises ValueError on escape."""
    module_path = tmp_path / "test_chdir_escape.py"
    module_path.write_text(
        dedent(
            """
            import os

            import pytest
            import rue


            @rue.test
            def test_escape_rejected(environment: rue.Environment):
                with environment:
                    with pytest.raises(ValueError, match="escapes"):
                        os.chdir("/")
                    # env.cwd unchanged after a rejected attempt
                    assert os.getcwd() == str(environment.root)
                    # Relative `..` from env.root would also escape
                    with pytest.raises(ValueError, match="escapes"):
                        os.chdir("..")
            """
        )
    )

    suite = await _run_module(module_path)
    assert suite.result.passed == 1, _failed(suite)


@pytest.mark.asyncio
async def test_router_rejects_non_str_keys_and_values(tmp_path: Path):
    """`os.environ[1] = 'x'` and similar must raise TypeError, like real environ."""
    module_path = tmp_path / "test_router_types.py"
    module_path.write_text(
        dedent(
            """
            import os

            import pytest
            import rue


            @rue.test
            def test_types(environment: rue.Environment):
                with environment:
                    with pytest.raises(TypeError):
                        os.environ[1] = "x"
                    with pytest.raises(TypeError):
                        os.environ["X"] = 1
                    with pytest.raises(TypeError):
                        del os.environ[2]
            """
        )
    )

    suite = await _run_module(module_path)
    assert suite.result.passed == 1, _failed(suite)


@pytest.mark.asyncio
async def test_environment_exec_uses_real_environ_as_base(tmp_path: Path):
    """`Environment.exec` composes overrides onto the real (not routed) environ.

    Inside `with environment:` the routed `os.environ` already contains the
    overlay; if `exec` re-applied the overlay on top of the routed view, the
    real base values would be lost. This test sets a key in the real environ
    before activation and asserts `exec` still inherits it.
    """
    module_path = tmp_path / "test_exec_real_base.py"
    module_path.write_text(
        dedent(
            """
            import os
            import sys

            import rue
            from rue.environment.dispatch.environ import real_environ


            @rue.test
            async def test_exec_real_base(environment: rue.Environment):
                real_environ()["RUE_BASE_KEY"] = "base"
                try:
                    environment.vars["RUE_OVERLAY_KEY"] = "overlay"
                    with environment:
                        result = await environment.exec(
                            [
                                sys.executable, "-c",
                                "import os; "
                                "print(os.environ.get('RUE_BASE_KEY'), "
                                "os.environ.get('RUE_OVERLAY_KEY'))",
                            ],
                        )
                    assert result.returncode == 0
                    assert result.stdout.strip() == b"base overlay"
                finally:
                    real_environ().pop("RUE_BASE_KEY", None)
            """
        )
    )

    suite = await _run_module(module_path)
    assert suite.result.passed == 1, _failed(suite)
