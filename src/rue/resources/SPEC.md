# Resource DI SPEC

**Status:** Draft
**Intended use:** Short map of Rue's dependency injection runtime

Rue resources are named providers selected at graph-compile time and owned at
runtime by `ScopeOwner`. Resolution returns kwargs for a consumer, caches
created values by scope owner, and tears generator resources down when that
owner ends.

## User Story

Resources are Rue's mirror of pytest fixtures. Users define named setup units
once and tests ask for them by parameter name. Rue also rewrites supported
top-level `pytest.fixture` declarations into resources while loading test
modules, so fixture-shaped setup can enter the same runtime.

```python
import rue


@rue.resource(scope="module")
def client():
    return APIClient()


@rue.test
def test_health(client):
    assert client.get("/health").ok
```

Users pick scope to express lifetime:

- `test`: fresh value per execution; best for mutable or isolated state
- `module`: one value per test file; best for medium-cost shared setup
- `run`: one value per active provider; best for expensive shared setup

Generator resources give users teardown without a second API:

```python
@rue.resource
def database():
    conn = connect()
    yield conn
    conn.close()
```

Setup files (`conftest.py`, `confrue_*.py`) let users provide shared resources
for a directory tree. Same-name providers may coexist; Rue selects the provider
nearest to the requesting test module.

Resources can cross subprocess boundaries. Syncable values are snapshotted
before a subprocess test runs, hydrated in the worker, and merged back into the
parent after execution. Non-syncable resources are resolved in the process that
needs them.

Specialized user-facing APIs are still resources: `@rue.metric` records quality
signals, `@rue.sut` wraps systems under test with tracing/output capture, and
the built-in `monkeypatch` resource scopes patches to the active Rue owner.

## Hooks

Resource hooks are registered through `resource(..., on_resolve=...,
on_injection=..., on_teardown=...)`. They run with `ResourceHookContext` bound,
so hook code can see the consumer spec, provider spec, and direct provider
dependencies.

- `on_resolve(value)` fires after direct dependencies are resolved and the
  selected factory returns or yields its first value. It runs before the value is
  committed to `ResourceStore`, once per `(ResourceSpec, ScopeOwner)`.
- `on_injection(value)` fires after a cached or newly materialized value is
  selected for a consumer, just before it is returned in kwargs. It can run many
  times for the same cached value and is skipped when `preload=True`.
- `on_teardown(value)` fires during owner teardown for generator resources,
  after the generator's post-yield cleanup path runs and before the value leaves
  the store.

## Sequence

```mermaid
sequenceDiagram
    autonumber
    participant User as Test/setup module
    participant Loader as TestLoader / AST rewrite
    participant Registry as ResourceRegistry
    participant Runner as Runner
    participant Resolver as DependencyResolver
    participant Store as ResourceStore
    participant Transfer as StateTransfer
    participant Test as LoadedTestDef

    Loader->>User: import setup + test modules
    User->>Registry: decorators register LoadedResourceDef
    Runner->>Registry: compile_graphs(execution_id -> consumer params)
    Registry-->>Runner: ResourceGraph(autouse, injections, dependencies)
    Runner->>Test: run_loaded_test(resolver)
    Test->>Resolver: resolve_graph_deps(graph, params, consumer_spec)
    Resolver->>Resolver: bind PatchStore
    loop autouse + injected resource roots
        Resolver->>Registry: get_definition(ResourceSpec)
        Resolver->>Store: owner = ScopeContext.current_owner(spec.scope)
        alt cached
            Store-->>Resolver: value
        else another task resolving
            Store-->>Resolver: wait_resolution(spec, owner)
        else first resolver
            Resolver->>Store: claim_resolution(spec, owner)
            Resolver->>Resolver: resolve direct dependencies first
            Resolver->>Resolver: call selected factory
            Resolver-->>Resolver: sync / async / generator value
            Resolver->>Store: record generator teardown if needed
            Resolver->>Store: commit_resolution(spec, owner, value)
        end
        Resolver-->>Test: kwarg value
    end
    Test->>User: call test function(**kwargs)
    alt subprocess backend
        Runner->>Resolver: preload shared graph deps
        Resolver->>Transfer: export_snapshot(execution_id)
        Transfer-->>Runner: StateSnapshot
        Runner->>Transfer: worker hydrate(snapshot)
        Transfer->>Resolver: resolve missing/opaque resources
        Transfer-->>Runner: update_since(snapshot)
        Runner->>Transfer: apply_update(snapshot, update)
    end
    Runner->>Resolver: teardown(Scope.TEST / MODULE / all)
    Resolver->>Resolver: close generator teardowns
    Resolver->>Store: clear(owner)
    Resolver->>Resolver: undo PatchStore handles
```

## API Map

| API | Role |
| --- | --- |
| `resource()` / `ResourceRegistry.register_resource()` | Register one provider function as a `LoadedResourceDef`. |
| `ResourceSpec` | Provider identity: locator plus `Scope`. |
| `ResourceGraph` | Per-execution concrete graph: autouse roots, injection roots, dependency edges, resolution order. |
| `DependencyResolver` | Runtime resolver, teardown owner, and patch-store binder. |
| `ResourceStore` | Cache, pending futures, teardown records, and sync graph per `ScopeOwner`. |
| `StateTransfer` | Snapshot/hydrate/update path for subprocess execution. |
| `ResourceHookContext` | Ambient metadata while resource hooks run. |

## Core Rules

- Registration happens while setup/test modules are imported; graph compilation
  happens after executable leaves and their params are known.
- Provider selection is concrete before execution: by requested name, allowed
  scope, and nearest provider directory to the consumer module.
- Wider scopes cannot depend on narrower scopes. The current rule is encoded by
  `Scope.dependency_scopes`.
- Runtime ownership is not the provider path. Values are cached under
  `ScopeContext.current_owner(spec.scope)`.
- Only the first resolver task materializes a `(ResourceSpec, ScopeOwner)`;
  concurrent callers wait on the pending future.
- `PatchStore` is bound for resolution and teardown so `monkeypatch` resources
  can register handles against the active resource owner.
- Shadow stores hydrate subprocess state and skip live teardown; the parent
  applies worker updates back onto visible live resources.
