"""E29-S07 (#1028), contract first (C-6.1): `23-ws-protocol.md` §15.9 replays each account's latest
notice of the `oms.` family after a first `auth_ok` and gives the family `changed_at_ms`; `24`
§8.5 and §8.12 say how a lock and a resync reach a connecting client. The text is pinned to its
key phrases, as the read-only notice's tests pin theirs; the schema's field is compared with the
producer's check and the per-role cut (the parity pattern of `test_ws_spec_parity.py`); and the
replay goes through the real router to a socket whose client validates every frame against
`docs/plan/ws-schema.json`."""

from __future__ import annotations

import json

import pytest

from candleviewer.domain.primitives import AccountId
from candleviewer.oms import reconcile_standing
from candleviewer.oms_stream_wiring import (
    CHANGED_AT,
    MAX_EPOCH_MS,
    AccountNoticeStates,
    account_notice,
    checked_notice,
)
from candleviewer.ws.system_filter import NEUTRAL_FIELDS
from tests.contract.ws._harness import PROTOCOL_DOC, World, connect
from tests.unit.ws._seq_support import ACC_A, ACC_B

_PLAN = PROTOCOL_DOC.parent
_SYSTEM = "cv://ws/v1/system.schema.json"
_EPOCH_MS = {"$ref": "cv://ws/v1/common.schema.json#/$defs/epochMs"}
CHANGED = 1_789_132_262_000


def _words(text: str) -> str:
    return " ".join(text.split())


def _paragraph(start: str) -> str:
    """The folded paragraph of §15.9 that starts with `start`."""
    doc = PROTOCOL_DOC.read_text(encoding="utf-8")
    section = doc.split("### 15.9 `SystemUpdate`", 1)[1].split("\n### 15.10", 1)[0]
    [paragraph] = [p for p in section.split("\n\n") if p.startswith(start)]
    return _words(paragraph)


@pytest.mark.parametrize(
    "sentence",
    [
        "While an account's latest notice of the `oms.` family is not `oms.account_synced`, that "
        "notice is pushed right after `auth_ok` and the `system` snap (§12.1) on a **first** "
        "authentication, as the read-only notice is (E27-T02, above), with the `changed_at_ms` it "
        "was sent with.",
        "A lock is replayed from the reconciliation standing (`24-internal-schemas.md` §8.5, the "
        "stale rule), which B19's restored state rebuilds after a restart, and never from a "
        "notice alone",
        "with the time of the lock's notice when this process sent it and with no "
        "`changed_at_ms` otherwise, never a restart's time; once the standing no longer holds it, "
        "its last `oms.account_stale` is not replayed.",
        "Each frame names one account, its state keyed by the account id, so no state crosses "
        "environments (C-2.11).",
        "It is cut as every `account_notice` is: the Owner receives it whole, a Manager or Viewer "
        "only for the accounts its `account_scope` lists, and nothing when none remains.",
        "It is not repeated on an in-place re-auth. A grant gained in place (§9.5) is not replayed",
        "A view-as switch (§9.6) reconnects the socket, so its first `auth_ok` replays the "
        "target's accounts, cut to the target's scope.",
        "keys it on the account, `reason` and `changed_at_ms` or its absence: a frame equal in all "
        "three to the state it holds is that state again, never a new episode",
        "A lock the standing gains with no notice of its own, one B19's restored state rebuilds "
        "after a restart or one set ahead of B19's notice, is broadcast at once as "
        "`oms.account_stale` with no `changed_at_ms`, one frame per account, so a socket that "
        "authenticated before the lock learns it too",
        "Only the lock is read from the standing: every other state of the family is the notice as "
        "the server keeps it in memory, so after a restart a desync or a resync is not replayed "
        "until the account's next notice.",
        "A kept `oms.account_resyncing` ends when the account's next reconciliation pass whose "
        "reads follow it reports, whatever the pass found",
        "a socket open during the drop keeps the state until its next connection, as the "
        "`oms.account_synced` rule above is unchanged.",
    ],
)
def test_section_15_9_replays_the_oms_family_at_a_first_authentication(sentence: str) -> None:
    assert sentence in _paragraph("**Replay at connect (E29-S07, #1028).**")


@pytest.mark.parametrize(
    "sentence",
    [
        "A frame of the `oms.` family carries `changed_at_ms` (epoch ms, the server's clock): when "
        "the account entered the state its `reason` names.",
        "No other family carries it, so a `profiles.changed` frame never does.",
        "It names no account and counts nothing, so a Manager or Viewer receives it with the rest "
        "of its cut (the table above).",
        "A lock broadcast as the standing gains it (above) carries none until B19's notice gives "
        "it one, a restored lock's replay carries none, and a notice whose clock cannot be read "
        "is sent without it rather than not at all.",
        "The field is optional and additive (C-6.3)",
    ],
)
def test_section_15_9_gives_the_oms_family_its_transition_time(sentence: str) -> None:
    assert sentence in _paragraph("**The transition time (E29-S07, #1028).**")


