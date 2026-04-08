from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from rue.context.collectors import CURRENT_ASSERTION_RESULTS
from rue.context.runtime import CURRENT_TEST
from rue.resources.metrics.scope import ACTIVE_ASSERTION_METRICS


if TYPE_CHECKING:
    from rue.predicates.models import PredicateResult


@dataclass
class AssertionRepr:
    """Represents a human-readable representation of an assertion expression.

    This class captures the assertion expression along with surrounding context
    lines and resolved argument values for debugging and reporting purposes.

    Attributes:
    ----------
    expr : str
        The assertion expression as a string.
    lines_above : str
        Source code lines appearing above the assertion expression.
    lines_below : str
        Source code lines appearing below the assertion expression.
    resolved_args : dict[str, str]
        A dictionary mapping argument names to their string representations,
        showing the resolved values of variables used in the assertion.
    """

    expr: str
    lines_above: str
    lines_below: str
    resolved_args: dict[str, str]


@dataclass
class AssertionResult:
    """Represents the result of an assertion evaluation in a rue test.

    This class captures the outcome of an assertion, including whether it passed,
    the original expression, any error messages, and results from predicate evaluations.

    Attributes:
    ----------
    expression_repr : AssertionRepr
        A human-readable representation of the assertion expression, including
        the expression string and resolved argument values.
    passed : bool
        Whether the assertion passed (True) or failed (False).
    error_message : str or None, optional
        An error message describing why the assertion failed, if applicable.
    predicate_results : list[PredicateResult], optional
        Results from any predicate evaluations that were part of this assertion.
    """

    expression_repr: AssertionRepr
    passed: bool
    error_message: str | None = None
    predicate_results: list[PredicateResult] = field(default_factory=list)

    def __post_init__(self) -> None:
        collector = CURRENT_ASSERTION_RESULTS.get()
        if collector is not None:
            collector.append(self)

        metrics = ACTIVE_ASSERTION_METRICS.get()
        if metrics is not None:
            for metric in metrics:
                metric.add_record(self.passed)

        test_ctx = CURRENT_TEST.get()
        if test_ctx is not None:
            if test_ctx.item.fail_fast and not self.passed:
                msg = (
                    self.error_message
                    or f"Assertion failed: {self.expression_repr.expr}"
                )
                raise AssertionError(msg)


def capture_var(values: dict[str, str], name: str, value: object) -> object:
    """Capture a variable's value and store it in a dictionary."""
    values[name] = repr(value)
    return value
