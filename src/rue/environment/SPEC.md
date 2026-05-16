# Environment Resource SPEC

**Status:** Draft
**Intended use:** Normative contract for Rue's `environment` builtin.

## Why This Exists

Rue tests AI agents that touch the real filesystem: they call `open()`,
`Path.write_text()`, `os.environ["OPENAI_API_KEY"]`, run subprocesses, and
expect the host machine to behave like a workspace. Real isolation requires
a sandbox per test (or per scope) plus a way to bind the running Python
process to that sandbox so agent code that knows nothing about Rue still
lands inside it.

`environment` is a builtin DI resource (like `monkeypatch`) that resolves to
a `rue.Environment` handle. The handle owns:

- A scoped on-disk root.
- An `os.environ` overlay that can be activated with `with environment:`.
- A default cwd inside the root.
- An async subprocess helper (`environment.exec`).
- A `Source` loader for materializing fixtures from empty / dir / git.
- A stateless checkpoint API for explicit filesystem comparisons.

The key words **MUST**, **MUST NOT**, **SHOULD**, **SHOULD NOT**, and
**MAY** are normative.

## Public Surface

```python
import rue

@rue.test
async def test_agent(environment: rue.Environment):
    environment.vars["OPENAI_API_KEY"] = "test-key"
    await environment.load(rue.env.dir("fixtures/workspace"))
    environment.path("input.txt").write_text("seed")
    before = environment.get_checkpoint()
    with environment:
        await my_agent.run()
    diff = before.compare(environment.get_checkpoint())
    assert "output.txt" in {path.name for path in diff.added}


@rue.resource(scope="module")
async def docs(environment):
    await environment.load(rue.env.git(
        "https://github.com/fastapi/fastapi",
        ref="0.115.0",
        subpath="docs_src",
    ))
    yield environment, environment.get_checkpoint()
```

The public symbols are:

- `rue.Environment` — the handle type.
- `rue.env.empty()` / `rue.env.dir(path)` / `rue.env.git(url, ref=..., subpath=...)` —
  source constructors; pass results to `Environment.load(...)`.
- `Environment.get_checkpoint()` — capture a fresh filesystem checkpoint.
- `Checkpoint.compare(checkpoint)` — compare two user-owned checkpoints.
- `rue.EnvironmentVars` (re-exported via `rue.environment`) — the env-var overlay type.

There is no new decorator. Custom env shapers use `@rue.resource`.

## `Environment` Contract

### Path containment

`Environment.path(p)` is the only sanctioned write entrypoint Rue blesses
for sandbox-relative I/O. It MUST resolve `p` against `Environment.root`
and MUST raise `ValueError` if the resolved path escapes the root
(absolute paths, `..` traversal, and symlinks pointing outside all count).
Callers then use plain `Path.write_text()`, `Path.mkdir()`, etc. on the
returned path.

`Environment.cwd` MUST always lie under `Environment.root`. `chdir(p)`
delegates to `path(p)` and MUST reject non-directory targets.

### Activation (`with environment:`)

Activation MUST snapshot `os.environ` and `os.getcwd()`, apply
`vars.merged(os.environ)` onto `os.environ`, and `os.chdir(self.cwd)`.
Exit MUST restore both.

Activation MUST be exclusive across the process. A second `__enter__`
attempt — re-entrant or from another thread — MUST raise `RuntimeError`
immediately. The implementation uses a non-blocking `threading.Lock`
acquire so callers never silently deadlock; "serializes via the lock"
holds only across actually-disjoint activation windows.

`Environment.exec` MUST NOT require activation. It threads `cwd` and
`env` through `asyncio.create_subprocess_exec` directly, validating cwd
through `path()`, and applies the merge order:
`os.environ if inherit_os else {}` → drop `vars.hidden` → apply
`vars.overrides` → apply caller `env=`.

### Vars overlay

`EnvironmentVars` is a `MutableMapping[str, str]` over the override layer
only. Lookups for keys that are not overridden MUST raise `KeyError`.
`unset(key)` masks a base value; `restore(key)` removes both the override
and the hide flag; `merged(base)` returns a fresh dict. Pickling MUST
preserve `_overrides` and `_hidden`.

### Sources

`Environment.load(source)` MUST materialize through
`.rue/environment-cache/<fingerprint>/` so concurrent loads of the same
source dedupe. Cache acquisition uses `fcntl.flock` wrapped in
`asyncio.to_thread` so other coroutines stay responsive.

- `EmptySource` materializes an empty directory.
- `DirSource(path)` clones the directory's contents.
- `GitSource(url, ref, subpath=None)` `git clone --depth 1 --branch <ref>`
  into a temp dir, drops `.git`, narrows by `subpath`, then clones the
  result into the cache.

After materialization `load` MUST remember the content-addressed cache
directory it installed from and reset `cwd` to `root`. `load` MUST NOT
capture or store a checkpoint.

