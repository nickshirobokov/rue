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
- `rue.EnvVars` (re-exported via `rue.environment`) — the env-var overlay type.

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

Activation MUST bind this `Environment` as the active routing target for
the current context through dispatcher-owned `activate(env)` /
`deactivate(env)` APIs. The dispatcher owns the per-context activation
stack and its `ContextVar` tokens. Exit MUST pop the matching active
environment; empty-stack or out-of-order exits MUST raise `RuntimeError`.
Activation MUST NOT mutate process-global state
(`os.environ`, `os.getcwd()`); a per-context dispatcher set installed at
package import time virtualizes the chokepoint surface of
`os` / `builtins` / `io` so reads under an active env route to the
env's `vars` overlay and rebased `cwd`, while reads with no active env
fast-path to the real process state.

Activation MUST be concurrent-safe: two `__enter__` calls in different
async tasks (or other contexts) each see their own binding, with no
lock, deadlock, or `RuntimeError`. Nested activation in the same
context is supported via the token stack — the innermost `with` block
wins for routing; exiting it restores the next-outer binding.

Activation MUST NOT propagate the overlay to subprocesses spawned with
`env=None`: those inherit the real process environ (the C-level
`environ` is never modified). Subprocesses spawned with `env=os.environ`
(explicit) DO see the overlay because `os.environ` is itself routed.

The dispatched chokepoint set comprises `os.environ`, `os.environb`,
`os.putenv`, `os.unsetenv`, `os.getcwd`, `os.getcwdb`, `os.chdir`,
`os.fchdir`, `os.stat`, `os.lstat`, `os.access`, `os.scandir`,
`os.listdir`, `os.mkdir`, `os.rmdir`, `os.unlink` / `os.remove`,
`os.rename`, `os.replace`, `os.link`, `os.symlink`, `os.readlink`,
`os.chmod`, `os.chown`, `os.utime`, `os.truncate`, `os.open`,
`builtins.open`, `io.open`, plus the platform-conditional
`os.pathconf`, `os.statvfs`, `os.mkfifo`, `os.mknod`, `os.getxattr` /
`setxattr` / `listxattr` / `removexattr`, `os.chflags` / `lchflags`,
`os.fwalk`. Wrappers rebase relative path arguments under the active
env's `cwd`; absolute paths and `int` file descriptors pass through
unchanged. For CPython APIs where `None` means "use the current
directory" (`os.listdir(None)`, `os.scandir(None)`, and platform
`os.listxattr(None)`), the dispatcher MUST treat explicit `None` the
same as an omitted path and route it to the active `env.cwd`. C / Rust
extensions that bypass the Python `os` module continue to see
real-process state.

`os.putenv(key, value)` and `os.unsetenv(key)` MUST route to the active
env's `vars` overlay rather than mutating the C-level `environ`. This
preserves isolation: SUT code that calls `os.putenv` does not leak the
key into other tests' overlays or into child processes inherited from
the real environ. With no env active, both pass through to the real
implementations.

`os.chdir(p)` and `os.fchdir(fd)` under an active env MUST mutate only
`env._cwd` and MUST NOT call the real `os.chdir` / `os.fchdir`.
Relative `p` resolves against the current `env.cwd`; fd arguments
resolve through `/dev/fd/N`. The resolved target MUST lie under
`env.root` — escapes (absolute paths outside the sandbox, `..`
traversal past the root) MUST raise `ValueError`. This guarantees
`Environment.cwd` stays under `Environment.root` even when SUT code
uses the routed `os.chdir`. `Environment.chdir(p)` (the method) keeps
its root-relative + containment contract via `Environment.path()` and
is the user-facing validated mover.

`Environment.exec` MUST NOT require activation. It threads `cwd` and
`env` through `asyncio.create_subprocess_exec` directly, validating cwd
through `path()`, and applies the merge order:
`real os.environ if inherit_os else {}` → drop `vars.hidden` → apply
`vars.overrides` → apply caller `env=`. The "real os.environ" here is
the pre-dispatch `os._Environ` captured at install time, so the merge
composes overrides onto the parent process environ rather than onto
the already-routed view.

