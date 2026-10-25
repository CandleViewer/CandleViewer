"""`@audited` / `@audit_exempt` (E42-X03, decision D1; C-2.9, SR-060): each declaration is checked
at import, changes nothing at run time, and every public method of every admin class carries one.
The last is the run-time twin of Semgrep's `cv-admin-mutation-audited`, which a file with PEP 695
generics can blind (X03-F4)."""

from __future__ import annotations

import ast
import importlib
import inspect
import pkgutil
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from functools import cached_property
from pathlib import Path
from typing import Any, Protocol

import pytest

import candleviewer.admin
from candleviewer.admin.audited import (
    EXEMPT_REASONS,
    AuditDeclaration,
    audit_exempt,
    audited,
    declaration,
)
from candleviewer.audit.actions import AUDIT_ACTIONS, UnknownAuditAction

#: `typing.Protocol` as a plain object: a class lists it among its bases to be one.
_PROTOCOL: object = Protocol


def test_audited_tags_and_returns_the_same_function() -> None:
    async def disable() -> None: ...

    assert audited("users.disable", "rbac.denied")(disable) is disable
    assert declaration(disable) == AuditDeclaration(actions=("users.disable", "rbac.denied"))


def test_audit_exempt_tags_and_returns_the_same_function() -> None:
    def page() -> list[str]:
        return []

    assert audit_exempt("read")(page) is page
    assert declaration(page) == AuditDeclaration(exempt="read")
    assert page() == []


@pytest.mark.parametrize("action", ["users.disabled", "Users.Disable", "users", ""])
def test_an_unregistered_or_malformed_action_fails_at_declaration(action: str) -> None:
    with pytest.raises(UnknownAuditAction):
        audited("users.disable", action)


@pytest.mark.parametrize("reason", ["", "  ", "reads", "TODO", "n/a"])
def test_a_reason_outside_the_vocabulary_fails_at_declaration(reason: str) -> None:
    unchecked: Any = reason  # a typo the type checker would also refuse
    with pytest.raises(ValueError, match="not one of"):
        audit_exempt(unchecked)


def test_a_function_is_declared_once() -> None:
    def replace() -> None: ...

    audited("users.access_change")(replace)
    with pytest.raises(TypeError, match="declared twice"):
        audit_exempt("read")(replace)


def test_a_declaration_above_a_property_is_refused() -> None:
    def engaged(self: object) -> bool:
        return True

    unchecked: Any = property(engaged)
    with pytest.raises(TypeError, match="directly above its def"):
        audit_exempt("read")(unchecked)


def test_declaration_reads_through_every_wrapper_a_method_can_have() -> None:
    class Service:
        @staticmethod
        @audit_exempt("read")
        def parse(text: str) -> int:
            return len(text)

        @classmethod
        @audit_exempt("wiring")
        def default(cls) -> object:
            return cls()

        @property
        @audit_exempt("read")
        def engaged(self) -> bool:
            return True

        @cached_property
        @audit_exempt("read")
        def registry(self) -> dict[str, str]:
            return {}

        @asynccontextmanager
        @audit_exempt("caller_audits")
        async def serialized(self) -> AsyncIterator[None]:
            yield

    members = vars(Service)
    assert declaration(members["parse"]) == AuditDeclaration(exempt="read")
    assert declaration(members["default"]) == AuditDeclaration(exempt="wiring")
    assert declaration(members["engaged"]) == AuditDeclaration(exempt="read")
    assert declaration(members["registry"]) == AuditDeclaration(exempt="read")
    assert declaration(members["serialized"]) == AuditDeclaration(exempt="caller_audits")
    assert declaration(object()) is None


def _admin_classes() -> Iterator[type]:
    """Every class an admin module defines at its top level or inside such a class, once (a
    module may also name one under an alias)."""
    seen: set[type] = set()

    def inner(cls: type) -> Iterator[type]:
        if cls in seen:
            return
        seen.add(cls)
        yield cls
        for member in vars(cls).values():
            if inspect.isclass(member) and member.__qualname__.startswith(cls.__qualname__ + "."):
                yield from inner(member)

    prefix = candleviewer.admin.__name__ + "."
    for info in pkgutil.walk_packages(candleviewer.admin.__path__, prefix):
        module = importlib.import_module(info.name)
        for member in vars(module).values():
            if inspect.isclass(member) and member.__module__ == module.__name__:
                yield from inner(member)


def _public_methods(cls: type) -> Iterator[tuple[str, object]]:
    """The members `cv-admin-mutation-audited` reads: a public staticmethod, or a public `def`
    taking `self` or `cls` (a classmethod's included)."""
    for name, member in vars(cls).items():
        if name.startswith("_"):
            continue
        if isinstance(member, staticmethod):
            yield name, member
            continue
        fn: object = member.fget if isinstance(member, property) else member
        fn = fn.func if isinstance(fn, cached_property) else fn
        fn = getattr(cls, name) if isinstance(fn, classmethod) else fn  # bound: reads through
        if not (inspect.isfunction(fn) or inspect.ismethod(fn)):  # a value, a nested class
            continue
        params = list(inspect.signature(fn).parameters)
        if inspect.ismethod(fn) or params[:1] in (["self"], ["cls"]):
            yield name, member


