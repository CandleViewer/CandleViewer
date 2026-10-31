"""The checks' limiter for a test rig that is not about the limit (#4834).

`make_rules_router` is never built without its per-user limiter, a required argument. A rig that
tests something else takes this one: the app's default rate with a burst no test spends, on a clock
that stands still, so it never answers `429`.
"""

from __future__ import annotations

from candleviewer.api.preview_limiter import PreviewLimiter
from candleviewer.settings import RULES_CHECK_RATE_PER_USER_PER_SECOND


def unthrottled() -> PreviewLimiter:
    """A limiter that admits every check of a test."""
    return PreviewLimiter(RULES_CHECK_RATE_PER_USER_PER_SECOND, burst=1_000_000, clock=lambda: 0.0)
