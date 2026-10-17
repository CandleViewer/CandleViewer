"""`AuditEmission` keeps every string storable in Postgres: U+0000 becomes U+FFFD and a lone
surrogate becomes `?`, in every field and in state keys and values at any depth, so each record
the writer accepts is stored. `PgTextAuditRepository` refuses such text as Postgres does."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from audit_fakes import FakeClock, PgTextAuditRepository
from hypothesis import given
from hypothesis import strategies as st

from candleviewer.audit.journal import fold_in, journal_dir
from candleviewer.audit.models import AuditEmission
from candleviewer.audit.wal import AuditWal
from candleviewer.audit.writer import AuditWriter

_FFFD = "\N{REPLACEMENT CHARACTER}"
_TS = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)
#: Text with at least one U+0000 or lone surrogate in it, among any other characters.
_UNSTORABLE = st.sampled_from(["\x00", chr(0xD800), chr(0xDFFF)])
_ANY_TEXT = st.text(_UNSTORABLE | st.characters(exclude_categories=()))
_DIRTY_TEXT = st.tuples(_ANY_TEXT, _UNSTORABLE, _ANY_TEXT).map("".join)
#: Text Postgres stores as is: everything UTF-8 encodes but U+0000 (other controls included).
_STORABLE_TEXT = st.text(st.characters(codec="utf-8", exclude_characters="\x00"))


def _writer(repo: PgTextAuditRepository, tmp_path: Path) -> AuditWriter:
    return AuditWriter(repo, str(tmp_path / "audit.wal"), clock=FakeClock(), sleep=repo.retry_sleep)


def _state(row: dict[str, Any], column: str = "after_state") -> Any:
    return json.loads(row[column])


async def _stored(tmp_path: Path, *records: dict[str, Any]) -> PgTextAuditRepository:
    """Emit each record as an `auth.login_failed` through a writer over a repository that
    refuses text Postgres cannot store, then flush."""
    repo = PgTextAuditRepository()
    w = _writer(repo, tmp_path)
    await w.start()
    for fields in records:
        await w.emit("auth.login_failed", **fields)
    await w.flush(5)
    await w.stop(1)
    return repo


async def test_writer_text_with_nul_in_a_field_is_stored_replaced(tmp_path: Path) -> None:
    fields = {"actor_label": "\x00ab***(len=3)", "object_id": "o\x00", "reason": "bad\x00reason"}
    [row] = (await _stored(tmp_path, fields)).rows
    assert (row["actor_label"], row["object_id"], row["reason"]) == (
        f"{_FFFD}ab***(len=3)",
        f"o{_FFFD}",
        f"bad{_FFFD}reason",
    )


async def test_writer_text_with_nul_in_state_is_stored_replaced(tmp_path: Path) -> None:
    fields = {
        "actor_label": "owner",
        "before_state": {"old\x00": ["v\x00"]},
        "after_state": {"binding\x00": "Ctrl+\x00", "nested": [{"k\x00": ["v\x00", 1]}]},
    }
    [row] = (await _stored(tmp_path, fields)).rows
    assert _state(row, "before_state") == {f"old{_FFFD}": [f"v{_FFFD}"]}
    assert _state(row) == {
        f"binding{_FFFD}": f"Ctrl+{_FFFD}",
        "nested": [{f"k{_FFFD}": [f"v{_FFFD}", 1]}],
    }


async def test_writer_stores_the_record_behind_one_with_nul(tmp_path: Path) -> None:
    repo = await _stored(tmp_path, {"actor_label": "\x00"}, {"actor_label": "owner"})
    assert [row["actor_label"] for row in repo.rows] == [_FFFD, "owner"]
    assert repo.refused == []


async def test_writer_lone_surrogate_is_stored_as_a_question_mark(tmp_path: Path) -> None:
    """`model_dump_json` refuses a lone surrogate, so the record is stored with `?` instead."""
    fields = {"actor_label": "a\ud800b", "after_state": {"k\udfff": "v\ud800"}}
    [row] = (await _stored(tmp_path, fields)).rows
    assert (row["actor_label"], _state(row)) == ("a?b", {"k?": "v?"})


async def test_fold_in_journaled_text_with_nul_is_stored_replaced(tmp_path: Path) -> None:
    """`ingest()` path: a break-glass journal record folded in at boot."""
    wal = tmp_path / "audit.wal"
    directory = journal_dir(str(wal))
    AuditWal(directory / "journal.wal").append(
        {
            "record_id": str(uuid.uuid4()),
            "action": "auth.break_glass_refused",
            "actor_label": "system:breakglass",
            "outcome": "denied",
            "reason": "r\x00",
            "after_state": {"note\x00": "n\x00"},
            "event_ts": "2026-10-15T12:00:00Z",
        }
    )
    repo = PgTextAuditRepository()
    w = _writer(repo, tmp_path)
    await w.start()
    assert await fold_in(w, directory) == 1
    await w.flush(5)
    await w.stop(1)
    [row] = repo.rows
    assert (row["reason"], _state(row)) == (f"r{_FFFD}", {f"note{_FFFD}": f"n{_FFFD}"})
    assert repo.refused == []


def _emission(texts: list[str]) -> AuditEmission:
    """An emission holding one of `texts` in each of six places: a field, and state keys and
    values in dicts, lists and tuples at several depths."""
    label, before_key, before_item, after_key, nested_key, nested_item = texts
    return AuditEmission(
        record_id=uuid.uuid4(),
        action="auth.login_failed",
        actor_label=label,
        before_state={before_key: [before_item]},
        after_state={after_key: [{nested_key: (nested_item,)}]},
        event_ts=_TS,
    )


def _texts(emission: AuditEmission) -> list[str]:
    assert emission.before_state is not None and emission.after_state is not None
    [(before_key, [before_item])] = emission.before_state.items()
    [(after_key, [nested])] = emission.after_state.items()
    [(nested_key, [nested_item])] = nested.items()
    return [emission.actor_label, before_key, before_item, after_key, nested_key, nested_item]


@pytest.mark.parametrize("slot", range(6))
@given(text=_DIRTY_TEXT)
def test_emission_replaces_text_when_it_is_the_only_unstorable_text(slot: int, text: str) -> None:
    texts = ["ok"] * 6
    texts[slot] = text
    for position, stored in enumerate(_texts(_emission(texts))):
        assert "\x00" not in stored
        stored.encode("utf-8")  # raises on a lone surrogate
        assert (stored == "ok") == (position != slot)


@given(text=_STORABLE_TEXT)
def test_emission_storable_text_is_unchanged(text: str) -> None:
    assert _texts(_emission([text] * 6)) == [text] * 6


def test_emission_validator_passes_storable_input_through_uncopied() -> None:
    clean = {"actor_label": "a\x01b", "after_state": {"k": ["v", ("t",)]}, "event_ts": _TS}
    dirty = {**clean, "reason": "r\x00"}
    assert AuditEmission._storable_text(clean) is clean
    assert AuditEmission._storable_text(dirty)["reason"] == f"r{_FFFD}"
    assert dirty["reason"] == "r\x00"  # the input is never modified
