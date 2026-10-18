"""#3539: a symbol, an option value or a topic segment that ends in a newline is refused like any
value outside its pattern. Python's `$` also matches before a final newline, so `match` took them;
the server reads each pattern whole (`fullmatch`). Under §13's ECMA-262 patterns such a frame
breaks the schema, so it is sent as a deliberately invalid frame (`conform=False`): the harness's
validator applies `pattern` with Python's `re.search`, whose `$` matches before the newline, and
could not tell. The assertions are ours. Both wires, backpressure flag off and on; every frame
received is validated. Unit twins: `tests/unit/ws/test_topics.py`."""

from __future__ import annotations

from typing import Any

import pytest

from candleviewer.ws.backpressure_config import BackpressureConfig
from tests.contract.ws._harness import World, connect

_FLAGS = pytest.mark.parametrize("flag", [None, BackpressureConfig()], ids=["flag-off", "flag-on"])


@_FLAGS
def test_contract_a_symbols_option_ending_in_a_newline_is_refused_alone(
    flag: BackpressureConfig | None,
) -> None:
    """§5.2: the entry whose `symbols` option holds `"BTCUSDT\\n"` is `invalid_options` naming
    `symbols`; its neighbours are accepted, nothing is held for it and the socket stays open."""
    bad = {"ch": "ticker", "opts": {"symbols": ["BTCUSDT\n"]}}
    with connect(World(backpressure=flag)) as c:
        results = c.sub("book.BTCUSDT.50", bad, "trades.BTCUSDT", conform=False)["p"]["results"]
        assert [(r["ch"], r["ok"]) for r in results] == [
            ("book.BTCUSDT.50", True),
            ("ticker", False),
            ("trades.BTCUSDT", True),
        ]
        assert results[1]["error"] == {
            "code": "invalid_options",
            "message": "Option 'symbols' is out of range.",
            "field": "symbols",
            "retryable": False,
        }
        again = c.sub({"ch": "ticker", "opts": {"symbols": ["BTCUSDT"]}})["p"]["results"][0]
        assert again["ok"] is True  # no duplicate: the refused entry left nothing behind


@_FLAGS
@pytest.mark.parametrize(
    ("entry", "field"),
    [
        pytest.param("ticker.BTCUSDT\n", "topics[0]", id="symbol-last"),
        pytest.param("book.BTCUSDT\n.50", "topics[0]", id="symbol-middle"),
        pytest.param({"ch": "trades.BTCUSDT\n"}, "topics[0].ch", id="object-entry"),
    ],
)
def test_contract_a_topic_whose_symbol_ends_in_a_newline_is_not_a_topic_name(
    flag: BackpressureConfig | None, entry: Any, field: str
) -> None:
    """§5.2: refused whole, as any name outside §13 `topic` is (#2396): one `err` naming the
    entry and no `sub_ok`; no strike, so the next `sub` of a legal name is served."""
    with connect(World(backpressure=flag)) as c:
        c.send({"t": "sub", "id": "z", "p": {"topics": [entry]}}, conform=False)
        f = c.recv()  # validated: an `err`, so no `results[].ch` echoes the name
        assert (f["t"], f["id"], f["p"]["code"], f["p"]["field"]) == (
            "err",
            "z",
            "invalid_options",
            field,
        )
        assert c.sub("ticker.BTCUSDT")["p"]["results"][0]["ok"] is True
