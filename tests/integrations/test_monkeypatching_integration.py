from pathlib import Path
from textwrap import dedent

import pytest

from rue.resources import DependencyResolver, registry
from rue.testing.models import TestStatus
from rue.testing.runner import Runner
from tests.unit.conftest import NullReporter
from tests.unit.factories import make_run_context, materialize_tests


@pytest.fixture(autouse=True)
def clean_registry():
    registry.reset()
    yield
    registry.reset()


def _failed_executions(run):
    rows = []
    pending = list(run.result.executions)
    while pending:
        execution = pending.pop()
        if execution.status is not TestStatus.PASSED:
            rows.append(
                (
                    str(execution.execution_id),
                    execution.status.value,
                    str(execution.result.error)
                    if execution.result.error
                    else None,
                )
            )
        pending.extend(execution.sub_executions)
    return rows


async def _run_module(module_path: Path):
    make_run_context(
            otel=False,
            db_enabled=False,
            concurrency=6,
        )
    return await Runner(
        reporters=[NullReporter()],
    ).run(
        items=materialize_tests(module_path),
        resolver=DependencyResolver(registry),
    )


@pytest.mark.asyncio
async def test_iterated_patches_to_same_object_are_execution_isolated(
    tmp_path: Path,
):
    module_path = tmp_path / "test_iterated_monkeypatch_isolation.py"
    module_path.write_text(
        dedent(
            """
            import asyncio
            import time

            import rue
            from rue import ExecutionBackend


            class Target:
                def value(self):
                    return "original"


            target = Target()


            def patch_target(monkeypatch, value):
                monkeypatch.setattr(
                    Target,
                    "value",
                    lambda self, value=value: value,
                )


            @rue.test.iterate.params(
                "case,pause",
                [("left", 0.12), ("right", 0.04), ("center", 0.08)],
            )
            def test_sync(case, pause, monkeypatch):
                expected = f"sync:{case}"
                assert target.value() == "original"
                patch_target(monkeypatch, expected)
                time.sleep(pause)
                assert target.value() == expected


            @rue.test.iterate.params(
                "case,pause",
                [("left", 0.03), ("right", 0.09), ("center", 0.06)],
            )
            @rue.test.backend(ExecutionBackend.MAIN)
            async def test_async_main(case, pause, monkeypatch):
                expected = f"main:{case}"
                assert target.value() == "original"
                patch_target(monkeypatch, expected)
                await asyncio.sleep(pause)
                assert target.value() == expected


            @rue.test.iterate.params(
                "case,pause",
                [("left", 0.10), ("right", 0.02), ("center", 0.06)],
            )
            @rue.test.backend(ExecutionBackend.SUBPROCESS)
            async def test_async_subprocess(case, pause, monkeypatch):
                expected = f"subprocess:{case}"
                assert target.value() == "original"
                patch_target(monkeypatch, expected)
                await asyncio.sleep(pause)
                assert target.value() == expected


            @rue.test.backend(ExecutionBackend.MAIN)
            def test_after():
                assert target.value() == "original"
            """
        )
    )

    run = await _run_module(module_path)

    assert run.result.passed == 4, _failed_executions(run)


@pytest.mark.asyncio
async def test_resource_monkeypatch_and_test_patches_are_execution_isolated(
    tmp_path: Path,
):
    module_path = tmp_path / "test_resource_monkeypatch_isolation.py"
    module_path.write_text(
        dedent(
            """
            import asyncio
            import time

            import rue
            from rue import ExecutionBackend


            class Target:
                def value(self):
                    return "original"


            target = Target()


            def patch_target(monkeypatch, value):
                monkeypatch.setattr(
                    Target,
                    "value",
                    lambda self, value=value: value,
                )


            @rue.resource
            def sync_patch(monkeypatch):
                patch_target(monkeypatch, "resource:sync")
                return "resource:sync"


            @rue.resource
            def main_patch(monkeypatch):
                patch_target(monkeypatch, "resource:main")
                return "resource:main"


            @rue.resource
            def subprocess_patch(monkeypatch):
                patch_target(monkeypatch, "resource:subprocess")
                return "resource:subprocess"


            @rue.test.iterate.params(
                "case,pause",
                [("left", 0.12), ("right", 0.04), ("center", 0.08)],
            )
            def test_sync(case, pause, sync_patch, monkeypatch):
                expected = f"test:sync:{case}"
                assert target.value() == sync_patch
                patch_target(monkeypatch, expected)
                time.sleep(pause)
                assert target.value() == expected


            @rue.test.iterate.params(
                "case,pause",
                [("left", 0.03), ("right", 0.09), ("center", 0.06)],
            )
            @rue.test.backend(ExecutionBackend.MAIN)
            async def test_async_main(case, pause, main_patch, monkeypatch):
                expected = f"test:main:{case}"
                assert target.value() == main_patch
                patch_target(monkeypatch, expected)
                await asyncio.sleep(pause)
                assert target.value() == expected


            @rue.test.iterate.params(
                "case,pause",
                [("left", 0.10), ("right", 0.02), ("center", 0.06)],
            )
            @rue.test.backend(ExecutionBackend.SUBPROCESS)
            async def test_async_subprocess(
                case,
                pause,
                subprocess_patch,
                monkeypatch,
            ):
                expected = f"test:subprocess:{case}"
                assert target.value() == subprocess_patch
                patch_target(monkeypatch, expected)
                await asyncio.sleep(pause)
                assert target.value() == expected


            @rue.test.backend(ExecutionBackend.MAIN)
            def test_after_without_resources():
                assert target.value() == "original"
            """
        )
    )

    run = await _run_module(module_path)

    assert run.result.passed == 4, _failed_executions(run)


