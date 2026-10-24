"""E29-T04 (#913) slice 4, S4-H: `attach_stop`'s failures before its send, and the known limitation
20 Sec.12.1 states until E32's B8 owns the fallback attach (the orchestrator's ruling of 2026-10-24
10:43Z): the sentence as ruled, and the names it gives as the command port writes them."""

from __future__ import annotations

from candleviewer.api.contract_conformance import OPENAPI_SPEC_PATH
from candleviewer.oms.commands import STOP_NOT_SENT

_ARCH = (OPENAPI_SPEC_PATH.parent / "20-architecture.md").read_text(encoding="utf-8")
_ROW = " ".join(
    next(
        line
        for line in _ARCH.splitlines()
        if line.startswith("| OMS | `naked_position_alerts_total` |")
    ).split()
)


def test_20_says_a_failed_attach_pages_and_nothing_retries_it_until_e32() -> None:
    assert (
        "until E32 owns `request_fallback_sl`, a failed attach pages (B1's `sl_missing`, "
        "`SL_ATTACH_FAILED`) and nothing retries or flattens it; live waits on E32's B8 for the "
        "fallback attach (24 §8.8 rule 3)." in _ROW
    )
    assert _ROW.startswith(
        "| OMS | `naked_position_alerts_total` | counter | **page immediately**."
    )


def test_20_names_a_failure_before_the_send_as_the_command_port_records_it() -> None:
    assert (
        "A failure before the attach's send (the account, the position read, the stop-request "
        "gate or the record) is answered with nothing sent, audited `sl.attached` denied with its "
        f"reason and logged `{STOP_NOT_SENT}`, so the operator can tell a stop never sent, the "
        "venue holding only what the create attached, from one sent and not confirmed" in _ROW
    )
