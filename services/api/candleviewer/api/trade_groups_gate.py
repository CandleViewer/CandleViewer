"""`trading.trade_groups` for its routes (E28-T05 #909; 21 Sec.10.7): the definition writes ask
`refusal`; the preview asks `preview_refusal`, a refusal whatever the flag says until the gate is
built `preview_ready`, which S3c alone does, with the preview's audited refusals (ruling 6)."""

from __future__ import annotations

from collections.abc import Callable

from fastapi.responses import Response

from candleviewer.api.profiles import problem


class TradeGroupsGate:
    """`trading.trade_groups` (C-4.13, never a kill switch: C-4.14) for the definition writes and
    the preview: off, `403 trading_disabled` with no `reason`, as `placeOrder` while its flag is."""

    def __init__(self, enabled: Callable[[], bool], *, preview_ready: bool = False) -> None:
        self._enabled, self._preview_ready = enabled, preview_ready

    def refusal(self) -> Response | None:
        if self._enabled() is True:
            return None
        return problem("trading_disabled", "Trade groups are not enabled.", status=403)

    def preview_refusal(self) -> Response | None:
        """Refused outright until the gate is built `preview_ready`, then as the writes are."""
        if self._preview_ready is not True:
            return problem("trading_disabled", "Trade groups are not enabled.", status=403)
        return self.refusal()
