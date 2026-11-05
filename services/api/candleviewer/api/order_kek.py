"""The credential key's latch at the order routes (#2331; 24 Sec.8.4 step 10, 22 `Forbidden`).

While the process holds no usable KEK, `SecretsService` latches the OMS read-only gate with the
reason `secrets.kek_unavailable` (E27-T02), and every signed call would fail at the signer. An order
mutation that opens or increases exposure is refused at its route first, `403 kek_unavailable`,
by one synchronous read of memory (C-2.21): `placeOrder` (a `reduce_only` one too),
`reversePosition`, `setPositionLeverage` and an amend that increases exposure (24 Sec.8.10).

Its slot (PROPOSED, the orchestrator's ruling on #2331): after authentication, RBAC, scope and the
idempotency lookup, so a replay keeps its stored outcome; after the environment lock's fence, live
trading not enabled and the B18 kill switch; before the order-entry gate. A cancel, cancel-all, a
close, close-all, every other amend and the trade-group preview never read it (C-2.6). The stranded
and rotation latches carry other reasons and stay `trading_disabled`. The `detail` is fixed
(`OrderKekUnavailable`), never the latch's remediation text. Each route records the refusal as it
records its other refusals, before it answers (C-2.9). This module never imports `secrets` (C-3.2):
the reason is pinned here, and a test composes the real latch with a route.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Final, Protocol

from candleviewer.oms.errors import OmsError, OrderEntryRefused, OrderKekUnavailable

__all__ = ["KEK_LATCH_REASON", "KekLatch", "entry_refusal", "kek_refusal"]

#: `secrets.service.GATE_REASON`: the latch's reason while no KEK loaded at boot.
KEK_LATCH_REASON: Final = "secrets.kek_unavailable"


class KekLatch(Protocol):
    """`net.ReadOnlyGate` (`AppContext.oms_read_only_gate`) as the routes read it."""

    @property
    def reason_code(self) -> str | None: ...


def _latched(latch: KekLatch | None) -> bool:
    return latch is not None and latch.reason_code == KEK_LATCH_REASON


def entry_refusal(latch: KekLatch | None, switched: OmsError | None) -> OmsError | None:
    """The refusal at the slot, given the switches' own (`TradingSwitches.refusal`): the lock's
    fence, live trading or the kill switch first, then the KEK's, then the order-entry gate's."""
    if switched is not None and not isinstance(switched, OrderEntryRefused):
        return switched
    return OrderKekUnavailable() if _latched(latch) else switched


def kek_refusal(
    latch: KekLatch | None, switches: Callable[[], OmsError | None]
) -> OrderKekUnavailable | None:
    """For a route whose OMS service reads the switches itself (an amend, a leverage change): the
    KEK's refusal where the switches let it answer first, else None and the service answers its
    own switch. The switches are read only while the latch holds; a read may raise `OmsNotReady`
    (the serving loop's stall fence), which the caller answers as its own."""
    if not _latched(latch):
        return None
    refused = entry_refusal(latch, switches())
    return refused if isinstance(refused, OrderKekUnavailable) else None
