"""Testing framework for AI agents."""

from rue.resources import ResourceResolver, Scope, resource
from rue.testing.decorators import (
    iter_case_groups,
    iter_cases,
    parametrize,
    repeat,
    run_inline,
    tag,
)
from rue.testing.discovery import collect
from rue.testing.environment import capture_environment
from rue.testing.execution import (
    CaseGroupIteratedTest,
    CaseIteratedTest,
    DefaultTestFactory,
    ParametrizedTest,
    ParametrizedRueTest,
    RepeatedTest,
    RepeatedRueTest,
    ResultBuilder,
    SingleTest,
    SingleRueTest,
    Test,
    TestFactory,
    RueTest,
)
from rue.testing.models import (
    Case,
    CaseGroup,
    CaseGroupIterateModifier,
    Run,
    TestDefinition,
    RueRun,
    RueTestDefinition,
    CaseIterateModifier,
    Modifier,
    ParameterSet,
    ParametrizeModifier,
    RepeatModifier,
    RunEnvironment,
    RunResult,
    TestExecution,
    TestResult,
    TestStatus,
)
from rue.testing.outcomes import (
    FailTest,
    SkipTest,
    XFailTest,
    fail,
    skip,
    xfail,
)
from rue.testing.runner import Runner


# Backwards compatibility alias
TestItem = TestDefinition

__all__ = [
    "Case",
    "CaseGroup",
    "CaseGroupIterateModifier",
    "CaseGroupIteratedTest",
    "CaseIteratedTest",
    "CaseIterateModifier",
    "DefaultTestFactory",
    "FailTest",
    "ParametrizedTest",
    "RepeatedTest",
    "Run",
    "SingleTest",
    "Test",
    "TestDefinition",
    "RueRun",
    "RueTest",
    "RueTestDefinition",
    "Modifier",
    "ParameterSet",
    "ParametrizeModifier",
    "ParametrizedRueTest",
    "RepeatModifier",
    "RepeatedRueTest",
    "ResourceResolver",
    "ResultBuilder",
    "RunEnvironment",
    "RunResult",
    "Runner",
    "Scope",
    "SingleRueTest",
    "SkipTest",
    "TestExecution",
    "TestFactory",
    "TestItem",  # alias
    "TestResult",
    "TestStatus",
    "XFailTest",
    "capture_environment",
    "collect",
    "fail",
    "iter_cases",
    "iter_case_groups",
    "parametrize",
    "repeat",
    "resource",
    "run_inline",
    "skip",
    "tag",
    "xfail",
]
