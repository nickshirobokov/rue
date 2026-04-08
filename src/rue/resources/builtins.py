from typing import Generator

from rue.context.output import CURRENT_OUTPUT_CAPTURE, OutputBuffer
from rue.resources.registry import Scope, registry, resource


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


registry.mark_builtin("captured_output")
