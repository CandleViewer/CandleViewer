"""E09-S11 #2119 slice 6 (decision O4, scenario S9): the break-glass notice through the E17-Q01
conformance harness. Its client validates every frame it receives against the §13-§15 schemas
(`docs/plan/ws-schema.json`), and §15.9 must name the reason code the server sends."""

from __future__ import annotations

import asyncio

from candleviewer.auth.break_glass_notice import BREAK_GLASS_NOTICE_REASON, BreakGlassNotice
from tests.contract.ws._harness import PROTOCOL_DOC, World, connect


class _Unresolved:
    async def has_unresolved_break_glass(self) -> bool:
        return True


def _section_15_9() -> str:
    text = PROTOCOL_DOC.read_text(encoding="utf-8")
    return text.split("### 15.9 `SystemUpdate`", 1)[1].split("\n## 16.", 1)[0]


def test_notice_matches_system_schema() -> None:
    source = BreakGlassNotice(_Unresolved())
    asyncio.run(source.refresh())
    with connect(World(system_notices=source.notices)) as client:  # hello, then auth -> auth_ok
        frame = client.recv()  # validated: the envelope and `system.schema.json`
    assert (frame["t"], frame["ch"], frame["p"]["kind"]) == ("d", "system", "notice")
    assert (frame["p"]["severity"], frame["p"]["reason"]) == ("critical", BREAK_GLASS_NOTICE_REASON)
    assert f"`{BREAK_GLASS_NOTICE_REASON}`" in _section_15_9()  # the contract names the code
