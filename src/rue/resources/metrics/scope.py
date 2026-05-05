from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING

from rue.context.runtime import bind


if TYPE_CHECKING:
    from rue.resources.metrics.metric import Metric


ACTIVE_ASSERTION_METRICS: ContextVar[list[Metric] | None] = ContextVar(
    "active_assertion_metrics", default=None
)


@contextmanager
def metrics(*metrics: Metric) -> Iterator[None]:
    metrics_list = list(metrics)
    if len(metrics_list) == 1 and isinstance(metrics_list[0], (list, tuple)):
        metrics_list = list(metrics_list[0])

    with bind(ACTIVE_ASSERTION_METRICS, metrics_list):
        yield
