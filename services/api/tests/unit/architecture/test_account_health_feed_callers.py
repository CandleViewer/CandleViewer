"""#837 (E27-T04): who may feed the account health runtime.

`ws_heartbeat`, `ws_dropped`, `rest_ok` and `wallet_pushed` are positive evidence: a faked healthy
state is the ticket's top threat (KV-T12), and `rest_ok` on a down account makes it degraded, which
the order-entry gate admits. The runtime's feed reaches the private-WS consumer as
`ctx.accounts.account_health`. Nothing else of `candleviewer` may name an evidence call or read that
property, bar the three below: the composition root's `account_health_wiring` (the feed hands each
call to the runtime, which hands it to the monitor and the cache), the wallet reconciler (a REST
success is evidence, `rest_ok`) and `app.py`, which attaches the feed to the accounts service. The
private-WS consumer (E29-T05, #848) adds itself to `ALLOWED` in the PR that builds it, so a reader
of the feed is a reviewed edit.

A module names one when an attribute of that name appears, call or not: a reference kept in a
variable feeds as well as a call.
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


def test_the_account_health_feed_is_named_only_where_it_is_reviewed() -> None:
    assert _users() == ALLOWED


def test_the_scan_still_sees_an_evidence_call_and_a_read_of_the_feed() -> None:
    assert _names("feed.ws_heartbeat(account)") == {"ws_heartbeat"}
    assert _names("ctx.accounts.account_health") == {FEED}
    assert _names("monitor = ctx.monitor") == set()
