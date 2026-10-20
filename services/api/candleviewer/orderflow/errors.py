"""Domain errors for the orderflow module (M9)."""

from __future__ import annotations


class OrderflowError(Exception):
    """Base exception for the M9 `orderflow` module."""


class IndicatorError(OrderflowError):
    """Base for the indicator kernels in `orderflow/indicators/` (E13-T02)."""


class UnknownIndicatorError(IndicatorError, LookupError):
    """No server kernel is registered under the requested indicator id."""


class IndicatorParamError(IndicatorError, ValueError):
    """A parameter, source, context or identity field is missing, mistyped or outside the
    kernel's domain. The message names the field and the rule, never the rejected value (IR-24).
    """


class InvalidParamsError(IndicatorParamError):
    """`catalogue.validate_params` refused a parameter object. `pointer` is a JSON pointer into
    the descriptor's public `params_schema` (`""` for the object as a whole) and `rule` the JSON
    Schema keyword the object breaks. The message names the parameter and its bound; nothing
    here carries the rejected value or a key the descriptor does not declare (IR-24)."""

    def __init__(self, pointer: str, rule: str, message: str) -> None:
        super().__init__(message)
        self.pointer = pointer
        self.rule = rule


class DuplicateIndicatorError(IndicatorError, ValueError):
    """An indicator id is registered twice in one catalogue."""


class IndicatorStateError(IndicatorError):
    """A state blob is malformed or belongs to another kernel (state version, indicator, build,
    params, source or context differ). The kernel keeps its state: nothing is restored."""


class IndicatorBoundaryError(IndicatorError, ValueError):
    """The C3 Decimal boundary was given a quantum it cannot apply."""


class InstanceRefusedError(IndicatorError, ValueError):
    """A requested server instance is refused before anything is held (23 §6.1): an unknown
    indicator, a `client_worker` one, a parameter outside its descriptor, the same instance twice,
    or a series it cannot read. `position` is its 0-based place in the request. The message names
    the position and, for a declared parameter, its name and bound, never a value or a key the
    server does not know (IR-24)."""

    def __init__(self, position: int, message: str) -> None:
        super().__init__(f"Instance {position}: {message}")
        self.position = position


class InstanceCapError(IndicatorError):
    """SR-E13-03: one more server instance would pass a cap. `cap` is `user`, `symbol` or
    `process` and `limit` its value; nothing names another user's instances."""

    def __init__(self, cap: str, limit: int) -> None:
        super().__init__(f"At most {limit} server indicator instances per {cap}.")
        self.cap, self.limit = cap, limit


class RecomputeRefusedError(IndicatorError):
    """SR-E13-04: a first computation needs a read of stored bars the full-recompute executor
    cannot start now (`cap` `recompute`), or a window longer than its bound (`window`). Refused,
    never queued."""

    def __init__(self, cap: str, message: str) -> None:
        super().__init__(message)
        self.cap = cap