def test_section_15_9_names_the_field_and_the_replay_where_it_bounded_both() -> None:
    notices = _paragraph("**Account notices (SR-E29-10, #3864).**")
    assert "a frame of the `oms.` family also `changed_at_ms` (below), and no other field." in (
        notices
    )
    cut = _paragraph("The Owner receives an `account_notice` whole.")
    assert "is not sent the notices before it, the `oms.` family's replay at a first " in cut


def test_24_says_how_a_connecting_client_learns_a_lock_and_a_resync() -> None:
    doc = _words((_PLAN / "24-internal-schemas.md").read_text(encoding="utf-8"))
    assert (
        "A connecting client learns a lock from the replay of `23-ws-protocol.md` §15.9 (E29-S07), "
        "which reads this standing and never a notice alone"
    ) in doc
    assert (
        "and with no time after a restart, as the standing is rebuilt from B19's restored " in doc
    )
    assert (
        "a connecting client is sent it after `auth_ok` until then or its next pass (E29-S07)"
        in (doc)
    )
    assert (
        "A lock the standing gains with no notice of its own (a restored one, or one set ahead of "
        "B19's notice) is broadcast at once as `oms.account_stale` with no time, one frame per "
        "account"
    ) in doc
    assert "Only the lock is read from the standing" in doc
    assert (
        "A pass whose reads were lost (the report of one has an empty `gap_window` and an error at "
        "step 1) confirmed nothing, so it keeps no digest and the account's last one stands"
    ) in doc
    assert "The digest is kept before the pass's notice is sent" in doc


def test_section_16_1_records_the_change() -> None:
    doc = _words(PROTOCOL_DOC.read_text(encoding="utf-8"))
    note = doc.split("**Contract change, 2026-11-02 (#1028).**", 1)[1].split("###", 1)[0]
    assert "gains an optional `changed_at_ms` (`epochMs`, §15.9)" in note
    assert "This is additive (C-6.3)" in note


@pytest.mark.parametrize(
    "bundle", ["docs/plan/ws-schema.json", "packages/protocol/ws-schemas.json"]
)
def test_the_schema_field_is_the_producers_and_the_cuts(bundle: str) -> None:
    """Both generated bundles carry `changed_at_ms` as an optional `epochMs`, whose range is the
    one the producer's check admits, and the role-neutral list keeps it."""
    schemas = json.loads((_PLAN.parents[1] / bundle).read_text(encoding="utf-8"))["schemas"]
    system = schemas[_SYSTEM]
    assert system["properties"][CHANGED_AT] == _EPOCH_MS
    assert CHANGED_AT not in system["required"]
    epoch = schemas["cv://ws/v1/common.schema.json"]["$defs"]["epochMs"]
    assert (epoch["type"], epoch["minimum"], epoch["maximum"]) == ("integer", 0, MAX_EPOCH_MS)
    body = account_notice(ACC_A, "oms.account_stale", changed_at_ms=MAX_EPOCH_MS)
    assert set(checked_notice(body)) <= set(system["properties"])
    assert CHANGED_AT in NEUTRAL_FIELDS["account_notice"]


def test_a_replayed_lock_matches_the_system_schema_with_and_without_its_time() -> None:
    """Through the real router: the standing's locks on A (its notice's time, sent by this
    process) and on B (restored: no time) follow the snap, each schema-valid, each naming its own
    account alone."""
    standing = reconcile_standing.ReconcileStanding()
    standing.mark_stale(AccountId(ACC_A))
    standing.restored(AccountId(ACC_B), "stale_lockout")
    states = AccountNoticeStates()
    states.bind_standing(standing)
    states.offer(account_notice(ACC_A, "oms.account_stale", changed_at_ms=CHANGED))
    with connect(World(system_notices=states.notices)) as client:
        frames = [client.recv(), client.recv()]  # validated: the envelope and `system`
    assert [(f["t"], f["ch"], f["s"]) for f in frames] == [("d", "system", 2), ("d", "system", 3)]
    first, second = (f["p"] for f in frames)
    assert first == account_notice(ACC_A, "oms.account_stale", changed_at_ms=CHANGED)
    assert second == account_notice(ACC_B, "oms.account_stale") and CHANGED_AT not in second
