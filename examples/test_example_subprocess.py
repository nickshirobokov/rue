import time
import rue
from rue import ExecutionBackend
from rue.resources import resource
from rue.resources.models import Scope

@resource(scope=Scope.PROCESS)
def shared_events():
    return []

@rue.test.backend(ExecutionBackend.SUBPROCESS)
@rue.test.iterate.params("event", [("one",), ("two",)])
def test_remote(event, shared_events):
    if event == "one":
        time.sleep(0.1)
    else:
        time.sleep(0.3)
    shared_events.append(event)

@rue.test.backend(ExecutionBackend.MAIN)
def test_after(shared_events):
    assert shared_events == ["one", "two"]