class _Sample:
    """Every kind of member the sweep must tell apart."""

    LIMIT = 3  # a value, not a method

    @staticmethod
    def build() -> None: ...

    @classmethod
    def default(cls) -> None: ...

    def act(self) -> None: ...

    @property
    def size(self) -> int:
        return 0

    @cached_property
    def total(self) -> int:
        return 0

    def _hidden(self) -> None: ...


def test_the_sweep_yields_exactly_the_public_methods() -> None:
    assert [name for name, _ in _public_methods(_Sample)] == [
        "build",
        "default",
        "act",
        "size",
        "total",
    ]


def test_every_public_method_of_an_admin_class_is_declared() -> None:
    checked, missing = 0, []
    for cls in _admin_classes():
        if any(base is _PROTOCOL for base in cls.__bases__):
            continue
        for name, member in _public_methods(cls):
            checked += 1
            found = declaration(member)
            if found is None:
                missing.append(f"{cls.__module__}.{cls.__qualname__}.{name}")
                continue
            assert set(found.actions) <= AUDIT_ACTIONS
            assert bool(found.actions) != (found.exempt in EXEMPT_REASONS)
    assert checked > 0
    assert missing == []


@pytest.mark.parametrize(
    ("module", "method", "actions"),
    [
        ("user_disable", "UserDisableService.disable", {"users.disable", "users.invite_revoked"}),
        ("account_access", "AccountAccessService.replace", {"users.access_change"}),
        ("flags.writes", "FlagWriter.set", {"flags.change", "auth.step_up_mismatch"}),
        ("backups.restore", "RestoreGuard.admit", {"backup.restore"}),
        ("backups.deletion", "BackupDeletion.delete", {"backup.deleted"}),
        ("backups.downloads", "BackupDownloads.fetch", {"backup.downloaded"}),
        ("backups.runs", "BackupRuns.start", {"backup.run"}),
        ("backups.verify", "BackupVerifications.start", {"backup.verified"}),
        ("ops.incidents", "AdminIncidentsService.acknowledge", {"incident.acknowledged"}),
        ("breakglass", "BreakGlassFlow.run", {"auth.break_glass_reset"}),
        ("bootstrap_owner", "BootstrapOwnerFlow.run", {"auth.bootstrap_owner_invited"}),
        ("view_as", "ViewAsService.start", {"admin.view_as_started", "admin.view_as_ended"}),
        ("view_as", "ViewAsService.end", {"admin.view_as_ended"}),
        ("view_as", "ViewAsService.evaluate", {"admin.view_as_ended"}),
        ("view_as", "ViewAsService.leave", {"admin.view_as_ended"}),
        ("view_as", "ViewAsService.write_end_record", {"admin.view_as_ended"}),
        ("view_as", "ViewAsService.on_roles_changed", {"admin.view_as_ended"}),
        ("view_as_sweeper", "ViewAsSweeper.tick", {"admin.view_as_ended"}),
        (
            "service",
            "AdminService.rewrap_kek",
            {"security.kek_rotated", "security.credential_rewrapped"},
        ),
    ],
)
def test_the_admin_mutations_declare_the_records_they_write(
    module: str, method: str, actions: set[str]
) -> None:
    owner: Any = importlib.import_module(f"candleviewer.admin.{module}")
    for part in method.split("."):
        owner = vars(owner)[part] if inspect.isclass(owner) else getattr(owner, part)
    found = declaration(owner)
    assert found is not None
    assert actions <= set(found.actions)


def test_contract_unrecorded_is_declared_only_where_a_review_allowed_it() -> None:
    """A write the contract records nothing for is an exemption from C-2.9, so each new use is a
    reviewed edit of this set (C-10.2), not a declaration that passes on its own (S4-SEC-09). It
    is empty: the one use, `ViewAsService.clear`, never had a caller and went (#3085 S14)."""
    found = {
        (cls.__module__, f"{cls.__qualname__}.{name}")
        for cls in _admin_classes()
        for name, member in _public_methods(cls)
        if (declared := declaration(member)) is not None
        and declared.exempt == "contract_unrecorded"
    }
    assert found == set()


_PACKAGE = Path(candleviewer.__file__).resolve().parent


def _written_literals() -> set[str]:
    """Every string constant under `candleviewer/` outside the action registry, migrations,
    generated code and the `@audited(...)` declarations themselves."""
    found: set[str] = set()
    for path in _PACKAGE.rglob("*.py"):
        parts = set(path.relative_to(_PACKAGE).parts)
        if path == _PACKAGE / "audit" / "actions.py" or {"migrations", "_generated"} & parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        declared = {
            id(node)
            for call in ast.walk(tree)
            if isinstance(call, ast.Call)
            and isinstance(call.func, ast.Name)
            and call.func.id == "audited"
            for node in ast.walk(call)
        }
        found |= {
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in declared
        }
    return found


def test_every_declared_action_is_written_somewhere() -> None:
    """Each action an `@audited` names occurs as a literal outside the registry and the
    declarations: in the declaring module, or where its record is written (a store, M2, a
    route's `write_ahead`). So a declaration cannot name an action no code writes."""
    declared = {
        action
        for cls in _admin_classes()
        for _, member in _public_methods(cls)
        if (found := declaration(member)) is not None
        for action in found.actions
    }
    assert len(declared) >= 20  # the 30 declarations name 25 distinct actions today
    assert sorted(declared - _written_literals()) == []
