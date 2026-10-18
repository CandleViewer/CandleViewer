"""Candidate-key verification inside M2 (E27-T03 2b3, #836: SR-E27-01, SR-E27-09, decision 7).

Key import's capability holds a pasted pair in memory for one check. It signs `key_verify` calls
for the candidate's own id; on a pass it stores the pair `pending` with the verified snapshot and
the acting Owner; on a refusal, an error or the hold's bound it stores nothing. Fixed low-entropy
vectors only (`_vectors`, `MARK_*`), never a real key. No network.
"""

from __future__ import annotations

import ast
import asyncio
import contextlib
import inspect
import traceback
import typing
from operator import attrgetter
from pathlib import Path
from typing import Any
from unittest.mock import Mock
from uuid import UUID

import pytest
from structlog.testing import capture_logs

from candleviewer.admin.wiring import build_secrets_service
from candleviewer.observability.logging import reset_logging
from candleviewer.observability.secret_type import Secret as Pasted
from candleviewer.secrets import (
    CandidateKeys,
    CandidateSigner,
    CredentialUnavailable,
    KekUnavailable,
    SecretsService,
    WithdrawPermissionRejected,
    mint_candidate_keys,
)
from candleviewer.secrets import _metrics as m
from candleviewer.secrets import candidate as candidate_mod
from candleviewer.secrets import signing as signing_mod
from candleviewer.secrets.store import InMemoryCredentialStore
from tests.unit.credentials_m2._helpers import _borrow
from tests.unit.credentials_m2._service_fakes import _ctx, _Src, _svc
from tests.unit.credentials_m2._vectors import (
    ACCOUNT,
    API_KEY,
    API_SECRET,
    KEK_V1,
    SNAPSHOT,
    AuditLog,
)
from tests.unit.credentials_m2.test_signing import MSG, STORED_MAC

OWNER = "00000000-0000-4000-8000-0000000000aa"
#: Distinct low-entropy markers for the leak checks (never a real credential).
MARK_ID, MARK_PRIVATE = "candidate" + "0" * 9 + "QRST", "candidate-" + "z" * 26
Rig = tuple[SecretsService, InMemoryCredentialStore, AuditLog]


@pytest.fixture
async def rig() -> Rig:
    """M2 booted on the in-memory store (demo), with the boot's own records cleared."""
    store, audit = InMemoryCredentialStore(), AuditLog()
    svc = _svc(_Src(KEK_V1, 1), store=store, audit=audit)
    await svc.start(_ctx())
    audit.records.clear()
    return svc, store, audit


async def run(keys: CandidateKeys, check: Any, env: str = "demo", **kw: Any) -> Any:
    wrap = kw.pop("wrap", Pasted)  # `str`: a bare value instead of a masking wrapper
    pair = (wrap(kw.pop("key", API_KEY)), wrap(kw.pop("private", API_SECRET)))
    actor = {"actor_user_id": OWNER, "actor_role": "owner", **kw}
    return await keys.store_if_verified(env, ACCOUNT, "main", *pair, check, **actor)


def signing(result: Any, ran: list[CandidateSigner] | None = None) -> Any:
    """A check that signs `MSG` once and then returns `result`."""

    async def check(signer: CandidateSigner) -> Any:
        if ran is not None:
            ran.append(signer)
        await signer.sign(signer.key_id, MSG, purpose="key_verify")
        return result

    return check


async def test_a_pass_stores_the_pair_pending_with_the_snapshot_and_the_owner(rig: Rig) -> None:
    svc, store, audit = rig
    ran: list[CandidateSigner] = []
    meta = await run(mint_candidate_keys(svc), signing(SNAPSHOT, ran))
    row = store.rows[meta.key_id]
    assert (meta.key_id, ran[0].env, row["status"]) == (ran[0].key_id, "demo", "pending")
    assert row["permission_snapshot"]["permissions"] == SNAPSHOT["permissions"]
    assert audit.actions() == ["security.credential_borrowed", "security.credential_stored"]
    who = {"key_id": str(meta.key_id), "actor_kind": "user", "actor_role": "owner"}
    assert audit.records[0][1] == {  # the whole write-ahead record (C-2.9)
        **who, "actor_user_id": OWNER, "exchange_account_id": str(ACCOUNT), "env": "demo",
        "caller_module": "exchange_adapter", "purpose": "key_verify", "candidate": "true",
        "message_sha256": signing_mod.message_sha256(MSG),
    }  # fmt: skip
    assert audit.records[1][1].items() >= {**who, "actor_user_id": OWNER}.items()
    store.activate(meta.key_id)
    assert await _borrow(svc._require(), meta.key_id) == (API_KEY, API_SECRET)


