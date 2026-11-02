"""#452 F5: every E12 number is read from `bars.limits`; the spec caps moved there from
`bars.leases`, which only re-exports them."""

from __future__ import annotations

from candleviewer.bars import leases, limits
from candleviewer.bars.leases import DEFAULT_CAPS


def test_spec_caps_are_pinned_to_the_threat_model_numbers() -> None:
    assert (limits.CAP_PER_USER, limits.CAP_PER_SYMBOL, limits.CAP_GLOBAL) == (8, 32, 512)


def test_leases_reexports_the_same_values() -> None:
    assert leases.CAP_PER_USER is limits.CAP_PER_USER
    assert leases.CAP_PER_SYMBOL is limits.CAP_PER_SYMBOL
    assert leases.CAP_GLOBAL is limits.CAP_GLOBAL


def test_default_spec_caps_come_from_limits() -> None:
    assert (DEFAULT_CAPS.per_user, DEFAULT_CAPS.per_symbol, DEFAULT_CAPS.global_) == (8, 32, 512)
