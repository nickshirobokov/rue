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
- A diff API that reports what the consumer test added/modified/deleted.

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
    environment.set_baseline()
    with environment:
        await my_agent.run()
    assert "output.txt" in environment.diff.added


@rue.resource(scope="module")
async def docs(environment):
    await environment.load(rue.env.git(
        "https://github.com/fastapi/fastapi",
        ref="0.115.0",
        subpath="docs_src",
    ))
    environment.set_baseline()
    yield environment
```

The public symbols are:

- `rue.Environment` — the handle type.
- `rue.env.empty()` / `rue.env.dir(path)` / `rue.env.git(url, ref=..., subpath=...)` —
  source constructors; pass results to `Environment.load(...)`.
- `Environment.set_baseline()` — explicit diff baseline capture after setup.
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

After materialization `load` MUST reset `cwd` to `root` and clear the
explicit diff baseline. `load` MUST NOT capture a diff baseline.

### Diff

`Environment.set_baseline()` MUST capture the current filesystem state under
`Environment.root`. `environment.diff` MUST report changes between that
explicit baseline and the current filesystem. This is intentionally explicit:
users may populate fixtures with `load(...)`, `path(...).write_text(...)`,
plain `Path` operations, or custom resources before deciding which state the
system under test should be compared against.

`Environment.load(source)`, resource injection, and environment construction
MUST NOT set the diff baseline. If `environment.diff` or
`environment.baseline` is read before `set_baseline()` has been called, Rue
MUST raise `RuntimeError`.

`Diff.added`, `Diff.modified`, `Diff.deleted` are sorted tuples of
`PurePosixPath`. A path is considered modified when size, mode, or
symlink target differ; ties on `(size, mtime_ns)` are broken with a
BLAKE2b content hash so timestamps cannot lie.

## Storage Layout

```
.rue/
  environment-cache/<source-fingerprint>/    # content-addressed source materializations
  environment-run/<suite-uuid>/
    lock                                      # advisory lock held by parent for the suite lifetime
    suite/<owner-key>/<process-tag>/
    module/<owner-key>/<process-tag>/
    test/<owner-key>/<process-tag>/
```

`<process-tag>` is `main` for the parent process and `p<pid>` for worker
processes, so a worker's reflink-clone target never collides with the
parent's live root. `<owner-key>` is a deterministic BLAKE2b digest of
`(scope, suite_execution_id, module_path | test_execution_id)` so the
same logical owner always lands at the same path within one process.

`EnvironmentStorage.allocate` is cheap: a single `mkdir`. The parent
acquires `flock(LOCK_EX | LOCK_NB)` on `lock` once per suite; workers
skip the lock because the parent already holds it.

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
registration. The wire payload contains no file bytes parent → worker;
worker → parent ships only changed file content.

| Direction | Method | Content |
| --- | --- | --- |
| Parent → worker | `get_sync_state()` | `parent_root`, sync baseline manifest, explicit diff baseline manifest, vars, cwd. |
| Worker hydrate | `from_sync_state(state)` | Reflink-clones `parent_root` into the worker's root, applies vars overlay. |
| Worker → parent | `get_sync_state()` | `deltas` computed against the baseline manifest captured during hydrate. |
| Parent merge | `merge_sync_states(baseline, update)` | Applies `update.deltas` to the parent root in place. |

For `Scope.TEST` envs the resolver short-circuits at `get_snapshot`, so
test-scope environments never sync; their `apply_transfer()` is a no-op
when the resolver receives unmatched test-scope state from a worker.

Reflink-clones use `cp -c -R` on Darwin (APFS clonefile, O(1)),
`cp --reflink=auto -r` on Linux, and `shutil.copytree(symlinks=True)`
otherwise. The strategy is detected once at module import.

## Builtin Registration

For every `Scope`, `register_builtin_resources` registers an
async-generator factory that:

1. Reads `SUITE_EXECUTION_CONTEXT` and the current owner.
2. Calls `EnvironmentStorage.allocate(suite_id, owner, process_kind=...)`.
3. `yield`s an `Environment._build(root=..., scope=...)`.
4. Calls `EnvironmentStorage.release(root)` in `finally`.

`on_resolve` stamps the provider spec onto the env (telemetry hook). There is
no injection-time diff baseline capture; consumers call `set_baseline()`
explicitly. The factory is intentionally cheap because subprocess workers
re-run it.
