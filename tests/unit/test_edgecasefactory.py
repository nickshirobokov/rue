"""Tests for AI-backed edge case factories."""

from pathlib import Path

import pytest
from pydantic_ai.exceptions import UnexpectedModelBehavior
from pydantic_ai.models.test import TestModel

from rue.testing.execution.case import Case, EdgeCaseFactory
from tests.helpers import make_definition


@pytest.mark.asyncio
async def test_edge_case_factory_exposes_read_only_backend_tools(
    tmp_path: Path,
) -> None:
    model = TestModel(call_tools=[])
    factory = EdgeCaseFactory(case_model=Case, model=model)
    loaded_test = make_definition(
        fn=lambda: None,
        module_path=tmp_path / "test_subject.py",
        suite_root=tmp_path,
    )

    with pytest.raises(UnexpectedModelBehavior):
        await factory.next_case(loaded_test)

    assert model.last_model_request_parameters is not None
    tool_names = {
        tool.name for tool in model.last_model_request_parameters.function_tools
    }
    assert tool_names == {
        "compact_conversation",
        "glob",
        "grep",
        "ls",
        "provide_case",
        "read_file",
    }
    assert tool_names - {"provide_case"} == {
        "compact_conversation",
        "glob",
        "grep",
        "ls",
        "read_file",
    }


@pytest.mark.asyncio
async def test_edge_case_factory_backend_is_read_only_and_suite_scoped(
    tmp_path: Path,
) -> None:
    suite_file = tmp_path / "test_subject.py"
    suite_file.write_text("def test_subject():\n    marker = 'needle'\n")
    outside_file = tmp_path.parent / f"{tmp_path.name}_outside.py"
    outside_file.write_text("outside = 'needle'\n")

    factory = EdgeCaseFactory(case_model=Case, model=TestModel(call_tools=[]))
    loaded_test = make_definition(
        fn=lambda: None,
        module_path=suite_file,
        suite_root=tmp_path,
    )

    with pytest.raises(UnexpectedModelBehavior):
        await factory.next_case(loaded_test)
    assert factory._main_agent_backend is not None
    backend = factory._main_agent_backend.backend

    assert backend.execute_enabled is False
    assert [entry["path"] for entry in backend.glob_info("*.py", ".")] == [
        str(suite_file)
    ]

    matches = backend.grep_raw("needle", "test_subject.py")
    assert isinstance(matches, list)
    assert matches[0]["path"] == str(suite_file)
    assert matches[0]["line_number"] == 2

    outside_result = backend.grep_raw("needle", str(outside_file))
    assert isinstance(outside_result, str)
    assert "outside allowed directories" in outside_result


def test_edge_case_factory_does_not_preload_main_agent_history(
    tmp_path: Path,
) -> None:
    factory = EdgeCaseFactory(case_model=Case, model=TestModel(call_tools=[]))
    loaded_test = make_definition(
        fn=lambda: None,
        module_path=tmp_path / "test_subject.py",
        suite_root=tmp_path,
    )

    factory._build_main_agent(loaded_test)

    assert factory.main_agent_messages == []
