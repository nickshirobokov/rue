# Resource DI SPEC

**Status:** Draft
**Intended use:** Short map of Rue's dependency injection runtime

Rue resources are named providers selected at graph-compile time and owned at
runtime by `ScopeOwner`. Resolution returns kwargs for a test or hook, caches
created values by scope owner, and tears generator resources down when that
owner ends.

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
    participant Hooks as ResourceHookContext
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
            Resolver->>Hooks: on_resolve(value)
            Resolver->>Store: commit_resolution(spec, owner, value)
        end
        Resolver->>Hooks: on_injection(value)
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
    Resolver->>Hooks: generator close + on_teardown(value)
    Resolver->>Store: clear(owner)
    Resolver->>Resolver: undo PatchStore handles
```

## API Map

| API | Role |
| --- | --- |
| `resource()` / `ResourceRegistry.register_resource()` | Register one provider function as a `LoadedResourceDef`. |
| `ResourceSpec` | Provider identity: locator plus `Scope`. |
| `ResourceGraph` | Per-execution concrete graph: autouse roots, injection roots, dependency edges, resolution order. |
| `DependencyResolver` | Runtime resolver, hook runner, teardown owner, and patch-store binder. |
| `ResourceStore` | Cache, pending futures, teardown records, and sync graph per `ScopeOwner`. |
| `StateTransfer` | Snapshot/hydrate/update path for subprocess execution. |
| `ResourceHookContext` | Ambient metadata for `on_resolve`, `on_injection`, and `on_teardown`. |

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
- `on_resolve` runs once for a freshly created value. `on_injection` runs every
  time the cached value is delivered to a consumer. `on_teardown` runs after the
  generator cleanup path for that owner.
- `PatchStore` is bound for resolution and teardown so `monkeypatch` resources
  can register handles against the active resource owner.
- Shadow stores hydrate subprocess state and skip live teardown; the parent
  applies worker updates back onto visible live resources.
