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


class IndicatorStateError(IndicatorError):
    """A state blob is malformed or belongs to another kernel (state version, indicator, build,
    params, source or context differ). The kernel keeps its state: nothing is restored."""


class IndicatorBoundaryError(IndicatorError, ValueError):
    """The C3 Decimal boundary was given a quantum it cannot apply."""