Before the first `load(...)`, `Environment.reset()` MUST empty
`Environment.root`. After `load(...)`, `Environment.reset()` MUST restore
`Environment.root` from the remembered cache directory. In both cases it
resets `cwd` to `root`. It MUST NOT invalidate or mutate the source cache.

### Checkpoints And Diffs

`Environment.get_checkpoint()` MUST capture the current filesystem state under
`Environment.root` and return it to the caller. It MUST NOT store that
checkpoint on `Environment` or mutate any environment state. Users may populate
fixtures with `load(...)`, `path(...).write_text(...)`, plain `Path`
operations, or custom resources before deciding which user-owned checkpoint the
system under test should be compared against.

`Checkpoint.compare(checkpoint)` MUST report changes from `self` to
`checkpoint`. Direction is intentionally explicit:
`before.compare(after)` reports what was added, modified, or deleted in
`after` relative to `before`.

`Checkpoint` stores an optional immutable `baseline` directory and a sorted
tuple of `UpdatedPath` records. `baseline=None` means the checkpoint is based on
an empty directory. Updated records include only changed regular files and
symlinks; directories are implied and are not tracked. Regular-file updates
store the final mode and a bsdiff patch when file bytes changed. Symlink
updates store the final target string. Deletions store no payload.

`Diff.added`, `Diff.modified`, `Diff.deleted` are sorted tuples of
`PurePosixPath`. `Checkpoint.compare(checkpoint)` MUST reconstruct both final
path states from `baseline + updated_paths` and derive status from those final
states. Regular-file equality uses final mode and final bytes. Symlink equality
uses final target.

## Storage Layout

```
.rue/
  environment-cache/<source-fingerprint>/    # content-addressed source materializations
  environment-run/<suite-uuid>/
    lock                                      # advisory lock held by parent for the suite lifetime
    suite/<owner-key>/
    module/<owner-key>/
    test/<owner-key>/
```

`<owner-key>` is a deterministic BLAKE2b digest of
`(scope, suite_execution_id, module_path | test_execution_id)` so the
same logical owner always lands at the same path in every process.
Parent and worker processes share the same real files for module/suite
environment scopes. If tests race on shared environment files, that is user
test design, not Rue isolation behavior. Users who want isolated files use a
test-scoped environment resource.

`EnvironmentStorage.allocate` is cheap: a single `mkdir`. The parent
acquires `flock(LOCK_EX | LOCK_NB)` on `lock` once per suite; workers
skip the lock because the parent already holds it. Allocation MUST NOT
remove an existing environment root; only explicit `Environment.reset()`,
`Environment.load(...)`, or final suite cleanup clear environment files.

`EnvironmentStorage.gc_stale()` runs at the start of every parent
`SuiteContext.__enter__`. It walks `environment-run/<*>/` and removes any
suite directory whose `lock` file can be acquired with
`LOCK_EX | LOCK_NB`. Suites that the current process owns are skipped.
Race-free, time-independent, no heuristics about clock skew.

`EnvironmentStorage.release_suite` runs at the end of the parent
`SuiteContext.__exit__`, releases the suite lock, and removes the suite
directory.

## Subprocess Transfer

`Environment` is registered with `subprocess_sync=True` and implements
the `SyncableResource[EnvironmentSyncState]` protocol via virtual ABC
registration. Environment files and source cache are shared by path, so the
wire payload contains no file bytes and no file deltas. It only carries
process-local object state: root path, environment variable overlay, and cwd.

| Direction | Method | Content |
| --- | --- | --- |
| Parent → worker | `get_sync_state()` | `root`, vars, cwd. |
| Worker hydrate | `from_sync_state(state)` | Points the worker handle at `root`, applies vars/cwd. |
| Worker → parent | `get_sync_state()` | Updated vars/cwd. |
| Parent merge | `merge_sync_states(baseline, update)` | Replaces vars/cwd from the worker update. |

For `Scope.TEST` envs the resolver short-circuits at `get_snapshot`, so
test-scope environments never sync; their `apply_transfer()` is a no-op
when the resolver receives unmatched test-scope state from a worker.

The parent keeps ownership of module/suite environment roots. Worker
teardown MUST NOT release borrowed module/suite roots; parent suite cleanup
removes the run directory.

## Builtin Registration

For every `Scope`, `register_builtin_resources` registers an
async-generator factory that:

1. Reads `SUITE_EXECUTION_CONTEXT` and the current owner.
2. Calls `EnvironmentStorage.allocate(suite_id, owner, process_kind=...)`.
3. `yield`s an `Environment(root=..., scope=...)`.
4. Calls `EnvironmentStorage.release(root)` in `finally`, except for borrowed
   module/suite roots inside test subprocesses.

There is no injection-time checkpoint capture, observability hook, or hidden
diff state. Consumers call `get_checkpoint()` explicitly. The factory is
intentionally cheap because subprocess workers re-run it.
