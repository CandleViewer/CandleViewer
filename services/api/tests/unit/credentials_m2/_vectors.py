"""M2 test vectors and fakes. Fixed vectors only; never a real key (C-13.5)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import UUID

from candleviewer.secrets._kek import LoadedKek

KEK_V1 = bytes(range(32))
KEK_V2 = bytes(range(100, 132))
#: The live lineage's KEK in two-environment tests: never shared with a non-live process (#2338).
KEK_LIVE = bytes(range(50, 82))
ACCOUNT = UUID("00000000-0000-4000-8000-000000000001")
# Synthetic, deliberately low-entropy vectors (not secret-shaped; gitleaks-clean without any
# allowlist): a key of 13 zeros + "WXYZ", a secret of 24 "x". Never a real credential.
API_KEY = "testkey" + "0" * 13 + "WXYZ"
API_SECRET = "testsecret-" + "x" * 24
_FIXTURE = Path(__file__).resolve().parents[5] / "packages/fixtures/accounts/accounts.json"


def fixture_snapshot() -> dict[str, Any]:
    """`permission_snapshot` from the synthetic accounts fixture (no key material), minus the
    transfer right the fixture grants (C-2.8 / SR-030a refuse transfer-capable keys)."""
    snap: dict[str, Any] = json.loads(_FIXTURE.read_text())["accounts"][0]["permission_snapshot"]
    snap["permissions"]["Wallet"] = []
    return snap


SNAPSHOT: dict[str, Any] = fixture_snapshot()


def kek(raw: bytes = KEK_V1, version: int = 1, env: str = "demo") -> LoadedKek:
    return LoadedKek(bytearray(raw), version, env_name=env)


class AuditLog:
    def __init__(self) -> None:
        self.records: list[tuple[str, dict[str, str]]] = []
        self.fail = False

    async def __call__(self, action: str, fields: dict[str, str]) -> None:
        if self.fail:
            raise RuntimeError("audit down")
        self.records.append((action, dict(fields)))

    def actions(self) -> list[str]:
        return [a for a, _ in self.records]


ENV = "demo"


class FakeClock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t
