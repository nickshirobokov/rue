from typing import Generator

from rue.resources import resource, Scope, register_builtin
from rue.telemetry.otel import OtelTrace
from rue.context.runtime import CURRENT_TEST_TRACER
from rue.context.output import CURRENT_OUTPUT_CAPTURE, OutputBuffer


@resource(scope=Scope.CASE)
def otel_trace() -> Generator[OtelTrace, None, None]:
    """Provide access to OpenTelemetry data for the current test."""
    tracer = CURRENT_TEST_TRACER.get()
    if tracer is None or not tracer.has_otel_trace:
        raise RuntimeError(
            "OpenTelemetry is not enabled; cannot resolve otel_trace resource."
        )
    yield OtelTrace(_session=tracer.otel_trace_session)


register_builtin("otel_trace")


@resource(scope=Scope.CASE)
def captured_output() -> Generator[OutputBuffer, None, None]:
    """Provide access to captured stdout/stderr for the current test.

    Usage:
        def test_my_test(captured_output):
            print("hello")
            out, err = captured_output.readouterr()
            assert out == "hello\\n"
    """
    capture = CURRENT_OUTPUT_CAPTURE.get()
    if capture is None:
        raise RuntimeError("Output capture not enabled")
    with capture.capture() as buf:
        yield buf


register_builtin("captured_output")