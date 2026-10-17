"""E27-T03 (#836) slice 2b1: the three reason codes the stored-key self-check latches the process
read-only gate with reach clients as `system` notices (`accounts/selfcheck.py`, since slice 2a3c),
and §15.9 of `23-ws-protocol.md` names them in the open code list. The notice schema is unchanged.
"""

from __future__ import annotations

import json
import re

import pytest

from candleviewer.accounts import selfcheck
from candleviewer.net.system_topic import client_notice
from tests.contract.ws._harness import PROTOCOL_DOC, World, connect

_CODES = (selfcheck.FAILED, selfcheck.STALE, selfcheck.UNAVAILABLE)
_UUID = re.compile(r"[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}", re.IGNORECASE)


def _notice_paragraph() -> str:
    """The folded `Read-only / degraded notice` paragraph of §15.9."""
    doc = PROTOCOL_DOC.read_text(encoding="utf-8")
    section = doc.split("### 15.9 `SystemUpdate`", 1)[1].split("\n## 16.", 1)[0]
    [paragraph] = [p for p in section.split("\n\n") if p.startswith("**Read-only / degraded")]
    return " ".join(paragraph.split())


def test_section_15_9_lists_the_key_selfcheck_codes_the_job_latches_with() -> None:
    failed, stale, unavailable = _CODES
    assert (
        "`net.binding_check_failed`, `net.self_check_timed_out`, `net.binding_safe`, "
        f"`{failed}`, `{stale}` and `{unavailable}`. The last three are the stored-key "
        "self-check's"
    ) in _notice_paragraph()
    assert "the credential key (KEK) being unavailable or the stored-key self-check" in (
        _notice_paragraph()
    )


@pytest.mark.parametrize(
    "template",
    [
        "`{failed}`: a stored key failed the key gate (`createApiKey`, steps 1 to 7)",
        "`{stale}`: a stored key has no passing check inside the check interval plus 15 minutes "
        "(SR-E27-18)",
        "`{unavailable}`: the stored keys could not be checked",
        "They latch until a restart whose start-up check passes, and the notice and its message "
        "name no key and no account",
    ],
)
def test_section_15_9_says_what_each_key_selfcheck_code_means(template: str) -> None:
    failed, stale, unavailable = _CODES
    sentence = template.format(failed=failed, stale=stale, unavailable=unavailable)
    assert sentence in _notice_paragraph()


def test_the_window_the_contract_gives_a_stale_key_is_the_selfchecks() -> None:
    assert selfcheck.FRESHNESS_GRACE.total_seconds() == 15 * 60
    assert selfcheck.MAX_INTERVAL_S == 3600.0


@pytest.mark.parametrize("code", _CODES)
def test_key_selfcheck_notice_matches_the_system_schema_and_carries_its_code(code: str) -> None:
    with connect(World(system_notices=lambda: [client_notice(True, code)])) as client:
        frame = client.recv()  # validated: the envelope and `system.schema.json`
    assert (frame["t"], frame["ch"], frame["p"]["kind"]) == ("d", "system", "notice")
    assert (frame["p"]["severity"], frame["p"]["reason"]) == ("critical", code)
    assert set(frame["p"]) <= {"kind", "severity", "message", "reason"}


@pytest.mark.parametrize("code", _CODES)
def test_key_selfcheck_notice_message_is_the_fixed_role_neutral_text_naming_no_key(
    code: str,
) -> None:
    with connect(World(system_notices=lambda: [client_notice(True, code)])) as client:
        notice = client.recv()["p"]
    assert notice["message"] == "Trading disabled: the server is in read-only mode."
    assert not _UUID.search(json.dumps(notice))  # a key id or an account id is a UUID
