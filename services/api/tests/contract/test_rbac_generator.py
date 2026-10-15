"""Tests for `tools/rbac/generate.py` (E09-T03).

Runs the generator as a subprocess (same convention as
`services/api/tests/contract/test_generate_protocol_models.py`) so the test
exercises the exact code path CI's `generated-code` check runs.

These tests never write inside the checkout (C-13.7): the write path is
exercised via `--out-dir <tmp_path>`, and the committed artefacts are only
ever *read*. (A previous version regenerated in place and "restored" with a
platform-default `write_text`, which rewrote the committed LF files as CRLF
on Windows — a dirty tree after every `pytest` run.)

Nor do they touch process-wide state: the enum check executes its own copy of
the generated module under a private name instead of reloading the shared
`candleviewer.auth.generated_permissions` (a reload splits `Permission` and
`Scope` into two classes for everything that imports them afterwards), and an
autouse fixture fails any test in this module that leaves that shared module,
its two classes or `sys.modules` different from how they were collected (#2554).
"""

from __future__ import annotations

import importlib.util
import inspect
import json
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

import pytest

import candleviewer.auth.generated_permissions as shared_enum_module
from candleviewer.auth.generated_permissions import Permission, Scope

REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPT = REPO_ROOT / "tools" / "rbac" / "generate.py"
ENUM_PATH = REPO_ROOT / "services" / "api" / "candleviewer" / "auth" / "generated_permissions.py"
SEED_PATH = REPO_ROOT / "services" / "api" / "candleviewer" / "auth" / "rbac_seed.json"
SHARED_ENUM_MODULE = "candleviewer.auth.generated_permissions"
PRIVATE_ENUM_MODULE = "_cv_generated_permissions_under_test"