async def test_the_candidate_signs_exactly_as_the_stored_key_would(rig: Rig) -> None:
    signed = []

    async def check(signer: CandidateSigner) -> None:
        signed.append(await signer.sign(signer.key_id, MSG, purpose="key_verify"))

    await run(mint_candidate_keys(rig[0]), check)
    assert (signed[0].api_key.reveal(), signed[0].signature) == (API_KEY, STORED_MAC)


async def test_a_refusal_persists_nothing_no_row_no_ciphertext(rig: Rig) -> None:
    _, store, audit = rig
    assert await run(mint_candidate_keys(rig[0]), signing(None)) is None
    assert store.rows == {} and audit.actions() == ["security.credential_borrowed"]


@pytest.mark.parametrize("error", [RuntimeError("probe failed"), TimeoutError("its own")])
async def test_a_check_error_persists_nothing_and_propagates_unchanged(
    rig: Rig, error: Exception
) -> None:
    """The check's own timeout included: only the hold's bound becomes `candidate_timeout`."""

    async def check(signer: CandidateSigner) -> None:
        raise error

    with pytest.raises(type(error)) as raised:
        await run(mint_candidate_keys(rig[0]), check)
    assert (raised.value, rig[1].rows, rig[2].records) == (error, {}, [])


async def test_the_holds_bound_drops_the_pair_and_its_signer_refuses_after(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    ran: list[CandidateSigner] = []
    bound = Mock(wraps=asyncio.timeout)

    async def stall(signer: CandidateSigner) -> None:
        ran.append(signer)
        await asyncio.Event().wait()

    monkeypatch.setattr(asyncio, "timeout", bound)
    with pytest.raises(CredentialUnavailable, match="candidate_timeout"):
        await run(mint_candidate_keys(rig[0], hold_s=0.01), stall)
    bound.assert_called_once_with(0.01)  # the hold's bound is hold_s itself
    with pytest.raises(CredentialUnavailable, match="candidate_unavailable"):
        await ran[0].sign(ran[0].key_id, MSG, purpose="key_verify")
    assert rig[1].rows == {} and rig[2].records == []
    held = inspect.getclosurevars(attrgetter("_CandidateSigner__sign")(ran[0])).nonlocals["pair"]
    for wrapper in held:  # the pair's wrappers refuse to reveal once the hold ended
        with pytest.raises(RuntimeError, match="invalidated"):
            wrapper.reveal()


async def test_a_check_swallowing_the_bounds_cancellation_stores_nothing(rig: Rig) -> None:
    async def swallow(signer: CandidateSigner) -> Any:
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.Event().wait()
        return SNAPSHOT  # a pass that arrives after the bound

    with pytest.raises(CredentialUnavailable, match="candidate_timeout"):
        await run(mint_candidate_keys(rig[0], hold_s=0.01), swallow)
    assert rig[1].rows == {} and rig[2].records == []


@pytest.mark.parametrize(
    ("key_id", "purpose"),
    [(None, "sign_rest"), (None, "sign_ws_auth"), (UUID(int=7), "key_verify")],
    ids=["sign_rest", "sign_ws_auth", "another_id"],
)
async def test_the_signer_signs_key_verify_for_its_own_id_only(
    rig: Rig, key_id: UUID | None, purpose: Any
) -> None:
    async def check(signer: CandidateSigner) -> None:
        await signer.sign(key_id or signer.key_id, MSG, purpose=purpose)

    with pytest.raises(CredentialUnavailable, match="candidate_unavailable"):
        await run(mint_candidate_keys(rig[0]), check)
    assert rig[1].rows == {} and rig[2].records == []


async def test_a_signing_that_outlives_the_hold_is_refused_after_its_record(rig: Rig) -> None:
    """The hold ends while a signing's write-ahead record is written: the signing refuses and
    closes its record, so nothing is signed for a dropped pair."""
    _, store, audit = rig
    entered, release = asyncio.Event(), asyncio.Event()

    async def slow_audit(action: str, fields: dict[str, str]) -> None:
        entered.set()
        await release.wait()
        audit.records.append((action, fields))

    rig[0]._require()._audit_sink = slow_audit
    late: list[asyncio.Task[Any]] = []

    async def check(signer: CandidateSigner) -> None:
        late.append(asyncio.create_task(signer.sign(signer.key_id, MSG, purpose="key_verify")))
        await entered.wait()

    assert await run(mint_candidate_keys(rig[0]), check) is None
    release.set()
    with pytest.raises(CredentialUnavailable, match="candidate_unavailable"):
        await late[0]
    assert audit.actions() == ["security.credential_borrowed", "security.credential_sign_failed"]
    assert audit.records[1][1]["reason"] == "candidate_unavailable" and store.rows == {}


@pytest.mark.parametrize(
    ("error", "raised", "reason"),
    [
        (ValueError("boom"), CredentialUnavailable, "signing_failed"),
        (asyncio.CancelledError(), asyncio.CancelledError, "cancelled"),
    ],
    ids=["error", "cancelled"],
)
async def test_a_failed_mac_closes_its_record_and_chains_nothing(
    rig: Rig, monkeypatch: pytest.MonkeyPatch, error: BaseException, raised: Any, reason: str
) -> None:
    def broken(*args: Any) -> str:
        raise error

    monkeypatch.setattr(signing_mod, "mac_hex", broken)
    with pytest.raises(raised) as failed:
        await run(mint_candidate_keys(rig[0]), signing(SNAPSHOT))
    assert failed.value.__cause__ is None and failed.value.__context__ is None
    assert rig[2].records[1][1]["reason"] == reason and rig[1].rows == {}


async def test_a_refused_failure_record_is_counted_and_the_error_kept(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*args: Any) -> str:
        raise ValueError("boom")

    async def refuse_failure_records(action: str, fields: dict[str, str]) -> None:
        rig[2].fail = action == "security.credential_sign_failed"
        await rig[2](action, fields)

    monkeypatch.setattr(signing_mod, "mac_hex", broken)
    rig[0]._require()._audit_sink = refuse_failure_records
    before = m.credential_outcome_audit_failures_total._value.get()
    with pytest.raises(CredentialUnavailable, match="signing_failed"):
        await run(mint_candidate_keys(rig[0]), signing(SNAPSHOT))
    after = m.credential_outcome_audit_failures_total._value.get()
    assert (after - before, rig[2].actions()) == (1, ["security.credential_borrowed"])


async def test_a_refused_audit_record_refuses_the_signing(rig: Rig) -> None:
    rig[2].fail = True
    with pytest.raises(CredentialUnavailable):
        await run(mint_candidate_keys(rig[0]), signing(SNAPSHOT))
    assert rig[1].rows == {}


@pytest.mark.parametrize(
    "snapshot",
    [
        {**SNAPSHOT, "permissions": {"Wallet": ["Withdraw"]}},
        {**SNAPSHOT, "permissions": {"FiatP2P": ["FiatP2POrder"]}},
        {**SNAPSHOT, "permissions": None},
        ["permissions"],
    ],
    ids=["withdraw_right", "fiat_right", "no_permissions", "not_a_mapping"],
)
async def test_a_snapshot_failing_c28_is_refused_and_nothing_stored(
    rig: Rig, snapshot: Any
) -> None:
    with pytest.raises(WithdrawPermissionRejected):
        await run(mint_candidate_keys(rig[0]), signing(snapshot))
    assert rig[1].rows == {} and "security.credential_stored" not in rig[2].actions()


@pytest.mark.parametrize(
    ("env", "fields", "error"),
    [
        ("live", {}, "environment_mismatch"),
        ("demo", {"key": ""}, "credential_shape_invalid"),
        ("demo", {"key": "with space"}, "credential_shape_invalid"),
        ("demo", {"private": "line\nbreak"}, "credential_shape_invalid"),
        ("demo", {"private": "x" * 129}, "credential_shape_invalid"),
        ("demo", {"wrap": str}, "credential_shape_invalid"),
    ],
    ids=["other_env", "empty", "space", "control", "too_long", "not_wrapped"],
)
async def test_a_refused_hold_never_runs_the_check(
    rig: Rig, env: str, fields: dict[str, Any], error: str
) -> None:
    ran: list[CandidateSigner] = []
    with pytest.raises(CredentialUnavailable, match=error):
        await run(mint_candidate_keys(rig[0]), signing(SNAPSHOT, ran), env, **fields)
    assert (ran, rig[1].rows, rig[2].records) == ([], {}, [])


@pytest.mark.parametrize(
    "actor",
    [{"actor_user_id": ""}, {"actor_role": ""}, {"actor_user_id": "owner-1"}],
    ids=["no_user", "no_role", "not_a_user_id"],
)
async def test_the_acting_owner_is_required(rig: Rig, actor: dict[str, str]) -> None:
    ran: list[CandidateSigner] = []
    with pytest.raises(ValueError, match=r"acting user|hexadecimal"):
        await run(mint_candidate_keys(rig[0]), signing(SNAPSHOT, ran), **actor)
    assert ran == []


async def test_without_a_kek_the_capability_fails_closed_before_any_hold() -> None:
    ran: list[CandidateSigner] = []
    for keys in (mint_candidate_keys(SecretsService()), build_secrets_service().candidate_keys):
        with pytest.raises(KekUnavailable):
            await run(keys, signing(SNAPSHOT, ran))
    assert ran == []


@pytest.mark.parametrize("hold_s", [0.0, 12.5])
def test_the_hold_is_bounded_at_twelve_seconds(hold_s: float) -> None:
    assert candidate_mod.CANDIDATE_HOLD_S == 12.0  # the ticket's overall deadline, pinned
    with pytest.raises(ValueError, match="CANDIDATE_HOLD_S"):
        mint_candidate_keys(SecretsService(), hold_s=hold_s)


async def test_the_pasted_pair_is_in_no_repr_log_record_or_traceback(rig: Rig) -> None:
    keys = mint_candidate_keys(rig[0])
    shown = [repr(keys)]

    async def check(signer: CandidateSigner) -> Any:
        signed = await signer.sign(signer.key_id, MSG, purpose="key_verify")
        shown.extend((repr(signer), repr(signed)))
        return SNAPSHOT

    async def boom(signer: CandidateSigner) -> None:
        raise RuntimeError("venue down")

    reset_logging()  # structlog's defaults: every level reaches the capture
    with capture_logs() as logs:
        meta = await run(keys, check, key=MARK_ID, private=MARK_PRIVATE)
        with pytest.raises(RuntimeError) as failed:
            await run(keys, boom, key=MARK_ID, private=MARK_PRIVATE)
    rendered = traceback.TracebackException.from_exception(failed.value, capture_locals=True)
    shown += [repr(meta), repr(logs), repr(rig[2].records), "".join(rendered.format())]
    assert [s for s in shown if MARK_ID in s or MARK_PRIVATE in s] == []
    assert "store_if_verified" in shown[-1]  # the traceback did render M2's frames


def test_the_capabilities_expose_only_their_members_and_stay_m2_classes() -> None:
    keys = mint_candidate_keys(SecretsService())
    assert {n for n in dir(keys) if not n.startswith("__")} == {
        "store_if_verified", "_CandidateKeys__run",
    }  # fmt: skip
    for cls in (CandidateKeys, CandidateSigner):
        with pytest.raises(TypeError, match="may not be subclassed"):
            type("Evil", (cls,), {"__module__": "candleviewer.oms.evil"})


def test_m2_mints_every_id_it_seals_under() -> None:
    """#2336: `_seal_new` takes the id, so its callers are pinned to `store()` and a candidate's
    hold, each with an id M2 just minted, and no caller-facing method takes a credential id."""
    refs = set()
    for path in sorted(Path(candidate_mod.__file__).parent.rglob("*.py")):
        for fn in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef) and any(
                isinstance(n, ast.Attribute) and n.attr == "_seal_new" for n in ast.walk(fn)
            ):
                refs.add(f"{path.name}:{fn.name}")
    assert refs == {"broker.py:store", "candidate.py:hold_candidate"}
    for entry in (CandidateKeys.store_if_verified, candidate_mod.hold_candidate):
        assert [n for n, t in typing.get_type_hints(entry).items() if t is UUID] == ["account_id"]
