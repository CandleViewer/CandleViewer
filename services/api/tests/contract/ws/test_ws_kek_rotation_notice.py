"""#2266 PR A: the two gate reasons of a KEK rotation reach clients as `system` notices, so §15.9 of
`23-ws-protocol.md` names them in the open code list, beside `secrets.kek_unavailable` (C-6.1).
`secrets.kek_rotation` is the reason the `rewrapKek` contract latches order entry with (#2266 D1
sends it); `secrets.kek_rows_stranded` is the one a boot with stranded API key rows latches with
(#2266 C sends it). The notice schema is unchanged; each client text stays with the PR that first
sends the reason."""

from __future__ import annotations

import json
import re

import pytest

from candleviewer.net.system_topic import client_notice
from tests.contract._admin_support import SPEC, text
from tests.contract.ws._harness import PROTOCOL_DOC, World, connect

_ROTATION = "secrets.kek_rotation"
_STRANDED = "secrets.kek_rows_stranded"
_UUID = re.compile(r"[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}", re.IGNORECASE)


def _notice_paragraph() -> str:
    """The folded `Read-only / degraded notice` paragraph of §15.9."""
    doc = PROTOCOL_DOC.read_text(encoding="utf-8")
    section = doc.split("### 15.9 `SystemUpdate`", 1)[1].split("\n## 16.", 1)[0]
    [paragraph] = [p for p in section.split("\n\n") if p.startswith("**Read-only / degraded")]
    return " ".join(paragraph.split())


def test_the_rewrap_contract_latches_order_entry_with_the_rotation_reason() -> None:
    description = text(SPEC["paths"]["/admin/keys/kek-rewrap"]["post"]["description"])
    assert re.findall(r"gate reason `([a-z_.]+)`", description) == [_ROTATION]


def test_section_15_9_lists_the_rotation_reasons_beside_kek_unavailable() -> None:
    paragraph = _notice_paragraph()
    assert (
        f"current values are `secrets.kek_unavailable`, `{_ROTATION}`, `{_STRANDED}`, "
        "`net.public_binding_detected`"
    ) in paragraph
    assert "the mesh binding self-check, a KEK rotation, the credential key (KEK)" in paragraph


@pytest.mark.parametrize(
    "sentence",
    [
        f"Two are the KEK rotation's (#2266): `{_ROTATION}`: a KEK re-wrap run (`rewrapKek`) "
        "latched order entry before its first row;",
        f"`{_STRANDED}`: the process started without a KEK version that unrevoked API key rows "
        "of its environment are still wrapped under.",
        "The first latches until the restart that ends the rotation and the second until a "
        "restart that finds no such row; neither notice names a key or an account.",
    ],
)
def test_section_15_9_says_when_each_rotation_reason_is_sent(sentence: str) -> None:
    assert sentence in _notice_paragraph()


@pytest.mark.parametrize("code", [_ROTATION, _STRANDED])
def test_rotation_notice_matches_the_system_schema_and_names_no_key(code: str) -> None:
    with connect(World(system_notices=lambda: [client_notice(True, code)])) as client:
        frame = client.recv()  # validated: the envelope and `system.schema.json`
    assert (frame["t"], frame["ch"], frame["p"]["kind"]) == ("d", "system", "notice")
    assert (frame["p"]["severity"], frame["p"]["reason"]) == ("critical", code)
    assert set(frame["p"]) <= {"kind", "severity", "message", "reason"}
    assert not _UUID.search(json.dumps(frame["p"]))  # a key id or an account id is a UUID
