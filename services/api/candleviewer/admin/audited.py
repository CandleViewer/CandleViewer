"""The audit declaration of an admin service method (E42-X03, decision D1; C-2.9, SR-060).

Every public method of a class under `candleviewer/admin/` that is not a `Protocol` declares
whether calling it writes audit records, and Semgrep's `cv-admin-mutation-audited` fails CI on one
that does not, naming `Class.method` (`21-database-schema.md` §3.10.1: "enforced by a Semgrep
rule on the service layer"):

- `@audited("users.disable", ...)` names the registered `AUDIT_ACTIONS` a call may write, itself
  or through what it calls (a store, a `write_ahead` callback, M2);
- `@audit_exempt("read")` gives the reason a call writes none, one of `EXEMPT_REASONS`.

Each is a declaration only: it tags the function and returns that same function, so nothing
changes at run time, and the record stays write-ahead where the change is made, under the
store's lock (C-2.9). Each checks itself at import, so a bad declaration fails the module's
import, which every test of the module meets: an unregistered or malformed action raises
`UnknownAuditAction`, a reason outside `EXEMPT_REASONS` raises `ValueError`, and a second
declaration of one function raises `TypeError`. Put the declaration directly above the `def`,
under `@property`, `@cached_property`, `@staticmethod`, `@classmethod` or `@asynccontextmanager`,
which do not return the function they wrap.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from functools import cached_property
from types import FunctionType
from typing import Final, Literal, TypeVar, get_args

from candleviewer.audit.actions import validate_action

ExemptReason = Literal["read", "lifecycle", "wiring", "caller_audits", "contract_unrecorded"]
#: Why a public admin method writes no audit record:
#: - `read`: it reads, derives or caches state (or refills or invalidates its own cache); nothing
#:   stored changes and no action is taken;
#: - `lifecycle`: it starts, stops, drains or polls the service itself;
#: - `wiring`: it builds or configures an instance;
#: - `caller_audits`: it changes in-process state (a lock, a link, a gauge, a push) for a caller
#:   whose own declaration names the record that action writes;
#: - `contract_unrecorded`: the contract records nothing for its write (22 `endViewAs`: "Clearing
#:   a held context writes no record of its own").
EXEMPT_REASONS: Final[frozenset[str]] = frozenset(get_args(ExemptReason))
#: The attribute each declaration sets on the function it declares.
DECLARATION_ATTR: Final = "__cv_audit__"

# A TypeVar, not a PEP 695 parameter: each factory returns a decorator generic in the function.
_F = TypeVar("_F", bound=Callable[..., object])


@dataclass(frozen=True, slots=True)
class AuditDeclaration:
    """A method's declaration: the actions it may write, or the reason it writes none."""

    actions: tuple[str, ...] = ()
    exempt: ExemptReason | None = None


def _tag(fn: object, declaration: AuditDeclaration) -> None:
    if not isinstance(fn, FunctionType):
        raise TypeError(f"declare a function, directly above its def: got {type(fn).__name__}")
    if hasattr(fn, DECLARATION_ATTR):
        raise TypeError(f"{getattr(fn, '__qualname__', fn)} is declared twice")
    setattr(fn, DECLARATION_ATTR, declaration)


def audited(action: str, *more: str) -> Callable[[_F], _F]:
    """Declare that a call may write `action` (and `more`), each in `AUDIT_ACTIONS`."""
    found = AuditDeclaration(actions=tuple(validate_action(name) for name in (action, *more)))

    def declare(fn: _F) -> _F:
        _tag(fn, found)
        return fn

    return declare


def audit_exempt(reason: ExemptReason) -> Callable[[_F], _F]:
    """Declare that a call writes no audit record, for `reason` (one of `EXEMPT_REASONS`)."""
    if reason not in EXEMPT_REASONS:
        raise ValueError(f"audit_exempt reason {reason!r} is not one of {sorted(EXEMPT_REASONS)}")
    found = AuditDeclaration(exempt=reason)

    def declare(fn: _F) -> _F:
        _tag(fn, found)
        return fn

    return declare


def declaration(member: object) -> AuditDeclaration | None:
    """The declaration a class member carries, if any: a function's own, or that of the function
    a `property` (`fget`), a `cached_property` (`func`), a `staticmethod` or a `classmethod`
    wraps. The last two are read through the descriptor protocol, as attribute access on the class
    does: a staticmethod yields its function, a classmethod a bound method that reads through to
    it."""
    if isinstance(member, property):
        member = member.fget
    elif isinstance(member, cached_property):
        member = member.func
    elif isinstance(member, staticmethod | classmethod):
        member = member.__get__(None, object)
    found = getattr(member, DECLARATION_ATTR, None)
    return found if isinstance(found, AuditDeclaration) else None
