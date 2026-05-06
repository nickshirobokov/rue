from contextlib import redirect_stdout
from io import StringIO

from rue.resources.sut.output import SUTOutputCapture


def test_sut_output_is_captured_without_reaching_stdout() -> None:
    output = StringIO()
    capture = SUTOutputCapture()

    def write_output() -> None:
        print("from sut")

    wrapped = capture.wrap(write_output, is_async=False)

    with redirect_stdout(output):
        wrapped()

    assert output.getvalue() == ""
    assert capture.stdout.text == "from sut\n"


def test_non_sut_output_is_not_captured() -> None:
    output = StringIO()
    capture = SUTOutputCapture()

    with redirect_stdout(output):
        print("from test")

    assert output.getvalue() == "from test\n"
    assert capture.output.events == ()
