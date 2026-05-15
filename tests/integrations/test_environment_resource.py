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
                with environment:
                    (environment.root / 'output.txt').write_text('hi')
                assert PurePosixPath('output.txt') in environment.diff.added

            @rue.test
            async def test_async_diff(environment: rue.Environment):
                target = environment.path('nested/data.json')
                target.parent.mkdir(parents=True)
                target.write_text('{"ok": true}')
                added = environment.diff.added
                assert PurePosixPath('nested/data.json') in added
            """
        )
    )

    suite = await _run_module(module_path)
    assert suite.result.passed == 2, _failed(suite)


@pytest.mark.asyncio
async def test_module_scope_env_persists_across_tests(tmp_path: Path):
    """Module-scope env keeps state across tests in the same module.

    `env.diff` here reports changes since the wrapper resource's injection
    (which is the actual consumer of the underlying env builtin), not
    per-test. Per-test isolation belongs to the default TEST-scope env.
    """
    module_path = tmp_path / "test_module_env.py"
    module_path.write_text(
        dedent(
            """
            from pathlib import PurePosixPath

            import rue

            @rue.resource(scope='module')
            def shared_env(environment: rue.Environment) -> rue.Environment:
                (environment.root / 'shared.txt').write_text('shared')
                return environment

            @rue.test
            def test_first(shared_env: rue.Environment):
                assert (shared_env.root / 'shared.txt').exists()
                (shared_env.root / 'first.txt').write_text('1')

            @rue.test
            def test_second(shared_env: rue.Environment):
                assert (shared_env.root / 'shared.txt').exists()
                assert (shared_env.root / 'first.txt').exists()
                (shared_env.root / 'second.txt').write_text('2')
                added = shared_env.diff.added
                assert PurePosixPath('second.txt') in added
                assert PurePosixPath('first.txt') in added
            """
        )
    )

    suite = await _run_module(module_path)
    assert suite.result.passed == 2, _failed(suite)


@pytest.mark.asyncio
async def test_per_test_env_diff_resets_for_test_scope(tmp_path: Path):
    """Direct test-scope env injection gives per-test diffs trivially."""
    module_path = tmp_path / "test_per_test_env_diff.py"
    module_path.write_text(
        dedent(
            """
            from pathlib import PurePosixPath

            import rue

            @rue.test
            def test_alpha(environment: rue.Environment):
                (environment.root / 'alpha.txt').write_text('a')
                assert environment.diff.added == (PurePosixPath('alpha.txt'),)

            @rue.test
            def test_beta(environment: rue.Environment):
                (environment.root / 'beta.txt').write_text('b')
                assert environment.diff.added == (PurePosixPath('beta.txt'),)
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
