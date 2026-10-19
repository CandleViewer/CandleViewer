"""#415 E17-X02: a `sub` takes one spelling of an id and of an integer (`23-ws-protocol.md` §6.1,
§6.2). Another spelling refuses its topic alone, so the topics around it are served, and the one
name left is the one `duplicate_subscription` sees."""

from __future__ import annotations

from typing import Any, Final

import pytest

from tests.unit.ws.test_subscriptions import A, _sub
from tests.unit.ws.test_topic_registry_as_built import _manager

ID: Final = str(A)  # 00000000-0000-0000-0000-00000000000a
RULE: Final = "bb000000-0000-4000-8000-000000000001"
#: Not the §13 `uuid` form (ASCII hex digits, 8-4-4-4-12). `uuid.UUID` reads the first eight as
#: `ID`; the last four are `ID` with one more character, which a match of a prefix would take.
OTHER: Final = {
    "urn": f"urn:uuid:{ID}",
    "braces": f"{{{ID}}}",
    "no-hyphens": ID.replace("-", ""),
    "doubled-hyphens": ID.replace("-", "--"),
    "plus-sign": "+" + ID[1:],
    "blank": " " + ID[1:],
    "fullwidth-digits": ID.replace("0", chr(0xFF10)),
    "arabic-indic-digits": ID.replace("0", chr(0x660)),
    "trailing-digit": ID + "0",
    "trailing-newline": ID + "\n",
    "trailing-blank": ID + " ",
    "trailing-brace": ID + "}",
}
NAMES: Final = (
    "book.BTCUSDT.050 bars.BTCUSDT.time.01 bars.BTCUSDT.time.::: bars.BTCUSDT.time.1: "
    "bars.BTCUSDT.tick.0100 bars.BTCUSDT.renko.00:5 bars.BTCUSDT.renko.atr:014 "
    "bars.BTCUSDT.renko.atr:14:02 "
    "footprint.BTCUSDT.time.05 footprint.BTCUSDT.tick.0100 footprint.BTCUSDT.time.:5"
).split()
#: The entry sent -> the `code` and `field` of the refusal it gets.
REFUSED: Final[dict[str, tuple[Any, str, str | None]]] = {
    **{
        f"{ch}-{name}": (
            {"ch": ch, "opts": {"exchange_account_ids": [ID], option: [spelling]}},
            "invalid_options",
            option,
        )
        for ch, option in (("orders", "exchange_account_ids"), ("rules", "rule_ids"))
        for name, spelling in OTHER.items()
    },
    **{name: (name, "invalid_topic_format", None) for name in NAMES},
}
#: Names pass the grammar only: no bar service is wired here, and it refuses `atr`, `pnf` and `0:5`.
SERVED: Final = [
    *"book.BTCUSDT.50 bars.BTCUSDT.time.5 bars.BTCUSDT.time.D bars.BTCUSDT.tick.100".split(),
    *"bars.BTCUSDT.renko.atr:14 bars.BTCUSDT.renko.0:5 bars.BTCUSDT.pnf.10:3".split(),
    "footprint.BTCUSDT.time.5",
    {"ch": "orders", "opts": {"exchange_account_ids": [ID]}},
    {"ch": "rules", "opts": {"exchange_account_ids": [ID], "rule_ids": [RULE]}},
]


@pytest.mark.parametrize(("entry", "code", "field"), REFUSED.values(), ids=REFUSED)
def test_sub_a_non_canonical_entry_refuses_its_topic_alone(
    entry: Any, code: str, field: str | None
) -> None:
    conn = _manager()
    results = _sub(conn, "trades.BTCUSDT", entry, "ticker.BTCUSDT")
    error = results[1].get("error", {})
    assert [r["ok"] for r in results] == [True, False, True]
    assert (error.get("code"), error.get("field")) == (code, field)
    assert len(conn.by_id) == 2


@pytest.mark.parametrize("entry", SERVED)
def test_sub_the_canonical_spelling_is_served(entry: Any) -> None:
    (result,) = _sub(_manager(), entry)
    assert result["ok"] is True


def test_sub_an_upper_case_id_is_read_as_its_lower_case_form() -> None:
    opts = {"exchange_account_ids": [ID.upper()], "rule_ids": [RULE.upper(), RULE]}
    (result,) = _sub(_manager(), {"ch": "rules", "opts": opts})
    effective = result["effective"]
    assert (effective["exchange_account_ids"], effective["rule_ids"]) == ([ID], [RULE])


@pytest.mark.parametrize(
    "pair",
    [
        "book.BTCUSDT.50 book.BTCUSDT.050",
        "bars.BTCUSDT.time.5 bars.BTCUSDT.time.05",
        "footprint.BTCUSDT.tick.100 footprint.BTCUSDT.tick.0100",
    ],
)
def test_sub_duplicate_subscription_sees_the_one_canonical_name(pair: str) -> None:
    name, other = pair.split()
    conn = _manager()
    codes = [r.get("error", {}).get("code") for ch in (name, other, name) for r in _sub(conn, ch)]
    assert codes == [None, "invalid_topic_format", "duplicate_subscription"]
    assert [s.ch for s in conn.by_id.values()] == [name]
