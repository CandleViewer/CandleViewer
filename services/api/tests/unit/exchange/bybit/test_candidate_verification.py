"""#836 slice 2b3 (SR-E27-01, C-2.11): a candidate key's verification calls, signed inside M2.

M2 holds a pasted pair for one import; the adapter builds key info and the probe for it on the
candidate's environment's host, over the account REST transport (#2893 S4). Replies: the
documented-shape `tests/fixtures/key_verification/` (README there). An injected `MockTransport`
answers and `respx` answers nothing, so no request leaves the process. No network.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
from structlog.testing import capture_logs

from candleviewer.exchange.bybit.key_info import KEY_INFO_PATH, PROBE_PATH
from candleviewer.exchange.bybit.service import ExchangeBybitService
from candleviewer.observability.logging import reset_logging
from candleviewer.observability.secret_type import Secret as Pasted
from candleviewer.secrets import CandidateSigner, mint_candidate_keys
from candleviewer.secrets.store import InMemoryCredentialStore
from tests.unit.credentials_m2._service_fakes import _ctx, _Src, _svc
from tests.unit.credentials_m2._vectors import ACCOUNT, API_KEY, API_SECRET, KEK_V1, AuditLog

FIXTURES = Path(__file__).parents[3] / "fixtures" / "key_verification"
REPLIES = {KEY_INFO_PATH: "key_info_trade.json", PROBE_PATH: "wallet_balance.json"}
OWNER, UID = "00000000-0000-4000-8000-0000000000aa", "1000001"


class Rig:
    """M2 booted on demo with an in-memory store, and the adapter on a recording transport."""

    def __init__(self) -> None:
        self.sent: list[httpx.Request] = []
        self.store = InMemoryCredentialStore()
        self.adapter = ExchangeBybitService(rest_transport=httpx.MockTransport(self.answer))

    def answer(self, request: httpx.Request) -> httpx.Response:
        self.sent.append(request)
        body = json.loads((FIXTURES / REPLIES[request.url.path]).read_text(encoding="utf-8"))
        return httpx.Response(200, json=body)

    async def run(self, env: str) -> Any:
        """One import: key info and the probe on `env`'s host, then the verified snapshot."""
        svc = _svc(_Src(KEK_V1, 1), store=self.store, audit=AuditLog())
        await svc.start(_ctx())

        async def check(signer: CandidateSigner) -> dict[str, Any]:
            calls = self.adapter.candidate_verification_calls(
                env, signer, uid=UID, recv_window_ms=5000
            )
            try:
                facts = await calls.key_info()
                await calls.probe()
            finally:
                await calls.aclose()
            return {"uid": facts.uid, "readOnly": 0, "permissions": dict(facts.permissions)}

        with respx.mock():
            return await mint_candidate_keys(svc).store_if_verified(
                "demo", ACCOUNT, "main", Pasted(API_KEY), Pasted(API_SECRET), check,
                actor_user_id=OWNER, actor_role="owner",
            )  # fmt: skip


async def test_a_candidates_calls_go_to_its_own_host_signed_with_the_pasted_key() -> None:
    rig = Rig()
    reset_logging()  # structlog's defaults: every level reaches the capture
    with capture_logs() as logs:
        stored = await rig.run("demo")
    assert [(r.url.host, r.url.path) for r in rig.sent] == [
        ("api-demo.bybit.com", KEY_INFO_PATH), ("api-demo.bybit.com", PROBE_PATH),
    ]  # fmt: skip
    assert {r.headers["X-BAPI-API-KEY"] for r in rig.sent} == {API_KEY}
    assert all(len(r.headers["X-BAPI-SIGN"]) == 64 for r in rig.sent)
    assert rig.store.rows[stored.key_id]["status"] == "pending"
    events = repr(logs)
    assert "bybit_rest_request" in events and API_KEY not in events and API_SECRET not in events


@pytest.mark.parametrize("env", ["live", "testnet"])
async def test_a_candidate_is_never_sent_to_another_environments_host(env: str) -> None:
    rig = Rig()
    with pytest.raises(ValueError, match="another environment"):
        await rig.run(env)
    assert (rig.sent, rig.store.rows) == ([], {})
