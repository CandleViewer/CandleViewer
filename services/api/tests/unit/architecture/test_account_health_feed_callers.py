"""#837 (E27-T04): who may feed the account health runtime.

`ws_heartbeat`, `ws_dropped`, `rest_ok` and `wallet_pushed` are positive evidence: a faked healthy
state is the ticket's top threat (KV-T12), and `rest_ok` on a down account makes it degraded, which
the order-entry gate admits. The runtime's feed reaches the private-WS consumer as
`ctx.accounts.account_health`. Nothing else of `candleviewer` may name an evidence call or read that
property, bar the four below: the composition root's `account_health_wiring` (the feed hands each
call to the runtime, which hands it to the monitor and the cache), the wallet reconciler (a REST
success is evidence, `rest_ok`), `app.py`, which attaches the feed to the accounts service, and the
private-WS consumer (E29-T05, #848), which feeds heartbeat, dropped and wallet evidence and reads
nothing else. The consumer's composition root, `oms_stream_wiring.py` (E29-T05 S8a), names those
same three, and only them: its `ServedEvidence` hands each call the consumer makes, as it is made,
to the feed on the serving loop (`Serving.notify`), whose monitor and wallet cache are that loop's;
it originates no evidence of its own, never names `rest_ok` (the consumer's protocol,
`stream_consumer.StreamEvidence`, has none) and never reads the feed's property (S8b passes the
feed in). Any other reader of the feed is a reviewed edit to `ALLOWED`.

A module names one when an attribute of that name appears, call or not: a reference kept in a
variable feeds as well as a call.

`stream_started` (E29-T05 S8b, 20 Sec.6.2) opens the boot dead-man's-switch window: an account
tracked at boot is owed its boot episode from then. Only the OMS runtime, which owns the
private-stream consumer, calls it, where it starts the consumer (`oms_wiring.py`), and the runtime
it calls hands it to the monitor (`account_health_wiring.py`): a call from anywhere else could open
the window when no consumer has started, or before one does.
"""

from __future__ import annotations

import ast
from pathlib import Path

import candleviewer

PKG = Path(candleviewer.__file__).resolve().parent
EVIDENCE = frozenset({"ws_heartbeat", "ws_dropped", "rest_ok", "wallet_pushed"})
FEED = "account_health"
ALLOWED: dict[str, frozenset[str]] = {
    "account_health_wiring.py": EVIDENCE,
    "accounts/wallet.py": frozenset({"rest_ok"}),
    "app.py": frozenset({FEED}),
    "oms/stream_consumer.py": frozenset({"ws_heartbeat", "ws_dropped", "wallet_pushed"}),
    "oms_stream_wiring.py": frozenset({"ws_heartbeat", "ws_dropped", "wallet_pushed"}),
}


def _names(text: str) -> set[str]:
    nodes = ast.walk(ast.parse(text))
    return {n.attr for n in nodes if isinstance(n, ast.Attribute)} & (EVIDENCE | {FEED})


def _users() -> dict[str, frozenset[str]]:
    found: dict[str, frozenset[str]] = {}
    for path in PKG.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if any(name in text for name in (*EVIDENCE, FEED)) and (names := _names(text)):
            found[path.relative_to(PKG).as_posix()] = frozenset(names)
    return found


STARTED = "stream_started"
STARTED_BY = frozenset({"account_health_wiring.py", "oms_wiring.py"})


def _starters() -> set[str]:
    found: set[str] = set()
    for path in PKG.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        nodes = ast.walk(ast.parse(text)) if STARTED in text else ()
        if any(isinstance(n, ast.Attribute) and n.attr == STARTED for n in nodes):
            found.add(path.relative_to(PKG).as_posix())
    return found


def test_the_account_health_feed_is_named_only_where_it_is_reviewed() -> None:
    assert _users() == ALLOWED


def test_the_boot_window_is_opened_only_where_the_consumer_starts() -> None:
    assert _starters() == STARTED_BY


def test_the_scan_still_sees_an_evidence_call_and_a_read_of_the_feed() -> None:
    assert _names("feed.ws_heartbeat(account)") == {"ws_heartbeat"}
    assert _names("ctx.accounts.account_health") == {FEED}
    assert _names("monitor = ctx.monitor") == set()
