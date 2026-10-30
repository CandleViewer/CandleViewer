"""`oms_reads_wiring` (E29-T07 #915, PR 1): the read store only on the real backend, of the
process's environment, and `getOrder`'s version read from the OMS in place, none while no OMS is
composed or it is not ready."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

from candleviewer.oms.errors import OmsNotReady
from candleviewer.oms_reads_wiring import oms_reads, order_versions
from candleviewer.settings import Environment as Env
from candleviewer.settings import Settings

ORDER = uuid.UUID(int=0x0A01)


def test_the_fake_backend_composes_no_read_store() -> None:
    assert oms_reads(Settings(environment=Env("demo"))) is None


def test_the_real_backend_reads_its_own_environment() -> None:
    settings = Settings(environment=Env("testnet"), storage_backend="real")
    reads = oms_reads(settings)
    assert reads is not None and reads.environment == "testnet"


class _Route:
    def __init__(self, seq: int | None, ready: bool = True) -> None:
        self.seq, self.ready = seq, ready

    @property
    def route(self) -> Any:
        if not self.ready:
            raise OmsNotReady
        return SimpleNamespace(versions=SimpleNamespace(version=lambda _id: self.seq))


def test_an_orders_version_is_the_oms_s_while_it_knows_one() -> None:
    assert order_versions(lambda: None)(ORDER) is None
    assert _version(_Route(7)) == 7
    assert _version(_Route(None)) is None
    assert _version(_Route(7, ready=False)) is None


def _version(route: Any) -> int | None:
    """The version `order_versions` reads off `route`, a stand-in typed as the runtime."""
    return order_versions(lambda: route)(ORDER)
