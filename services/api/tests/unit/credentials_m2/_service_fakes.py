"""Shared fakes for the SecretsService tests."""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from candleviewer.net.binding_check import BindingCheckResult
from candleviewer.net.read_only_gate import ReadOnlyGate
from candleviewer.secrets import KEY_ID_SLOT
from candleviewer.secrets._kek import LoadedKek
from candleviewer.secrets._source import KekSources
from candleviewer.secrets.errors import KekLoadError
from candleviewer.secrets.secret import Secret
from candleviewer.secrets.service import SecretsService, mint_borrower
from candleviewer.secrets.store import InMemoryCredentialStore
from candleviewer.settings import Settings
from tests.unit.credentials_m2._vectors import ACCOUNT, SNAPSHOT, AuditLog

_PASS = BindingCheckResult(safe=True, bound_addresses=(), reason_code="ok", reason_text="ok")
KEK_V3 = bytes(range(200, 232))


def _settings(**kw: Any) -> Settings:
    return Settings(_env_file=None, **kw)  # type: ignore[call-arg]  # pydantic-settings kwarg


class _Src:
    """Fake source; records every LoadedKek it hands out so tests can assert zeroing.
    `_bound_sources` binds it to the process environment, as `sources_from_settings` does."""

    def __init__(self, raw: bytes | None, version: int, *, exc: BaseException | None = None,
                 fifo: bool = False, gate: threading.Event | None = None) -> None:  # fmt: skip
        self.raw, self.version, self.exc, self.fifo, self.gate = raw, version, exc, fifo, gate
        self.env = "demo"
        self.handed: list[LoadedKek] = []

    def load(self) -> LoadedKek:
        if self.gate is not None:
            self.gate.wait(5)
        if self.exc is not None:
            raise self.exc
        if self.raw is None:
            raise KekLoadError("kek_unavailable")
        k = LoadedKek(bytearray(self.raw), self.version, env_name=self.env, is_fifo=self.fifo)
        self.handed.append(k)
        return k


def _zeroed(src: _Src) -> bool:
    return bool(src.handed) and all(k._key == bytearray(32) for k in src.handed)


def _bound_sources(
    cur: _Src, prev: _Src | None = None, ack: Path | None = None
) -> Callable[[Settings], KekSources]:
    """The `sources` seam: each fake source loads for the process environment (#2338)."""

    def sources(settings: Settings) -> KekSources:
        for src in filter(None, (cur, prev)):
            src.env = settings.environment.value
        return KekSources(cur, prev, ack)

    return sources


def _ctx(**kw: Any) -> Any:
    return SimpleNamespace(settings=_settings(**kw), oms_read_only_gate=ReadOnlyGate())


def _svc(
    cur: _Src,
    prev: _Src | None = None,
    *,
    store: Any = None,
    audit: AuditLog | None = None,
    hardened: bool = True,
    ack: Path | None = None,
    timeout: float = 15.0,
) -> SecretsService:
    st = store if store is not None else InMemoryCredentialStore()
    return SecretsService(
        store=st, kcv_store=st, audit=audit or AuditLog(), sources=_bound_sources(cur, prev, ack),
        harden=lambda: hardened, load_timeout_s=timeout,
    )  # fmt: skip


async def _store_one(svc: SecretsService) -> Any:
    b = svc._require()
    meta = await b.store("demo", ACCOUNT, "l", Secret("ABCD1234"), Secret("s"), SNAPSHOT)
    b._store.activate(meta.key_id)  # type: ignore[attr-defined]  # in-memory fake helper
    return meta


async def _borrow(svc: SecretsService, key_id: Any) -> str:
    """Sign through the minted capability; returns the key id M2 hands back (never the secret)."""
    borrower = mint_borrower(svc, "exchange_adapter")
    out = await borrower.sign(key_id, (KEY_ID_SLOT,), purpose="sign_rest")
    return out.api_key.reveal()


async def _boot(store: Any, cur: _Src, prev: _Src | None = None) -> SecretsService:
    svc = _svc(cur, prev, store=store)
    await svc.start(_ctx())
    return svc
