"""Integration tests for the `environment` builtin DI resource."""

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


async def _run_module(module_path: Path):
    context = make_suite_context(otel=False, concurrency=4)
    with context:
        suite = await ExecutableSuite(
            items=materialize_tests(module_path),
            suite_execution_id=context.suite_execution_id,
            resolver=DependencyResolver(registry),
        ).execute()
    return suite


@pytest.mark.asyncio
async def test_test_scope_environment_is_isolated_per_test(
    tmp_path: Path,
):
    module_path = tmp_path / "test_env_isolation.py"
    module_path.write_text(
        dedent(
            """
            from pathlib import Path

            import rue

            @rue.test
            def test_creates_marker_a(environment: rue.Environment):
                assert list(environment.root.iterdir()) == []
                (environment.root / 'a.txt').write_text('a')
                assert (environment.root / 'a.txt').exists()

            @rue.test
            def test_creates_marker_b(environment: rue.Environment):
                assert list(environment.root.iterdir()) == []
                (environment.root / 'b.txt').write_text('b')
            """
        )
    )

    suite = await _run_module(module_path)

    assert suite.result.passed == 2, _failed(suite)
    assert suite.result.failed == 0


@pytest.mark.asyncio
async def test_environment_diff_after_path_write(tmp_path: Path):
    module_path = tmp_path / "test_env_diff.py"
    module_path.write_text(
        dedent(
            """
            from pathlib import PurePosixPath

            import rue

            @rue.test
            def test_diff_reports_added_files(environment: rue.Environment):
                environment.path('input.txt').write_text('input')
                before = environment.get_checkpoint()
                with environment:
                    (environment.root / 'output.txt').write_text('hi')
                assert before.compare(environment.get_checkpoint()).added == (
                    PurePosixPath('output.txt'),
                )
            """
        )
    )

    suite = await _run_module(module_path)
    assert suite.result.passed == 1, _failed(suite)


@pytest.mark.asyncio
async def test_module_scope_env_persists_across_tests(tmp_path: Path):
    """Module-scope env keeps state across tests in the same module.

    The wrapper resource returns both the shared environment and the
    user-owned checkpoint that later tests compare against explicitly.
    Per-test isolation belongs to the default TEST-scope env.
    """
    module_path = tmp_path / "test_module_env.py"
    module_path.write_text(
        dedent(
            """
            from pathlib import PurePosixPath

            import rue

            @rue.resource(scope='module')
            def shared_env(environment: rue.Environment):
                (environment.root / 'shared.txt').write_text('shared')
                return environment, environment.get_checkpoint()

            @rue.test
            def test_first(shared_env):
                environment, _checkpoint = shared_env
                (environment.root / 'first.txt').write_text('1')

            @rue.test
            def test_second(shared_env):
                environment, checkpoint = shared_env
                (environment.root / 'second.txt').write_text('2')
                added = checkpoint.compare(environment.get_checkpoint()).added
                assert set(added) == {
                    PurePosixPath('first.txt'),
                    PurePosixPath('second.txt'),
                }
            """
        )
    )

    suite = await _run_module(module_path)
    assert suite.result.passed == 2, _failed(suite)


@pytest.mark.asyncio
async def test_module_scope_env_is_shared_with_subprocess(
    tmp_path: Path,
):
    module_path = tmp_path / "test_module_env_subprocess.py"
    module_path.write_text(
        dedent(
            """
            import rue
            from rue import ExecutionBackend

            @rue.resource(scope='module')
            def shared_env(environment: rue.Environment):
                environment.vars['PARENT_ONLY'] = 'parent'
                (environment.root / 'setup.txt').write_text('setup')
                return environment, environment.get_checkpoint()

            @rue.test.backend(ExecutionBackend.MAIN)
            def test_001_prepare(shared_env):
                environment, _checkpoint = shared_env
                assert (environment.root / 'setup.txt').read_text() == 'setup'

            @rue.test.backend(ExecutionBackend.SUBPROCESS)
            def test_002_remote_writes(shared_env):
                environment, _checkpoint = shared_env
                environment.vars.restore('PARENT_ONLY')
                environment.vars['WORKER_ONLY'] = 'worker'
                (environment.root / 'remote.txt').write_text('remote')

            @rue.test.backend(ExecutionBackend.MAIN)
            def test_003_main_sees_remote_write(shared_env):
                environment, checkpoint = shared_env
                assert (environment.root / 'remote.txt').read_text() == 'remote'
                assert environment.vars['WORKER_ONLY'] == 'worker'
                assert 'PARENT_ONLY' not in environment.vars
                diff = checkpoint.compare(environment.get_checkpoint())
                assert {p.name for p in diff.added} == {'remote.txt'}
            """
        )
    )

    suite = await _run_module(module_path)
    assert suite.result.passed == 3, _failed(suite)


