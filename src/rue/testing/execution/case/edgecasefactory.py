"""AI-backed case factories for adversarial test attempts."""

from __future__ import annotations

import inspect
import json
import re
import subprocess
from pathlib import Path
from typing import Any

from pydantic import BaseModel
from pydantic_ai import (
    Agent,
    DeferredToolRequests,
    DeferredToolResults,
    ExternalToolset,
    FunctionToolset,
    ModelRetry,
    ToolDefinition,
)
from pydantic_ai.messages import ModelMessage, ModelRequest, UserPromptPart
from pydantic_ai.models import KnownModelName
from pydantic_ai.settings import ModelSettings

from rue.analysis.dep_collector import collect_dependencies
from rue.testing.execution.case.basefactory import CaseFactory
from rue.testing.execution.case.models import Case
from rue.testing.execution.models import ExecutedTest, LoadedTestDef


class CaseReview(BaseModel):
    """Validation result for a proposed edge case."""

    valid: bool
    message: str


class EdgeCaseFactory[CaseT: Case[Any, Any]](CaseFactory):
    """Generate valid cases that try to break a test's assertions."""

    def __init__(
        self,
        *,
        case_model: type[CaseT],
        max_attempts: int = 3,
        display_name: str = "edge_cases",
        model: KnownModelName | str = "openai:gpt-5.4",
        model_settings: ModelSettings | None = None,
    ) -> None:
        super().__init__(
            max_attempts=max_attempts,
            display_name=display_name,
        )
        self.case_model = case_model
        self.provide_case_tool = ToolDefinition(
            name="provide_case",
            description=(
                "Provide final Case values for the next adaptive attempt."
            ),
            parameters_json_schema=self.case_model.model_json_schema(),
        )
        self.external_toolset = ExternalToolset([self.provide_case_tool])
        self.internal_toolset = FunctionToolset(
            [
                self.grep_local_files,
                self.get_dependency_graph,
            ]
        )

        self.main_agent = Agent(
            model=model,
            output_type=[DeferredToolRequests, type(None)],
            instructions=(
                "Analyze the test and provide Case values that have the "
                "highest chance of failing assertions in the test body while "
                "still being valid for the described inputs and references."
            ),
            model_settings=model_settings,
            toolsets=[self.external_toolset, self.internal_toolset],
            retries=3,
        )
        self.main_agent.output_validator(self._validate_output)
        self.main_agent_messages: list[ModelMessage] = []

        self.reviewer_agent = Agent(
            model,
            output_type=CaseReview,
            instructions=(
                "Check whether proposed Case values are valid for the test "
                "description and schema. Reject invalid, missing, or "
                "impossible values even if they might fail the test."
            ),
            model_settings=model_settings,
        )

        self._loaded_test: LoadedTestDef | None = None
        self._test_body = ""
        self._case_schema: dict[str, Any] = {}

        self.pending_tool_results: DeferredToolResults | None = None
        self.last_tool_call_id: str | None = None
        self.proposed_case: CaseT | None = None
        self.generated_cases_count = 0

    async def next_case(
        self,
        loaded_test: LoadedTestDef,
    ) -> CaseT | None:
        """Return the next edge case generated for ``loaded_test``."""
        if self.generated_cases_count >= self.max_attempts:
            return None

        if not self._loaded_test:
            self._loaded_test = loaded_test

        if not self._test_body:
            self._test_body = self._load_test_body(loaded_test)

        if not self._case_schema:
            self._case_schema = self.case_model.model_json_schema()

        self.proposed_case = None
        self.last_tool_call_id = None

        if not self.main_agent_messages:
            self.main_agent_messages = [
                ModelRequest(
                    parts=[
                        UserPromptPart(
                            content=(
                                "You generate edge cases for Rue tests. Use "
                                "tools if you need local context. Call "
                                "provide_case with a complete Case object "
                                "when ready.\n"
                                f"Test code body: {self._test_body}\n"
                                f"Case JSON schema: {self._case_schema}"
                            )
                        )
                    ]
                )
            ]

        while self.proposed_case is None:
            deferred_results = self.pending_tool_results
            self.pending_tool_results = None
            result = await self.main_agent.run(
                message_history=self.main_agent_messages,
                deferred_tool_results=deferred_results,
            )

            assert result.output is not None
            self.main_agent_messages = list(result.all_messages())

            for tool_call in result.output.calls:
                if tool_call.tool_name != self.provide_case_tool.name:
                    continue

                review_prompt = (
                    f"Test code body:{self._test_body}\n"
                    f"Case JSON schema:{self._case_schema}\n"
                    "Proposed Case:"
                    f"{json.dumps(tool_call.args, indent=2, default=str)}"
                )
                review_result = await self.reviewer_agent.run(
                    user_prompt=review_prompt
                )
                if review_result.output.valid:
                    self.proposed_case = self.case_model.model_validate(
                        tool_call.args
                    )
                    self.last_tool_call_id = tool_call.tool_call_id
                    self.generated_cases_count += 1
                    break

                self.pending_tool_results = DeferredToolResults()
                self.pending_tool_results.calls[tool_call.tool_call_id] = (
                    ModelRetry(review_result.output.message)
                )
                break

        return self.proposed_case

    async def observe(
        self,
        case: CaseT,
        execution: ExecutedTest,
    ) -> None:
        """Append the observed execution outcome to the agent history."""
        _ = case
        if self.last_tool_call_id is None:
            raise ValueError("No tool call ID found.")
        self.pending_tool_results = DeferredToolResults()
        self.pending_tool_results.calls[self.last_tool_call_id] = (
            execution.result
        )

    def grep_local_files(
        self,
        pattern: str,
        path: str = ".",
    ) -> str:
        """Search suite-local files with a regular expression."""
        if self._loaded_test is None:
            return "No loaded test is active."
        root = self._loaded_test.suite_root.resolve()
        target = (root / path).resolve()
        if not target.is_relative_to(root):
            return "Path must stay inside the loaded suite root."
        command = [
            "rg",
            "--line-number",
            "--no-heading",
            "--color",
            "never",
            pattern,
            str(target),
        ]
        try:
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
            )
        except FileNotFoundError:
            return self._python_grep(pattern, target)
        except subprocess.TimeoutExpired:
            return "Search timed out."
        if completed.returncode not in {0, 1}:
            return completed.stderr.strip()[:12000] or "Search failed."
        output = completed.stdout.strip()
        if not output:
            return "No matches."
        return output[:12000]

    def get_dependency_graph(
        self,
        member_name: str | None = None,
    ) -> list[dict[str, str]]:
        """Return repository-local dependencies for a callable member."""
        if self._loaded_test is None:
            return [{"module": "error", "path": "No loaded test active."}]
        target = self._loaded_test.fn
        if member_name is not None:
            member = target.__globals__.get(member_name)
            if not callable(member):
                return [
                    {
                        "module": "error",
                        "path": f"Callable member not found: {member_name}",
                    }
                ]
            target = member
        return [
            {
                "module": entry.module_name,
                "path": str(entry.file_path),
            }
            for entry in collect_dependencies(
                target,
                mode="symbol",
            )
        ]

    def _load_test_body(self, loaded_test: LoadedTestDef) -> str:
        try:
            return inspect.getsource(loaded_test.fn)
        except OSError:
            return loaded_test.spec.full_name

    def _python_grep(self, pattern: str, target: Path) -> str:
        try:
            regex = re.compile(pattern)
        except re.error as exc:
            return f"Invalid regular expression: {exc}"
        files = [target] if target.is_file() else target.rglob("*")
        matches: list[str] = []
        for file_path in files:
            if not file_path.is_file():
                continue
            try:
                lines = file_path.read_text(encoding="utf-8").splitlines()
            except UnicodeDecodeError:
                continue
            for line_number, line in enumerate(lines, start=1):
                if regex.search(line):
                    matches.append(f"{file_path}:{line_number}:{line}")
            if len(matches) >= 200:
                break
        return "\n".join(matches)[:12000] or "No matches."

    @staticmethod
    def _validate_output(
        output: DeferredToolRequests | None,
    ) -> DeferredToolRequests:
        if output is None:
            raise ModelRetry("Agent must use tools.")
        return output
