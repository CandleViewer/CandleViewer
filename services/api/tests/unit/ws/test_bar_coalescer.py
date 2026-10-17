from __future__ import annotations

from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st

from candleviewer.ws.bar_coalescer import BarCoalescer


def _bar(gen: int, idx: int, c: str, *, confirm: bool = False, **kw: Any) -> dict[str, Any]:
    return {"generation": gen, "index": idx, "t_ms": 1000, "c": c, "confirm": confirm, **kw}


def test_same_t_ms_volume_bars_are_not_merged() -> None:
    co = BarCoalescer()
    for i in range(5):
        co.add(_bar(0, i, str(i), confirm=True))
    items, count = co.flush()
    assert [b["index"] for b in items] == [0, 1, 2, 3, 4]
    assert count == 5


def test_generation_is_part_of_key() -> None:
    co = BarCoalescer()
    co.add(_bar(0, 0, "1"))
    co.add(_bar(1, 0, "2"))
    assert len(co.flush()[0]) == 2


def test_unconfirmed_never_replaces_confirmed() -> None:
    co = BarCoalescer()
    co.add(_bar(0, 0, "1", confirm=True))
    co.add(_bar(0, 0, "2"))
    assert co.flush()[0][0]["c"] == "1"


def test_confirmed_replaced_only_when_amended() -> None:
    co = BarCoalescer()
    co.add(_bar(0, 0, "1", confirm=True))
    co.add(_bar(0, 0, "2", confirm=True))
    assert co.flush()[0][0]["c"] == "1"
    co.add(_bar(0, 0, "1", confirm=True))
    co.add(_bar(0, 0, "9", confirm=True, amended=True))
    assert co.flush()[0][0]["c"] == "9"


def test_truthy_confirm_counts_as_confirmed() -> None:
    """`confirm` is read by truthiness; the footprint merge reads it the same way (#2998)."""
    co = BarCoalescer()
    co.add({**_bar(0, 0, "1"), "confirm": 1})
    co.add(_bar(0, 0, "2"))  # unconfirmed: never replaces a confirmed bar
    co.add({**_bar(0, 0, "3"), "confirm": 1})  # confirmed again: only an amendment replaces it
    assert co.flush()[0][0]["c"] == "1"
    co.add({**_bar(0, 0, "1"), "confirm": 1})
    co.add({**_bar(0, 0, "9"), "confirm": 1, "amended": True})
    assert co.flush()[0][0]["c"] == "9"


def test_overflow_flags_resnapshot() -> None:
    co = BarCoalescer(max_pending=1)
    co.add(_bar(0, 0, "1"))
    co.add(_bar(0, 1, "1"))
    assert co.overflowed


def test_amended_then_stale_confirmed_keeps_amended() -> None:
    co = BarCoalescer()
    co.add(_bar(0, 0, "1", confirm=True))
    co.add(_bar(0, 0, "9", confirm=True, amended=True))
    co.add(_bar(0, 0, "5", confirm=True))
    assert co.flush()[0][0]["c"] == "9"


def test_take_overflow_clears_flag() -> None:
    co = BarCoalescer(max_pending=1)
    co.add(_bar(0, 0, "1"))
    co.add(_bar(0, 1, "1"))
    assert co.take_overflow() is True
    assert co.take_overflow() is False


def _oracle(updates: list[dict[str, Any]]) -> dict[tuple[int, int], dict[str, Any]]:
    """Explicit §8.2 rules, one update at a time."""
    state: dict[tuple[int, int], dict[str, Any]] = {}
    for u in updates:
        k = (u["generation"], u["index"])
        cur = state.get(k)
        if cur is None:
            state[k] = u
        elif cur["confirm"]:
            if u["confirm"] and u.get("amended"):
                state[k] = u
        else:
            state[k] = u
    return state


_updates = st.lists(
    st.builds(
        lambda g, i, c, conf, am: _bar(g, i, str(c), confirm=conf, amended=am),
        st.integers(0, 2),
        st.integers(0, 3),
        st.integers(0, 99),
        st.booleans(),
        st.booleans(),
    ),
    max_size=40,
)


@settings(max_examples=300, deadline=None)
@given(_updates)
def test_coalesced_state_matches_section_8_2_oracle(updates: list[dict[str, Any]]) -> None:
    co = BarCoalescer()
    for u in updates:
        co.add(u)
    items, count = co.flush()
    assert {(b["generation"], b["index"]): b for b in items} == _oracle(updates)
    assert count == len(updates)
    assert [(b["generation"], b["index"]) for b in items] == sorted(
        (b["generation"], b["index"]) for b in items
    )
