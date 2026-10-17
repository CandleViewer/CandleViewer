"""SR-E12-02 pre-query estimate for non-time bars (#2093, E12 STRIDE BR-28).

`/market/bars` refuses a non-time window whose estimate exceeds `limits.MAX_WINDOW_BARS` before it
reads a bar. The input is one aggregate over the window's stored prints, their count and summed
qty, and each estimate follows how the builder that stored the series closes a bar (exact `int`
and `Fraction` arithmetic; every stored print has qty > 0, the #1898 print rejection):

- `tick:N` closes on exactly N prints: `ceil(prints / N)`.
- `volume:V` closes at exactly V and splits the print that overshoots, so one print can close
  several bars and the print count bounds nothing: `ceil(qty / V)`.
- `delta:D` closes once `|buy - sell| >= D` and never splits a print. A bar's `|delta|` is at most
  the qty traded in it, so `ceil(qty / D)` bounds the bars, and so does the print count. The
  window's net delta does not: a `+D` bar and a `-D` bar net to zero.
- `range` never splits a print, so every bar holds at least one: `prints`.
- `renko` takes `prints` too, as the ticket sets it. It is an estimate, not a bound: one print can
  complete up to `MAX_BRICKS_PER_TRADE` bricks (SR-E12-15).

A bar the window serves opens on a print the window counts, so the bars cut by a window edge stay
inside these ceilings. One builder generation is assumed: each cold start in the window (#2704)
can add one partial bar.
"""

from __future__ import annotations

from decimal import Decimal
from fractions import Fraction

from candleviewer.bars.models import BarSpec


def estimate_non_time_bars(spec: BarSpec, prints: int, qty: Decimal) -> int:
    """Bars `spec`'s stored series holds in a window of `prints` prints with summed `qty`."""
    if spec.kind == "tick":
        return -(-prints // int(spec.param_value))
    if spec.kind in ("volume", "delta"):
        by_qty = -(-Fraction(qty) // Fraction(spec.param_value))
        return by_qty if spec.kind == "volume" else min(by_qty, prints)
    if spec.kind in ("range", "renko"):
        return prints
    raise ValueError("time bars are estimated from the window span, not from prints")


__all__ = ["estimate_non_time_bars"]
