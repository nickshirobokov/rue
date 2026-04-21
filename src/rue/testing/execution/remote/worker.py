"""Worker-side entrypoint for remote test execution."""

from __future__ import annotations

import asyncio
import logging
import time
from functools import partial
from typing import TYPE_CHECKING, Any

from rue.assertions.base import AssertionResult
from rue.context.collectors import CURRENT_ASSERTION_RESULTS
from rue.context.runtime import (
    CURRENT_RESOURCE_CONSUMER,
    CURRENT_RESOURCE_CONSUMER_KIND,
    CURRENT_TEST,
    CURRENT_TEST_TRACER,
    TestContext,
    bind,
)
from rue.resources import ResourceResolver
from rue.resources.models import Scope
from rue.resources.registry import registry as default_resource_registry
from rue.testing.discovery.loader import TestLoader
from rue.testing.execution.remote.models import (
    ExecutorPayload,
    RemoteExecutionResult,
)
from rue.testing.models import TestResult, TestStatus
from rue.testing.outcomes import FailTest, SkipTest, XFailTest
from rue.testing.tracing import build_test_tracer


if TYPE_CHECKING:
    from rue.testing.models import LoadedTestDef


logger = logging.getLogger(__name__)


def run_remote_test(payload: ExecutorPayload) -> RemoteExecutionResult:
    """Synchronous entrypoint submitted to a ProcessPoolExecutor worker."""
    return asyncio.run(_run_remote_test(payload))


async def _run_remote_test(payload: ExecutorPayload) -> RemoteExecutionResult:
    loader = TestLoader(payload.suite_root)
    for ref in payload.setup_chain:
        loader.prepare_setup(ref.path)

    definition = loader.load_definition(
        payload.spec,
        setup_chain=payload.setup_chain,
    )

    resolver = await ResourceResolver.hydrate_from_sync_snapshot(
        payload.snapshot,
        default_resource_registry,
    )

    assertion_results: list[AssertionResult] = []
    error: BaseException | None = None
    imperative_outcome: TestStatus | None = None
    telemetry_artifacts = ()
    tracer = build_test_tracer(
        config=payload.config,
        run_id=payload.run_id,
    )

    ctx = TestContext(item=definition, execution_id=payload.execution_id)

    with bind(CURRENT_TEST_TRACER, tracer):
        tracer.start(definition, execution_id=payload.execution_id)
        with (
            bind(CURRENT_TEST, ctx),
            bind(CURRENT_ASSERTION_RESULTS, assertion_results),
        ):
            try:
                start = time.perf_counter()
                kwargs = await _resolve_params(
                    resolver, definition, payload.params
                )
                await _invoke(definition, kwargs)
            except SkipTest as e:
                imperative_outcome = TestStatus.SKIPPED
                error = e
            except FailTest as e:
                imperative_outcome = TestStatus.FAILED
                error = e
            except XFailTest as e:
                imperative_outcome = TestStatus.XFAILED
                error = e
            except Exception as e:  # noqa: BLE001
                error = e

        duration_ms = (time.perf_counter() - start) * 1000

        if imperative_outcome is not None:
            result = TestResult(
                status=imperative_outcome,
                duration_ms=duration_ms,
                error=error,
                assertion_results=assertion_results,
            )
        else:
            expect_failure = definition.spec.xfail_reason is not None
            failed_assertions = [ar for ar in assertion_results if not ar.passed]
            has_error = error is not None and not isinstance(
                error, AssertionError
            )
            has_assertion_fail = bool(failed_assertions) or isinstance(
                error, AssertionError
            )

            match (has_error, has_assertion_fail, expect_failure):
                case (True, _, True):
                    status, result_error = TestStatus.XFAILED, error
                case (True, _, False):
                    status, result_error = TestStatus.ERROR, error
                case (_, True, xfail):
                    status = TestStatus.XFAILED if xfail else TestStatus.FAILED
                    if error is None and failed_assertions:
                        msg = (
                            failed_assertions[0].error_message
                            or failed_assertions[0].expression_repr.expr
                        )
                        result_error = AssertionError(msg)
                    else:
                        result_error = error
                case (_, _, True) if definition.spec.xfail_strict:
                    status = TestStatus.FAILED
                    result_error = AssertionError(
                        definition.spec.xfail_reason or "xfail test passed"
                    )
                case (_, _, True):
                    status, result_error = TestStatus.XPASSED, None
                case _:
                    status, result_error = TestStatus.PASSED, None

            result = TestResult(
                status=status,
                duration_ms=duration_ms,
                error=result_error,
                assertion_results=assertion_results.copy(),
            )

        try: # no ctx required: resolver in shadow mode, and teardown happens in the local one 
            await resolver.teardown_scope(Scope.TEST)
        except Exception as teardown_err:
            logger.warning(
                f"Error during resource teardown: {teardown_err}"
            )
            if result.error is None:
                result.error = teardown_err

        tracer.record_result(result)
        telemetry_artifacts = tracer.finish()

    sync_update = resolver.sync_update_since(
        payload.snapshot.base_state,
        list(payload.snapshot.res_specs),
    )

    return RemoteExecutionResult(
        result=result,
        telemetry_artifacts=telemetry_artifacts,
        sync_update=sync_update,
    )


async def _resolve_params(
    resolver: ResourceResolver,
    definition: LoadedTestDef,
    preset: dict[str, Any],
) -> dict[str, Any]:
    kwargs = dict(preset)
    with (
        bind(CURRENT_RESOURCE_CONSUMER, definition.spec.name),
        bind(CURRENT_RESOURCE_CONSUMER_KIND, "test"),
    ):
        for param in definition.spec.params:
            if param not in kwargs:
                kwargs[param] = await resolver.resolve(param)
    return kwargs


async def _invoke(definition: LoadedTestDef, kwargs: dict[str, Any]) -> None:
    fn = definition.fn
    instance = None

    if definition.spec.class_name:
        cls = fn.__globals__.get(definition.spec.class_name)
        if cls is None:
            raise RuntimeError(
                f"Test class '{definition.spec.class_name}' not found for test '{definition.spec.name}'"
            )
        instance = cls()

    call = (
        partial(fn, instance, **kwargs) if instance else partial(fn, **kwargs)
    )

    if definition.spec.is_async:
        await call()
    elif definition.spec.inline:
        call()
    else:
        await asyncio.to_thread(call)