@pytest.mark.asyncio
async def test_all_monkeypatch_operations_conflict_across_backends(
    tmp_path: Path,
):
    module_path = tmp_path / "test_all_monkeypatch_operations.py"
    module_path.write_text(
        dedent(
            """
            import asyncio
            import time

            import pytest
            import rue
            from rue import ExecutionBackend


            class Target:
                value = "original"
                deleted = "present"


            def path_call():
                return "original"


            mapping = {"value": "original", "deleted": "present"}
            items = ["original", "present"]


            @rue.test.iterate.params(
                "case,pause",
                [("left", 0.12), ("right", 0.04)],
            )
            @rue.test.backend(ExecutionBackend.MAIN)
            def test_001_main_blocking_conflicts(case, pause, monkeypatch):
                assert Target.value == "original"
                assert Target.deleted == "present"
                assert path_call() == "original"
                assert mapping["value"] == "original"
                assert mapping["deleted"] == "present"
                assert items[0] == "original"
                assert items[1] == "present"

                expected = f"main-one:{case}"
                monkeypatch.setattr(Target, "value", expected)
                monkeypatch.setattr(
                    __name__ + ":path_call",
                    lambda expected=expected: expected,
                )
                monkeypatch.delattr(Target, "deleted")
                monkeypatch.setitem(mapping, "value", expected)
                monkeypatch.delitem(mapping, "deleted")
                monkeypatch.setitem(items, expected, idx=0, replace=True)
                monkeypatch.delitem(items, idx=1, replace=True)

                inserted = ["tail"]
                monkeypatch.setitem(inserted, expected, idx=0, replace=False)
                assert inserted[0] == expected
                assert inserted[1] == "tail"

                time.sleep(pause)
                assert Target.value == expected
                assert path_call() == expected
                assert not hasattr(Target, "deleted")
                assert mapping["value"] == expected
                with pytest.raises(KeyError):
                    str(mapping["deleted"])
                assert items[0] == expected
                with pytest.raises(IndexError):
                    str(items[1])


            @rue.test.iterate.params(
                "case,pause",
                [("left", 0.03), ("right", 0.09)],
            )
            async def test_002_default_async_conflicts(
                case,
                pause,
                monkeypatch,
            ):
                assert Target.value == "original"
                assert Target.deleted == "present"
                assert path_call() == "original"
                assert mapping["value"] == "original"
                assert mapping["deleted"] == "present"
                assert items[0] == "original"
                assert items[1] == "present"

                expected = f"default-async-one:{case}"
                monkeypatch.setattr(Target, "value", expected)
                monkeypatch.setattr(
                    __name__ + ":path_call",
                    lambda expected=expected: expected,
                )
                monkeypatch.delattr(Target, "deleted")
                monkeypatch.setitem(mapping, "value", expected)
                monkeypatch.delitem(mapping, "deleted")
                monkeypatch.setitem(items, expected, idx=0, replace=True)
                monkeypatch.delitem(items, idx=1, replace=True)

                inserted = ["tail"]
                monkeypatch.setitem(inserted, expected, idx=0, replace=False)
                assert inserted[0] == expected
                assert inserted[1] == "tail"

                await asyncio.sleep(pause)
                assert Target.value == expected
                assert path_call() == expected
                assert not hasattr(Target, "deleted")
                assert mapping["value"] == expected
                with pytest.raises(KeyError):
                    str(mapping["deleted"])
                assert items[0] == expected
                with pytest.raises(IndexError):
                    str(items[1])


            @rue.test.iterate.params(
                "case,pause",
                [("left", 0.10), ("right", 0.02)],
            )
            @rue.test.backend(ExecutionBackend.SUBPROCESS)
            async def test_003_subprocess_conflicts(
                case,
                pause,
                monkeypatch,
            ):
                assert Target.value == "original"
                assert Target.deleted == "present"
                assert path_call() == "original"
                assert mapping["value"] == "original"
                assert mapping["deleted"] == "present"
                assert items[0] == "original"
                assert items[1] == "present"

                expected = f"subprocess:{case}"
                monkeypatch.setattr(Target, "value", expected)
                monkeypatch.setattr(
                    __name__ + ":path_call",
                    lambda expected=expected: expected,
                )
                monkeypatch.delattr(Target, "deleted")
                monkeypatch.setitem(mapping, "value", expected)
                monkeypatch.delitem(mapping, "deleted")
                monkeypatch.setitem(items, expected, idx=0, replace=True)
                monkeypatch.delitem(items, idx=1, replace=True)

                inserted = ["tail"]
                monkeypatch.setitem(inserted, expected, idx=0, replace=False)
                assert inserted[0] == expected
                assert inserted[1] == "tail"

                await asyncio.sleep(pause)
                assert Target.value == expected
                assert path_call() == expected
                assert not hasattr(Target, "deleted")
                assert mapping["value"] == expected
                with pytest.raises(KeyError):
                    str(mapping["deleted"])
                assert items[0] == expected
                with pytest.raises(IndexError):
                    str(items[1])


            @rue.test.iterate.params(
                "case,pause",
                [("left", 0.11), ("right", 0.05)],
            )
            def test_004_default_blocking_conflicts(
                case,
                pause,
                monkeypatch,
            ):
                assert Target.value == "original"
                assert Target.deleted == "present"
                assert path_call() == "original"
                assert mapping["value"] == "original"
                assert mapping["deleted"] == "present"
                assert items[0] == "original"
                assert items[1] == "present"

                expected = f"default-blocking:{case}"
                monkeypatch.setattr(Target, "value", expected)
                monkeypatch.setattr(
                    __name__ + ":path_call",
                    lambda expected=expected: expected,
                )
                monkeypatch.delattr(Target, "deleted")
                monkeypatch.setitem(mapping, "value", expected)
                monkeypatch.delitem(mapping, "deleted")
                monkeypatch.setitem(items, expected, idx=0, replace=True)
                monkeypatch.delitem(items, idx=1, replace=True)

                inserted = ["tail"]
                monkeypatch.setitem(inserted, expected, idx=0, replace=False)
                assert inserted[0] == expected
                assert inserted[1] == "tail"

                time.sleep(pause)
                assert Target.value == expected
                assert path_call() == expected
                assert not hasattr(Target, "deleted")
                assert mapping["value"] == expected
                with pytest.raises(KeyError):
                    str(mapping["deleted"])
                assert items[0] == expected
                with pytest.raises(IndexError):
                    str(items[1])


            @rue.test.iterate.params(
                "case,pause",
                [("left", 0.07), ("right", 0.01)],
            )
            @rue.test.backend(ExecutionBackend.MAIN)
            def test_005_main_blocking_conflicts(case, pause, monkeypatch):
                assert Target.value == "original"
                assert Target.deleted == "present"
                assert path_call() == "original"
                assert mapping["value"] == "original"
                assert mapping["deleted"] == "present"
                assert items[0] == "original"
                assert items[1] == "present"

                expected = f"main-two:{case}"
                monkeypatch.setattr(Target, "value", expected)
                monkeypatch.setattr(
                    __name__ + ":path_call",
                    lambda expected=expected: expected,
                )
                monkeypatch.delattr(Target, "deleted")
                monkeypatch.setitem(mapping, "value", expected)
                monkeypatch.delitem(mapping, "deleted")
                monkeypatch.setitem(items, expected, idx=0, replace=True)
                monkeypatch.delitem(items, idx=1, replace=True)

                inserted = ["tail"]
                monkeypatch.setitem(inserted, expected, idx=0, replace=False)
                assert inserted[0] == expected
                assert inserted[1] == "tail"

                time.sleep(pause)
                assert Target.value == expected
                assert path_call() == expected
                assert not hasattr(Target, "deleted")
                assert mapping["value"] == expected
                with pytest.raises(KeyError):
                    str(mapping["deleted"])
                assert items[0] == expected
                with pytest.raises(IndexError):
                    str(items[1])


            @rue.test.iterate.params(
                "case,pause",
                [("left", 0.02), ("right", 0.08)],
            )
            async def test_006_default_async_conflicts(
                case,
                pause,
                monkeypatch,
            ):
                assert Target.value == "original"
                assert Target.deleted == "present"
                assert path_call() == "original"
                assert mapping["value"] == "original"
                assert mapping["deleted"] == "present"
                assert items[0] == "original"
                assert items[1] == "present"

                expected = f"default-async-two:{case}"
                monkeypatch.setattr(Target, "value", expected)
                monkeypatch.setattr(
                    __name__ + ":path_call",
                    lambda expected=expected: expected,
                )
                monkeypatch.delattr(Target, "deleted")
                monkeypatch.setitem(mapping, "value", expected)
                monkeypatch.delitem(mapping, "deleted")
                monkeypatch.setitem(items, expected, idx=0, replace=True)
                monkeypatch.delitem(items, idx=1, replace=True)

                inserted = ["tail"]
                monkeypatch.setitem(inserted, expected, idx=0, replace=False)
                assert inserted[0] == expected
                assert inserted[1] == "tail"

                await asyncio.sleep(pause)
                assert Target.value == expected
                assert path_call() == expected
                assert not hasattr(Target, "deleted")
                assert mapping["value"] == expected
                with pytest.raises(KeyError):
                    str(mapping["deleted"])
                assert items[0] == expected
                with pytest.raises(IndexError):
                    str(items[1])
            """
        )
    )

    run = await _run_module(module_path)

    assert run.result.passed == 6, _failed_executions(run)