### Vars overlay

`EnvVars` is a `MutableMapping[str, str]` over the override layer
only. Lookups for keys that are not overridden MUST raise `KeyError`.
`unset(key)` masks a base value; `restore(key)` removes both the override
and the hide flag. `view(base)` returns a `MergedVarsView` — a live
`MutableMapping` of the overlay composed onto an arbitrary base — used by
the routers and by `Environment.exec` to compute the effective env.

`EnvVars` owns all string environment validation. Keys and values
MUST be `str`; non-string keys or values raise `TypeError("str expected,
not <type>")`. Empty keys raise `OSError(errno.EINVAL, "Invalid
argument")`. Keys containing `=` raise `ValueError("illegal environment
variable name")`. Embedded NUL bytes in keys or values raise
`ValueError("embedded null byte")`. `os.environb`, `os.putenv`, and
`os.unsetenv` dispatchers MUST decode byte inputs before calling
`EnvVars`, so the same validation path applies. Pickling MUST
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
tuple of `PathDelta` records. `baseline=None` means the checkpoint is based on
an empty directory. Each delta is one of three tagged variants:

- `FileDelta(path, mode, patch)` — `patch` is a bsdiff payload when bytes
  changed, or `None` for a mode-only change.
- `SymlinkDelta(path, target)` — the final symlink target string.
- `Deletion(path)` — a path that existed in the baseline and no longer does.

Directories are implied and are not tracked.

`Checkpoint.final_states` MUST be a property returning the fully-reconstructed
state of every live path as a read-only `Mapping[PurePosixPath, PathState]`,
where each value is a `FileState(path, mode, content)` or
`SymlinkState(path, target)`. The result MAY be memoized on the checkpoint
instance. Both variants expose a `content` attribute of type `bytes`: file
bytes for `FileState`, UTF-8-encoded target for `SymlinkState`.

`CheckpointDelta.added`, `CheckpointDelta.modified`, `CheckpointDelta.deleted`
are sorted tuples of `PurePosixPath`. `Checkpoint.compare(checkpoint)` MUST
derive these from both checkpoints' `final_states()`. Regular-file equality
uses final mode and final bytes. Symlink equality uses final target. File
content for changed paths is reconstructed on demand through the source
checkpoints — `CheckpointDelta` itself does not eagerly materialize
before/after byte maps.

`CheckpointDelta` MUST implement the standard collection protocol:

- `iter(delta)` yields every changed path (`added ∪ modified ∪ deleted`) in
  sorted order, exactly once each.
- `len(delta)` is the count of changed paths.
- `path in delta` accepts `str` or `PurePosixPath` and returns whether the path
  is in any of the three sets; any other type returns `False`.
- `bool(delta)` is `False` when there are no changes; `delta.empty` is preserved
  as the inverse property.

`CheckpointDelta(path)` MUST return a `FileDiff` for any path in
`added ∪ modified ∪ deleted` and MUST raise `PathNotInDiff` (a subclass of
`KeyError`) otherwise. On the returned `FileDiff`, the missing side
(before-state for added, after-state for deleted) MUST be `b""`. Symlink
"content" on either side MUST be the UTF-8-encoded target.

`FileDiff` exposes three views over its `before` / `after` bytes:

- `FileDiff.unified` MUST return `difflib.unified_diff` output as a single
  string, labelled with the file path on both sides.
- `FileDiff.words` MUST return a tuple of `(op, text)` pairs produced by
  `difflib.SequenceMatcher` over whitespace-delimited tokens, where `op` is
  one of `"="`, `"-"`, `"+"`. Replace opcodes MUST be split into a `"-"`
  followed by a `"+"` pair.
- `FileDiff.json` MUST return an RFC 6902 JSON Patch (list of operation
  dictionaries) computed via `jsonpatch.make_patch`, treating an empty side as
  JSON `null`.

Decoding errors on non-UTF-8 bytes (`unified`, `words`) and parse errors on
non-JSON bytes (`json`) MUST propagate to the caller. The tool does not paper
over malformed inputs.

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
