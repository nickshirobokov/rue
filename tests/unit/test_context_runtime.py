from pathlib import Path
from uuid import uuid4

import pytest

from rue.context.runtime import (
    CURRENT_TEST,
    ModuleContext,
    SuiteContext,
    TestContext,
)
from rue.context.scopes import Scope, ScopeContext


def test_module_context_exposes_module_owner_without_test_owner(
    tmp_path: Path,
):
    module_path = tmp_path / "test_module.py"

    with SuiteContext() as suite_context:
        with ModuleContext(module_path):
            owner = ScopeContext.current_owner(Scope.MODULE)

            assert owner.scope is Scope.MODULE
            assert owner.suite_execution_id == suite_context.suite_execution_id
            assert owner.module_path == module_path
            with pytest.raises(RuntimeError, match="Test-scoped resources"):
                ScopeContext.current_owner(Scope.TEST)
            with pytest.raises(LookupError):
                CURRENT_TEST.get()


def test_test_context_layers_test_owner_over_active_module(
    tmp_path: Path,
):
    module_path = tmp_path / "test_module.py"

    with SuiteContext():
        with ModuleContext(module_path):
            module_owner = ScopeContext.current_owner(Scope.MODULE)
            with TestContext(test_execution_id=uuid4()):
                assert ScopeContext.current_owner(Scope.MODULE) == module_owner
                assert (
                    ScopeContext.current_owner(Scope.TEST).module_path is None
                )
