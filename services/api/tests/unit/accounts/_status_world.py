"""E27-T04 (#837) W4: two monitored accounts on a fake clock, read through the `ExchangeAccount`
read model (`accounts/status.py`); the `wallet` topic tests extend it with a hub (`_wallet_ws.py`).
"""

from __future__ import annotations

from candleviewer.accounts.health import AccountHealthMonitor
from candleviewer.accounts.status import AccountStatusReader
from candleviewer.accounts.wallet import WalletCache
from tests.unit.accounts._fakes import ACC, ACC_B, T0, Dms, FakeClock
from tests.unit.accounts._runtime_rig import snapshot


class StatusWorld:
    """`ACC` and `ACC_B` monitored on a fake clock, healthy, each with a wallet snapshot refreshed
    at `T0`; `status` reads an account's five fields."""

    def __init__(self) -> None:
        self.clock = FakeClock()
        self.monitor = AccountHealthMonitor(self.clock, Dms())
        self.wallets = WalletCache(self.clock)
        for account in (ACC, ACC_B):
            self.monitor.track(account)
            self.wallets.track(account)
            self.monitor.ws_heartbeat(account)
            self.wallets.apply(account, snapshot(T0))
        self.status = AccountStatusReader(self.monitor, self.wallets).status