@pytest.mark.asyncio
async def test_subprocess_test_scope_environment_is_isolated_per_test(
    tmp_path: Path,
):
    module_path = tmp_path / "test_subprocess_test_env_isolation.py"
    module_path.write_text(
        dedent(
            """
            import rue
            from rue import ExecutionBackend

            @rue.test.backend(ExecutionBackend.SUBPROCESS)
            def test_remote_a(environment: rue.Environment):
                (environment.root / 'a.txt').write_text('a')

            @rue.test.backend(ExecutionBackend.SUBPROCESS)
            def test_remote_b(environment: rue.Environment):
                assert list(environment.root.iterdir()) == []
            """
        )
    )

    suite = await _run_module(module_path)
    assert suite.result.passed == 2, _failed(suite)


@pytest.mark.asyncio
async def test_activation_binds_environ_inside_block(tmp_path: Path):
    module_path = tmp_path / "test_env_activation.py"
    module_path.write_text(
        dedent(
            """
            import os
            from pathlib import Path

            import rue

            @rue.test
            def test_activation_writes_via_relative_path(
                environment: rue.Environment,
            ):
                environment.vars['RUE_INTEGRATION_KEY'] = 'overlay'
                with environment:
                    Path('agent_output.txt').write_text('written')
                    assert (
                        os.environ['RUE_INTEGRATION_KEY']
                        == 'overlay'
                    )
                target = environment.root / 'agent_output.txt'
                assert target.read_text() == 'written'
                assert 'RUE_INTEGRATION_KEY' not in os.environ
            """
        )
    )

    suite = await _run_module(module_path)
    assert suite.result.passed == 1, _failed(suite)


@pytest.mark.asyncio
async def test_environment_exec_runs_with_overlay(tmp_path: Path):
    module_path = tmp_path / "test_env_exec.py"
    module_path.write_text(
        dedent(
            """
            import sys

            import rue

            @rue.test
            async def test_exec_uses_overlay(environment: rue.Environment):
                environment.vars['RUE_EXEC_FLAG'] = 'flag-x'
                result = await environment.exec(
                    [
                        sys.executable,
                        '-c',
                        'import os, sys; '
                        "sys.stdout.write(os.environ['RUE_EXEC_FLAG'])",
                    ],
                )
                assert result.returncode == 0
                assert result.stdout == b'flag-x'
            """
        )
    )

    suite = await _run_module(module_path)
    assert suite.result.passed == 1, _failed(suite)


@pytest.mark.asyncio
async def test_load_dir_source_into_module_env(tmp_path: Path):
    fixture_dir = tmp_path / "fixture"
    fixture_dir.mkdir()
    (fixture_dir / "config.json").write_text('{"key": "value"}')
    (fixture_dir / "data").mkdir()
    (fixture_dir / "data" / "row.txt").write_text("row-1")

    module_path = tmp_path / "test_env_load.py"
    module_path.write_text(
        dedent(
            f"""
            from pathlib import Path

            import rue

            FIXTURE = Path({str(fixture_dir)!r})

            @rue.resource(scope='module')
            async def loaded(environment: rue.Environment) -> rue.Environment:
                await environment.load(rue.env.dir(FIXTURE))
                return environment

            @rue.test
            def test_loaded_files_present(loaded: rue.Environment):
                assert (loaded.root / 'config.json').exists()
                assert (loaded.root / 'data' / 'row.txt').read_text() == 'row-1'
            """
        )
    )

    suite = await _run_module(module_path)
    assert suite.result.passed == 1, _failed(suite)
