# smemo

Single-file PyPI library ("explicit session memoization"). All library code is
`smemo/__init__.py` (+ `smemo/py.typed`); tests are `tests/test_smemo.py`.

Maintainer- and machine-specific setup (virtualenv location, a private command
console, benchmarking conditions) lives in `AGENTS.local.md`, which is not
committed, so nothing below depends on it. To keep notes of your own that
OpenCode reads automatically, add them to a local `opencode.json` (also not
committed) under `instructions`; missing entries are simply skipped.

## Verifying changes

There is no CI and no pre-commit hook, so local verification is the only gate:

    PYTHONPATH=. pytest tests/test_smemo.py -q          # or: python -m pytest
    mypy --disallow-untyped-defs --warn-no-return --strict-optional -p smemo

- A bare `pytest` fails with `ModuleNotFoundError: No module named 'smemo'`: the
  package is normally not installed into the environment and there is no root
  `conftest.py`, so the source tree must be on `PYTHONPATH`.
- Type-check the package only (`-p smemo`). The same flags over `tests/` add noise
  that is not a problem: "Function is missing a return type annotation" on every
  untyped test helper (that flag is meant for the package), and 5 `attr-defined`
  errors (`session.getval` is a `Session` method while the helpers annotate the
  parameter as `BaseSession`). That is accepted as it stands; do not refactor
  working code to chase it. Only the `attr-defined` count is a fixed number; the
  untyped-def one grows with every test function added.
- `pylint smemo` is clean (10.00/10), though it is not wired into any menu. The
  no-op `BaseSession` stubs have docstring-only bodies, which is what makes pylint
  treat them as abstract; adding any statement to one, even `_ = func`, brings
  `unused-argument` warnings back for all its arguments.
- `requirements-dev.txt` is generated from `requirements-dev.in` and is
  gitignored. Edit the `.in` file, never the generated one.
- The suite is pure in-process (no services, fixtures or goldens) and runs in
  milliseconds. Its assertions pin exact call counts using counters stashed in
  the session (`session.putval([0], 'counter')`), i.e. they encode the
  memoization behavior itself - if a count changes, explain why rather than
  editing the number to match.

### Under Python 3.9

The floor is `requires-python >= 3.9` while the development environment is newer,
and no type checker can see the floor, so run the suite under 3.9 whenever a
change could depend on the interpreter version:

    PYTHONPATH=. uv run --no-project --python 3.9 --with pytest \
      pytest tests/test_smemo.py -q

Keep the code 3.9-compatible: no `match`, no post-3.9 stdlib APIs.

## Code notes

- **Typing style is pinned to 3.9.** Use builtin generics (`dict[str, Any]`) and
  `collections.abc.Callable` / `.Iterator` / `.Iterable`, but **keep
  `typing.Optional` / `typing.Union`**: PEP 604 `X | Y` needs either 3.10 or
  `from __future__ import annotations`, and the latter would break
  `typing.get_type_hints()` on the library's own annotations under 3.9. Do not
  "modernize" `Optional` to `X | None`.
- **Cache entries must be exact 2-tuples** `(value, exception)`, aliased as
  `ResType`. Do not turn it into a `NamedTuple` or any tuple subclass: measured
  with an interleaved A/B against the previous commit plus a byte-identical
  control, subclass instances cost ~2-4% on **every hit** of the arg-taking path,
  because CPython's tuple specializations require an exact tuple. `test_res_type`
  asserts `type(entry) is tuple`. The no-arg fast path is unaffected either way.
- **Parameters belonging to the machinery (`session`, `func`, `val`, `exc`) are
  positional-only (`/`).** This is load-bearing, not stylistic: without it a user
  keyword argument named `func` or `val` raised `TypeError: got multiple values
  for argument`. Since `/` already isolates them from the call's `**kwargs`, the
  names need no leading underscore - use plain `val`/`exc`. Underscores are for
  genuinely unused arguments only. `Session.putval`'s value argument is
  positional-only for the same reason, so a cache key may itself be `val=`;
  `test_putval_keys` pins that and `setcache(ret=, exc=)` deliberately stays
  keyword-taking because users pass those names as API.
- Consequently one limitation is inherent and documented in the README: a user
  keyword argument literally named `session` clashes with the session parameter of
  the function they decorated, and cannot be passed through.
- `MISSING` and `PICKLED` are named `_Sentinel` instances that pickle back to
  themselves. Compare with `is`, and do not replace them with `None` or `False`.
- Every decorator dispatches on `_no_arg(func)` (`len(signature.parameters) <= 1`).
  Session-only functions take a fast path (`_gc0_func` + `simple_get_cache` /
  `simple_pre_call` + `Session._simple_cache`) that does **not** forward
  args/kwargs and does **not** cache exceptions; anything else uses `_gc_func`.
  Adding or removing a parameter silently moves a function between the two paths.
- `_no_arg` is memoized in the weak-keyed `_NO_ARG`, because `_cache_store`
  and `invalidate` both ask it and `inspect.signature()` costs more than a
  whole cache miss (~16 us here against 1.4 us for a hit). Measured on the
  paths that pay: 0.23x on a miss, 0.02-0.08x on an invalidation. Retrieval
  never asks, and must not start to. Keep the memo weak-keyed - a plain dict
  is only marginally faster and would leak every function decorated at
  runtime - and keep both `TypeError` guards: the public `session.cache()`
  takes any callable, including one a weak reference cannot be made to, and
  `WeakKeyDictionary` raises `TypeError` on *lookup* for those, not only on
  insertion. `test_no_arg_memo`, `test_no_arg_memo_lifetime` and
  `test_no_weakref_callable` cover the answer, the lifetime and the trap.
- Cache keys and the process-global `PERSISTENT_FUNCS` / `PKEY_FUNCS` registries
  are keyed on the inner `_func` object, not the `functools.wraps`-copied public
  name. Preserve that identity.
- Cache control is expressed by passing a `BaseSession` stand-in *as the session
  argument* (`session.inv`, `session.callonly`, `session.setcache(...)`) so mypy
  checks the call. A `pre_call` returning `None` means "don't call, treat the
  result as `None`".
- Perf claims here need to reproduce across separate runs, ideally in both
  directions (add the change to old code *and* remove it from new code). A single
  run is not evidence even with an identical-code control: runtime-identical code
  has measured over 2% apart. See `AGENTS.local.md` for this machine's conditions.

## Versions and releases

`__version__` in `smemo/__init__.py` is the single source of truth; hatch reads it
by regex and `pyproject.toml` declares `dynamic = ["version"]` - never add a
version field there.

Releases go straight to `origin/master` (no PR flow): a release rewrites
`__version__`, commits `Set version number to <ver>`, tags `rel-<ver>`, pushes
`master` with the tag, uploads the artifacts to PyPI, and archives them into
`dist/archive/`. Every part of that is irreversible - never do any of it unless
explicitly asked.

## README examples

`README.md` is the design doc and its snippets are all executable prose blocks
(indented, not fenced). They were checked to run as written on 3.9 and 3.12, which
corrected: `cache_val` to the real `Session.cache`, `with session.nocache:` to
`session.nocache()`, `setcache(exception=...)` to the real parameter `exc=`, and
`typing.Dict[str, float]` to `dict[str, float]`. The prose reuses the name `efib`
for two different example functions, so an extracted snippet may need the
definition that matches its argument list. Re-run any snippet you touch; docs here
have drifted before.
