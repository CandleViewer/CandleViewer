"""Domain errors for the bars module (M8)."""

from __future__ import annotations


class BarsError(Exception):
    """Base exception for the M8 `bars` module."""


class BarSpecError(BarsError, ValueError):
    """A bar spec or wire `(bar_type, param)` pair is invalid.

    Messages are human-readable sentences naming the offending field; they surface
    verbatim in SCR-042 and map to an RFC 7807 422 at the HTTP edge.
    """


class BarParamOutOfRange(BarSpecError):
    """SR-E12-03: a well-formed `param` outside the floor and ceiling of its bar type. The message
    names the bound (never the client's text), so REST and WS show the same sentence."""


class BarServiceStopping(BarsError):
    """The bar service is shutting down: a transient refusal, retried after a reconnect."""


class SyntheticBarPersistError(BarsError):
    """A synthetic (densified) bar reached the persistence boundary (§3.3a: never persisted)."""


class SpecCapExceeded(BarsError):
    """SR-E12-04 / BR-30: registering one more distinct spec would exceed a hard cap.

    `code` is the stable token (`spec_cap_exceeded`); the message is a sentence for SCR-042.
    Only the per-user cap lists spec hashes, and only the caller's own (`own`): per-symbol
    and process-wide refusals carry the count alone, because those series belong to other
    users too (no cross-user disclosure).
    """

    code = "spec_cap_exceeded"

    def __init__(self, cap: str, limit: int, active: int, own: tuple[str, ...] = ()) -> None:
        self.cap, self.limit, self.active, self.own = cap, limit, active, own
        if own:
            shown = ", ".join(own[:8]) + (" and more" if len(own) > 8 else "")
            what = f"close one of your series ({shown})"
        else:
            what = "close a series or try again later"
        super().__init__(
            f"The {cap} limit of {limit} bar series is reached ({active} active); "
            f"{what} before opening another."
        )