def _run(*extra_args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 — fixed argv, no shell, trusted script under test
        [sys.executable, str(SCRIPT), *extra_args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def _read_bytes(path: Path) -> bytes:
    return path.read_bytes()


def _load_generated_enum_privately() -> ModuleType:
    """The generated enum file executed as its own module object under a private name.

    Never `importlib.reload` the shared module for this. A reload re-runs the file inside the
    existing module object, so later `from candleviewer.auth.generated_permissions import
    Permission, Scope` get new classes while `ws/topics`, `ws/sequencing` and `auth/scopes` keep
    the old ones. `StrEnum` members still compare equal across the two classes, but `is` and
    `isinstance` do not, so any suite that runs after the reload would depend on the test order
    (C-13.7). The copy is not registered in `sys.modules`, so nothing can import it or find it
    left behind.
    """
    spec = importlib.util.spec_from_file_location(PRIVATE_ENUM_MODULE, ENUM_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _assert_shared_enum_untouched() -> None:
    """The shared generated enum is still what every other importer captured at collection time.

    `shared_enum_module`, `Permission` and `Scope` are imported at the top of this file, once,
    while pytest collects it, the same way `ws/topics.py` binds them. An in-place
    `importlib.reload` keeps the module object but rebuilds its classes, so the names held here
    stop matching the module's attributes.
    """
    assert sys.modules[SHARED_ENUM_MODULE] is shared_enum_module, "sys.modules entry replaced"
    assert shared_enum_module.Permission is Permission, "Permission was rebuilt (in-place reload?)"
    assert shared_enum_module.Scope is Scope, "Scope was rebuilt (in-place reload?)"
    assert PRIVATE_ENUM_MODULE not in sys.modules, "private copy left in sys.modules"


@pytest.fixture(autouse=True)
def _shared_generated_enum_is_left_alone() -> Iterator[None]:
    """Fail whichever test leaves the shared generated enum changed, at any fixture scope.

    Checking the loader alone is not enough: a test that goes back to `importlib.reload` still
    passes every assertion in its own body, so the shared state is checked after every test.
    """
    yield
    _assert_shared_enum_untouched()


def _start_guard() -> Iterator[None]:
    """The autouse guard's own body, run by hand instead of by pytest.

    The returned generator is already set up. The caller's `next()` runs the teardown half that
    pytest would run after a test, so a test can show that the guard fails when the enum is split.
    """
    guard: Iterator[None] = inspect.unwrap(_shared_generated_enum_is_left_alone)()
    next(guard)
    return guard


def test_check_passes_against_committed_output() -> None:
    """The committed `generated_permissions.py`/`rbac_seed.json` are exactly
    what the generator produces today — CI's `generated-code` job runs this
    exact invocation."""
    result = _run("--check")
    assert result.returncode == 0, result.stderr


def test_committed_artefacts_round_trip_byte_identical(tmp_path: Path) -> None:
    """Regenerating into a scratch directory reproduces the committed files
    byte-for-byte (content *and* LF line endings), so running the generator
    for real never produces a diff."""
    result = _run("--out-dir", str(tmp_path))
    assert result.returncode == 0, result.stderr

    for committed in (ENUM_PATH, SEED_PATH):
        generated = tmp_path / committed.name
        assert generated.is_file()
        assert _read_bytes(generated) == _read_bytes(committed), committed.name
        assert b"\r" not in _read_bytes(generated), f"{committed.name} must be LF-only"


def test_regenerating_twice_is_byte_identical(tmp_path: Path) -> None:
    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"

    first = _run("--out-dir", str(first_dir))
    assert first.returncode == 0, first.stderr
    second = _run("--out-dir", str(second_dir))
    assert second.returncode == 0, second.stderr

    for name in (ENUM_PATH.name, SEED_PATH.name):
        assert _read_bytes(first_dir / name) == _read_bytes(second_dir / name)


def test_generator_does_not_touch_the_checkout(tmp_path: Path) -> None:
    """Explicit no-side-effect guard (C-13.7): after a `--out-dir` run the
    committed files have the same bytes and mtimes as before."""
    before = {p: (_read_bytes(p), p.stat().st_mtime_ns) for p in (ENUM_PATH, SEED_PATH)}
    result = _run("--out-dir", str(tmp_path))
    assert result.returncode == 0, result.stderr
    after = {p: (_read_bytes(p), p.stat().st_mtime_ns) for p in (ENUM_PATH, SEED_PATH)}
    assert before == after


def test_generated_enum_imports_cleanly() -> None:
    generated = _load_generated_enum_privately()
    seed = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    assert len(list(generated.Permission)) == len(seed["permissions"])
    assert {s.value for s in generated.Scope} == {"none", "self", "granted_accounts"}


def test_private_load_of_generated_enum_builds_classes_independent_of_the_shared_ones() -> None:
    generated = _load_generated_enum_privately()

    assert generated.Permission is not shared_enum_module.Permission
    assert generated.Scope is not shared_enum_module.Scope
    assert [(m.name, m.value) for m in generated.Permission] == [
        (m.name, m.value) for m in shared_enum_module.Permission
    ]
    assert [(m.name, m.value) for m in generated.Scope] == [
        (m.name, m.value) for m in shared_enum_module.Scope
    ]


# Tests of the guard fixture above. The four scenario tests break the shared enum on purpose,
# through `monkeypatch`, and run the guard's body by hand to prove it flags each way the original
# `importlib.reload` could split the enum. The patch is undone before the fixture's own teardown:
# autouse fixtures are set up first, so they are torn down last.


def test_guard_is_active_for_every_test_in_this_module(request: pytest.FixtureRequest) -> None:
    assert "_shared_generated_enum_is_left_alone" in request.fixturenames


def test_guard_flags_a_rebuilt_permission_class(monkeypatch: pytest.MonkeyPatch) -> None:
    guard = _start_guard()
    rebuilt = _load_generated_enum_privately()
    monkeypatch.setattr(shared_enum_module, "Permission", rebuilt.Permission)

    with pytest.raises(AssertionError, match="Permission was rebuilt"):
        next(guard)


def test_guard_flags_a_rebuilt_scope_class(monkeypatch: pytest.MonkeyPatch) -> None:
    guard = _start_guard()
    rebuilt = _load_generated_enum_privately()
    monkeypatch.setattr(shared_enum_module, "Scope", rebuilt.Scope)

    with pytest.raises(AssertionError, match="Scope was rebuilt"):
        next(guard)


def test_guard_flags_a_replaced_shared_sys_modules_entry(monkeypatch: pytest.MonkeyPatch) -> None:
    guard = _start_guard()
    replacement = _load_generated_enum_privately()
    monkeypatch.setitem(sys.modules, SHARED_ENUM_MODULE, replacement)

    with pytest.raises(AssertionError, match=r"sys\.modules entry replaced"):
        next(guard)


def test_guard_flags_a_private_copy_left_in_sys_modules(monkeypatch: pytest.MonkeyPatch) -> None:
    guard = _start_guard()
    leftover = _load_generated_enum_privately()
    monkeypatch.setitem(sys.modules, PRIVATE_ENUM_MODULE, leftover)

    with pytest.raises(AssertionError, match=r"private copy left in sys\.modules"):
        next(guard)
