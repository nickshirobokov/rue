"""Tests for sys-level output capture."""

import sys

from rue.resources.sut.output import SUTOutputCapture


class TestSysOutputCapture:
    def test_install_replaces_sys_streams(self):
        original_stdout = sys.stdout
        original_stderr = sys.stderr

        with SUTOutputCapture.sys_capture(swallow=True):
            assert sys.stdout is not original_stdout
            assert sys.stderr is not original_stderr

        assert sys.stdout is original_stdout
        assert sys.stderr is original_stderr

    def test_capture_routes_stdout_and_stderr(self):
        capture = SUTOutputCapture()

        with capture.capturing():
            sys.stdout.write("hello")
            sys.stderr.write("error\n")

        assert [
            (event.stream, event.text) for event in capture.output.events
        ] == [("stdout", "hello"), ("stderr", "error\n")]

    def test_swallow_true_hides_output_when_sink_active(self, capsys):
        capture = SUTOutputCapture()

        with SUTOutputCapture.sys_capture(swallow=True):
            with capture.capturing():
                sys.stdout.write("hidden")

        real_out, _ = capsys.readouterr()
        assert "hidden" not in real_out

    def test_swallow_true_passes_through_when_no_sink(self, capsys):
        with SUTOutputCapture.sys_capture(swallow=True):
            sys.stdout.write("visible")

        real_out, _ = capsys.readouterr()
        assert "visible" in real_out

    def test_swallow_false_shows_output(self, capsys):
        capture = SUTOutputCapture()

        with SUTOutputCapture.sys_capture(swallow=False):
            with capture.capturing():
                sys.stdout.write("visible")

        real_out, _ = capsys.readouterr()
        assert real_out == "visible"
        assert capture.stdout.text == "visible"

    def test_nested_captures_fan_out_to_all_sinks(self):
        outer = SUTOutputCapture()
        inner = SUTOutputCapture()

        with SUTOutputCapture.sys_capture(swallow=True):
            with outer.capturing():
                with inner.capturing():
                    sys.stderr.write("nested")

        assert [
            (event.stream, event.text) for event in outer.output.events
        ] == [("stderr", "nested")]
        assert [
            (event.stream, event.text) for event in inner.output.events
        ] == [("stderr", "nested")]


class TestSysOutputCaptureContextManager:
    def test_installs_global_capture_temporarily(self):
        assert not SUTOutputCapture.is_sys_capture_installed()

        with SUTOutputCapture.sys_capture(swallow=True):
            assert SUTOutputCapture.is_sys_capture_installed()

        assert not SUTOutputCapture.is_sys_capture_installed()


class TestGlobalListener:
    def setup_method(self):
        SUTOutputCapture.clear_global_listener()

    def teardown_method(self):
        SUTOutputCapture.clear_global_listener()

    def test_global_listener_receives_non_sut_stderr(self):
        received: list[tuple[str, str]] = []

        SUTOutputCapture.set_global_listener(
            lambda stream, s: received.append((stream, s))
        )

        with SUTOutputCapture.sys_capture(swallow=True):
            sys.stderr.write("warning\n")

        assert received == [("stderr", "warning\n")]

    def test_global_listener_skipped_when_sut_swallows(self):
        received: list[tuple[str, str]] = []
        capture = SUTOutputCapture()

        SUTOutputCapture.set_global_listener(
            lambda stream, s: received.append((stream, s))
        )

        with SUTOutputCapture.sys_capture(swallow=True):
            with capture.capturing():
                sys.stderr.write("sut-only\n")

        assert capture.stderr.text == "sut-only\n"
        assert received == []

    def test_global_listener_receives_when_sut_does_not_swallow(self):
        received: list[tuple[str, str]] = []
        capture = SUTOutputCapture()

        SUTOutputCapture.set_global_listener(
            lambda stream, s: received.append((stream, s))
        )

        with SUTOutputCapture.sys_capture(swallow=False):
            with capture.capturing():
                sys.stderr.write("shared\n")

        assert capture.stderr.text == "shared\n"
        assert received == [("stderr", "shared\n")]

    def test_global_listener_not_called_for_stdout(self):
        received: list[tuple[str, str]] = []

        SUTOutputCapture.set_global_listener(
            lambda stream, s: received.append((stream, s))
        )

        with SUTOutputCapture.sys_capture(swallow=True):
            sys.stdout.write("stdout-only\n")

        stderr_received = [r for r in received if r[0] == "stderr"]
        assert stderr_received == []

    def test_clear_global_listener_stops_receiving(self):
        received: list[tuple[str, str]] = []

        SUTOutputCapture.set_global_listener(
            lambda stream, s: received.append((stream, s))
        )
        SUTOutputCapture.clear_global_listener()

        with SUTOutputCapture.sys_capture(swallow=True):
            sys.stderr.write("nothing\n")

        assert received == []
