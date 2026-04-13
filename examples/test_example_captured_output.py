"""Example: Inspecting SUT-owned stdout/stderr capture.

Run with:
    rue test examples/test_example_captured_output.py

Run with live SUT output visible:
    rue test examples/test_example_captured_output.py -s
"""

import sys

import rue


class Greeter:
    def __init__(self, prefix: str = "Hello") -> None:
        self.prefix = prefix

    def greet(self, name: str) -> str:
        message = f"{self.prefix}, {name}!"
        print(message)
        return message

    def warn(self, name: str) -> None:
        sys.stderr.write(f"warn:{name}\n")


@rue.resource.sut
def greeter():
    return rue.SUT(Greeter(), methods=["greet", "warn"])


@rue.test
def test_capture_stdout(greeter):
    result = greeter.instance.greet("Alice")

    assert result == "Hello, Alice!"
    assert greeter.stdout.text == "Hello, Alice!\n"
    assert greeter.stderr.text == ""


@rue.test
def test_capture_stderr(greeter):
    greeter.instance.warn("Bob")

    assert greeter.stdout.text == ""
    assert greeter.stderr.lines == ("warn:Bob",)


@rue.test
def test_capture_multiple_calls(greeter):
    greeter.instance.greet("Alice")
    greeter.instance.greet("Bob")

    assert greeter.stdout.lines == ("Hello, Alice!", "Hello, Bob!")


@rue.test
def test_clear_output(greeter):
    greeter.instance.greet("Alice")
    assert greeter.stdout.text == "Hello, Alice!\n"

    greeter.clear_output()

    assert greeter.captured_output.events == ()
    assert greeter.captured_output.combined.text == ""
