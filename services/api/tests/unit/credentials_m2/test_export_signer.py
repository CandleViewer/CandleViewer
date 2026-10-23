"""The audit export signer and its key directory (#889 S6b; ADR-0039 decisions 3, 4 and 7;
SR-E42-15): its checks in order, each refusal before any decrypt or record, and its two records.
Every key is generated in-process or is an RFC 8032 Sec.7.1 vector (C-13.5)."""

from __future__ import annotations

import asyncio
import hashlib
import pickle
import traceback
from typing import Any
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from structlog.testing import capture_logs

from candleviewer.observability.health import HealthStatus
from candleviewer.secrets import _envelope as env
from candleviewer.secrets import _export_key
from candleviewer.secrets import _metrics as m
from candleviewer.secrets import export_signer as signer
from candleviewer.secrets._kek import LoadedKek
from candleviewer.secrets.errors import CredentialUnavailable, KekUnavailable, SecretsError
from candleviewer.secrets.export_signer import ExportSigner, SigningKeys
from candleviewer.secrets.service import mint_export_signer, mint_signing_keys
from candleviewer.secrets.store import InMemoryAuthKeyStore, InMemoryExportKeyStore
from tests.unit.credentials_m2._service_fakes import _ctx, _Src, _svc
from tests.unit.credentials_m2._vectors import KEK_V1, KEK_V2, RFC8032, AuditLog, kek
from tests.unit.credentials_m2.test_export_key_boot import _booted as _boot
from tests.unit.credentials_m2.test_export_key_boot import _first
from tests.unit.credentials_m2.test_export_key_store import GENERATED

DIGEST = hashlib.sha256(b"an audit export file").digest()
JOB, OWNER = uuid4(), uuid4()
#: The 83 bytes a signature over DIGEST covers (24 Sec.15.7), written out independently.
MESSAGE = b"cv.audit.export.v1:" + DIGEST.hex().encode()


class _Booted:
    """A demo process booted under KEK v1, its signer and directory minted as wiring mints them."""

    def __init__(self, keys: InMemoryExportKeyStore) -> None:
        self.keys, self.audit = keys, AuditLog()
        self.svc = _svc(_Src(KEK_V1, 1), audit=self.audit, auth_keys=InMemoryAuthKeyStore(),
                        export_keys=keys)  # fmt: skip
        self.signer, self.directory = mint_export_signer(self.svc), mint_signing_keys(self.svc)

    async def start(self) -> _Booted:
        await self.svc.start(_ctx())
        self.booted, self.key = len(self.audit.records), self.keys.rows[-1]
        return self

    def written(self) -> list[tuple[str, dict[str, str]]]:
        return self.audit.records[self.booted :]  # what the signer wrote, after the boot's

    async def sign(self, **change: Any) -> bytes:
        call = {"key_id": self.key["key_id"], "digest": DIGEST, "job_id": JOB} | change
        return await self.signer.sign_audit_export(actor_user_id=OWNER, **call)


async def _booted(keys: InMemoryExportKeyStore | None = None) -> _Booted:
    return await _Booted(keys or InMemoryExportKeyStore()).start()


async def _down(*_: object) -> Any:
    raise RuntimeError("store down")


def _answers(row: dict[str, Any]) -> Any:
    """A store whose `active` answers `row`, whatever environment it is asked for."""

    async def active(*_: object) -> dict[str, Any]:
        return row

    return active


async def _unavailable(b: _Booted, process: str) -> None:
    """After a good boot: no KEK, no active key, a key found unusable, no store or no audit."""
    if process == "stopped":
        await b.svc.stop(1.0)
    elif process == "retired":
        b.key["status"] = "retired"
    elif process == "unopenable":
        b.svc._export_reason = "export_key_unopenable"  # what a boot whose check failed sets
    elif process == "unreadable":
        setattr(b.keys, "active", _down)  # noqa: B010 -- the store cannot be read
    elif process == "audit_down":
        b.audit.fail = True
    elif process == "other_env":  # a store that answers with another environment's row (C-2.11)
        setattr(b.keys, "active", _answers(b.key | {"env": "live"}))  # noqa: B010
    elif process == "unheld":  # re-wrapped since boot under a KEK this process does not hold
        setattr(b.keys, "active", _answers(b.key | {"kek_version": 9}))  # noqa: B010
    elif process in ("no_wrap", "no_seal"):  # a row without its wrap, or without its seal
        gone = {"no_wrap": "dek_ref", "no_seal": "sealed_seed"}[process]
        row = {k: v for k, v in b.key.items() if k != gone}
        setattr(b.keys, "active", _answers(row))  # noqa: B010


def _made(monkeypatch: pytest.MonkeyPatch) -> list[bytes]:
    """Every DEK and seed made from now on, kept to look for: no output may hold one."""
    made: list[bytes] = []

    def recorded(make: Any) -> Any:
        def wrapper() -> bytearray:
            out: bytearray = make()
            made.append(bytes(out))
            return out

        return wrapper

    monkeypatch.setattr(env, "new_dek", recorded(env.new_dek))
    monkeypatch.setattr(_export_key, "new_seed", recorded(_export_key.new_seed))
    return made


def _unwraps(monkeypatch: pytest.MonkeyPatch) -> list[bytearray]:
    """Each export DEK unwrapped from now on: the decrypt no refusal may reach."""
    seen, unwrap = [], LoadedKek.unwrap_export_dek

    def spied(self: LoadedKek, ref: str, *, key_id: str) -> bytearray:
        seen.append(unwrap(self, ref, key_id=key_id))
        return seen[-1]

    monkeypatch.setattr(LoadedKek, "unwrap_export_dek", spied)
    return seen


async def test_the_record_is_written_before_the_signature(monkeypatch: pytest.MonkeyPatch) -> None:
    """The write-ahead spy: when `sign_export` runs, its record is already written, naming the
    job, the Owner, the digest and the key (24 Sec.15.7's chain cross-check)."""
    b, at_sign, sign = await _booted(), [], signer.sign_export

    def spied(*args: Any, **kw: Any) -> bytes:
        at_sign.append(list(b.written()))
        return sign(*args, **kw)

    monkeypatch.setattr(signer, "sign_export", spied)
    deks, signature = _unwraps(monkeypatch), await b.sign()
    assert [bytes(dek) for dek in deks] == [bytes(32)]  # the one DEK opened, zeroed after use
    owner = {"actor_kind": "user", "actor_role": "owner", "actor_user_id": str(OWNER)}
    named = {"job_id": str(JOB), "env": "demo", "sha256": DIGEST.hex(), "key_id": b.key["key_id"]}
    record = (signer.SIGNED, owner | named | {"fingerprint_sha256": b.key["fingerprint_sha256"]})
    assert at_sign == [[record]] == [b.written()]
    Ed25519PublicKey.from_public_bytes(b.key["public_key"]).verify(signature, MESSAGE)


#: Each refusal before any decrypt or record: the call's change, the process, the code.
REFUSED: dict[str, tuple[dict[str, Any], str, str]] = {
    "digest_31": ({"digest": DIGEST[:31]}, "", "export_request_invalid"),
    "digest_hex": ({"digest": DIGEST.hex()}, "", "export_request_invalid"),
    "key_id_malformed": ({"key_id": "cv-audit-export-v1:XYZ"}, "", "export_request_invalid"),
    "key_id_not_str": ({"key_id": None}, "", "export_request_invalid"),
    "job_not_a_uuid": ({"job_id": "job-1"}, "", "export_request_invalid"),
    "job_not_str": ({"job_id": 7}, "", "export_request_invalid"),
    "not_the_active_key": ({"key_id": "cv-audit-export-v9:" + "0" * 16}, "", "signing_key_rotated"),
    "no_kek": ({}, "stopped", "kek_unavailable"),
    "no_active_key": ({}, "retired", "export_key_unavailable"),
    "unusable_at_boot": ({}, "unopenable", "export_key_unavailable"),
    "store_unreadable": ({}, "unreadable", "export_key_unavailable"),
    "another_environment": ({}, "other_env", "export_key_unavailable"),
    "kek_of_its_version_not_held": ({}, "unheld", "export_key_unavailable"),
    "row_without_its_wrap": ({}, "no_wrap", "export_key_unavailable"),
    "row_without_its_seal": ({}, "no_seal", "export_key_unavailable"),
    "record_not_written": ({}, "audit_down", "audit_unavailable"),  # and nothing signed
}


@pytest.mark.parametrize(("change", "process", "code"), REFUSED.values(), ids=list(REFUSED))
async def test_a_refusal_comes_before_any_decrypt_or_record(
    change: dict[str, Any], process: str, code: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    b = await _booted()
    await _unavailable(b, process)
    unwrapped = _unwraps(monkeypatch)
    with pytest.raises(SecretsError, match=f"^{code}$") as refused:
        await b.sign(**change)
    kind = KekUnavailable if process == "stopped" else CredentialUnavailable
    assert type(refused.value) is kind and refused.value.__context__ is None
    assert (unwrapped, b.written()) == ([], [])


@pytest.mark.parametrize(
    ("damage", "refusal", "code"),
    [
        ({"sealed_seed": bytes(60)}, None, "export_key_unopenable"),
        ({"dek_ref": "ek1:" + "00" * 60}, None, "export_key_unopenable"),
        ({"dek_ref": "not a wrap"}, None, "export_key_unopenable"),
        ({}, "export_key_mismatch", "export_key_mismatch"),  # `_open_seed`'s: not its public key
        ({}, "signing_failed", "signing_failed"),  # `sign_export`'s own: not the key's
    ],
    ids=["seal", "wrap", "not_a_wrap", "mismatch", "signing"],
)
async def test_a_failure_after_the_record_appends_sign_failed(
    damage: dict[str, Any], refusal: str | None, code: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """It leaves typed, nothing chained, and closes its record: a fault of the key's own by boot's
    reason for it (`KEY_FAULTS`), latched; any other refusal with its own code, latching nothing."""
    b = await _booted()
    b.key |= damage
    if refusal is not None:
        monkeypatch.setattr(signer, "sign_export", Mock(side_effect=CredentialUnavailable(refusal)))
    with pytest.raises(CredentialUnavailable, match=f"^{code}$") as failed:
        await b.sign()
    assert failed.value.__context__ is None and failed.value.__cause__ is None
    (signed, fields), closed, *latched = b.written()
    assert (signed, closed) == (signer.SIGNED, (signer.SIGN_FAILED, fields | {"reason": code}))
    assert b.svc._export_reason == (code if code in signer.KEY_FAULTS else None)
    assert len(latched) == (code in signer.KEY_FAULTS)


async def test_a_key_found_unusable_at_signing_is_latched_and_paged_as_at_boot() -> None:
    """Decision 4 (refused and paged), at signing time as at boot: `secrets` degraded, the page's
    gauge, a critical log and the record at error; the directory names no key, and the next call
    is refused before any decrypt or record. Trading is untouched: no order entry latches."""
    b = await _booted()
    b.key["sealed_seed"] = bytes(60)
    with capture_logs() as logs, pytest.raises(CredentialUnavailable):
        await b.sign()
    reason = "export_key_unopenable"
    action, fields = b.written()[-1]  # M2's own record, as boot writes it
    assert (action, fields["env"], fields["reason"]) == (
        "security.audit_signing_key_unavailable", "demo", reason
    )  # fmt: skip
    assert [e["reason"] for e in logs if e["event"] == "secrets.export_key_unavailable"] == [reason]
    assert all(
        e["log_level"] == "critical" for e in logs if e["event"] == "secrets.export_key_unavailable"
    )
    assert m.export_key_unavailable_state._value.get() == 1
    report = b.svc.health()
    assert (report.status, report.detail) == (HealthStatus.DEGRADED, reason)
    assert await b.directory.active() is None
    written = len(b.written())
    with pytest.raises(CredentialUnavailable, match=r"^export_key_unavailable$"):
        await b.sign()
    assert len(b.written()) == written  # refused before any record


async def test_two_signings_that_find_the_key_unusable_latch_it_once() -> None:
    """Both pass the boot check before either fails: one page, one record, one critical log."""
    b, both, signed = await _booted(), asyncio.Event(), []
    b.key["sealed_seed"] = bytes(60)

    async def together(action: str, fields: dict[str, str]) -> None:
        b.audit.records.append((action, dict(fields)))
        if action == signer.SIGNED:  # each waits here until both have written their record
            signed.append(action)
            if len(signed) == 2:
                both.set()
            async with asyncio.timeout(5):
                await both.wait()

    setattr(b.svc, "_audit_sink", together)  # noqa: B010
    with capture_logs() as logs:
        failed = await asyncio.gather(b.sign(), b.sign(), return_exceptions=True)
    assert [str(f) for f in failed] == ["export_key_unopenable"] * 2
    latched = [a for a, _ in b.written() if a == "security.audit_signing_key_unavailable"]
    paged = [e for e in logs if e["event"] == "secrets.export_key_unavailable"]
    assert (len(latched), len(paged)) == (1, 1)


async def test_a_kek_closed_while_signing_is_recorded_as_such_and_latches_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`stop()` closing the KEK mid-call is not the key's fault: the closing record says so (the
    bounded `_failure_reason`, as the HMAC signer's), and export stays available."""
    b = await _booted()

    def closed(*_: object, **__: object) -> bytearray:
        raise KekUnavailable("kek_unavailable")

    monkeypatch.setattr(LoadedKek, "unwrap_export_dek", closed)
    with pytest.raises(CredentialUnavailable, match=r"^credential_unavailable$"):
        await b.sign()
    assert [(a, f.get("reason")) for a, f in b.written()] == [
        (signer.SIGNED, None), (signer.SIGN_FAILED, "kek_unavailable")
    ]  # fmt: skip
    assert b.svc._export_reason is None and m.export_key_unavailable_state._value.get() == 0


@pytest.mark.parametrize(
    ("after_the_record", "code"),
    [("rotated", "signing_key_rotated"), ("unreadable", "export_key_unavailable")],
)
async def test_the_fence_refuses_a_key_no_longer_active_after_the_record(
    after_the_record: str, code: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0009 Amendment 2's re-check: a rotation committed between check 2 and the decrypt
    (or a store that cannot say) is refused and closed, never signed with the retired key."""
    b = await _booted()
    unwrapped, rotated = _unwraps(monkeypatch), b.key | {"key_id": "cv-audit-export-v2:" + "f" * 16}

    async def then_changed(action: str, fields: dict[str, str]) -> None:
        b.audit.records.append((action, dict(fields)))
        if action == signer.SIGNED:
            changed = _answers(rotated) if after_the_record == "rotated" else _down
            setattr(b.keys, "active", changed)  # noqa: B010 -- the key changes after the record

    setattr(b.svc, "_audit_sink", then_changed)  # noqa: B010
    with pytest.raises(CredentialUnavailable, match=f"^{code}$"):
        await b.sign()
    assert [(a, f.get("reason")) for a, f in b.written()] == [
        (signer.SIGNED, None), (signer.SIGN_FAILED, code)
    ]  # fmt: skip
    assert (unwrapped, b.svc._export_reason) == ([], None)


async def test_a_row_under_a_kek_version_not_held_is_logged_by_the_versions_alone() -> None:
    """#889 S7's re-check, F3-2: the read that finds the active row under a KEK version this
    process does not hold logs both versions, and nothing else."""
    b = await _booted()
    await _unavailable(b, "unheld")
    with capture_logs() as logs:
        assert await b.directory.active() is None
    assert [e for e in logs if e["event"] == "secrets.export_key_kek_not_held"] == [
        {"event": "secrets.export_key_kek_not_held", "kek_version": 9, "held": [1],
         "log_level": "error"}
    ]  # fmt: skip


@pytest.mark.parametrize(
    ("change", "check"),
    [
        ({"key_id": "cv-audit-export-v1:XYZ"}, "key_id"),
        ({"job_id": "job-1"}, "job_id"),
        ({"actor_user_id": "owner-1"}, "actor_user_id"),
        ({"digest": DIGEST[:31]}, "digest"),
    ],
)
def test_a_refused_request_is_logged_by_its_check_never_its_value(
    change: dict[str, Any], check: str
) -> None:
    call = {"key_id": "cv-audit-export-v1:" + "a" * 16, "digest": DIGEST, "job_id": JOB}
    call |= {"actor_user_id": OWNER} | change
    with capture_logs() as logs, pytest.raises(CredentialUnavailable):
        signer.request(**call)
    assert logs == [
        {"event": "secrets.export_request_invalid", "check": check, "log_level": "error"}
    ]


async def test_a_key_left_under_the_previous_kek_signs_with_that_kek() -> None:
    """A rotation boot whose re-wrap failed leaves the key under KEK v1, which boot allows
    (`_export_custody`): the directory names it and it signs with v1, the held KEK of its own
    version, never the current one."""
    keys, store = await _first()
    keys.audit_fails = True  # the rotation boot's re-wrap is refused with its record
    svc, _ = await _boot(keys, _Src(KEK_V2, 2), _Src(KEK_V1, 1), store=store, audit=AuditLog())
    keys.audit_fails, key = False, keys.rows[0]
    assert key["kek_version"] == 1 and svc.health().status is HealthStatus.OK
    assert await mint_signing_keys(svc).active() == (
        key["key_id"], key["public_key"], key["fingerprint_sha256"]
    )  # fmt: skip
    signature = await mint_export_signer(svc).sign_audit_export(key["key_id"], DIGEST, JOB, OWNER)
    Ed25519PublicKey.from_public_bytes(key["public_key"]).verify(signature, MESSAGE)


async def test_a_cancelled_signing_propagates_after_its_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    b = await _booted()

    def cancelled(*_: object, **__: object) -> bytearray:
        raise asyncio.CancelledError

    monkeypatch.setattr(LoadedKek, "unwrap_export_dek", cancelled)
    with pytest.raises(asyncio.CancelledError) as raised:
        await b.sign()
    frames = list(traceback.walk_tb(raised.value.__traceback__))
    assert frames[-1][0].f_code.co_name == "cancelled" and frames[-1][0].f_locals == {}  # scrubbed
    closing = [(a, f.get("reason")) for a, f in b.written()]
    assert closing == [(signer.SIGNED, None), (signer.SIGN_FAILED, "cancelled")]


async def test_a_closing_record_that_is_lost_is_counted() -> None:
    b = await _booted()
    b.key["sealed_seed"] = bytes(60)

    async def lost(action: str, fields: dict[str, str]) -> None:
        if action == signer.SIGN_FAILED:
            raise RuntimeError("audit down")
        b.audit.records.append((action, dict(fields)))

    setattr(b.svc, "_audit_sink", lost)  # noqa: B010 -- the audit writer fails after the first
    before = m.credential_outcome_audit_failures_total._value.get()
    with pytest.raises(CredentialUnavailable, match=r"^export_key_unopenable$"):
        await b.sign()
    assert m.credential_outcome_audit_failures_total._value.get() == before + 1


async def test_the_signature_verifies_with_the_active_key_and_no_other() -> None:
    """RFC 8032's TEST 1 as the active key: its signature verifies with TEST 1 alone (C-13.5)."""
    dek, seed = env.new_dek(), bytearray(bytes.fromhex(RFC8032["TEST 1"][0]))
    key = _export_key.seal_seed(dek, seed, env_name="demo", version=1)
    sealed = {"sealed_seed": key.sealed_seed, "public_key": key.public_key, "kek_version": 1}
    sealed["dek_ref"] = kek(KEK_V1, 1).wrap_export_dek(dek, key_id=key.key_id)
    keys, row = InMemoryExportKeyStore(), {"id": uuid4(), "env": "demo", "version": 1}
    assert await keys.insert_first(row | sealed | {"key_id": key.key_id}, audit=GENERATED)
    signature = await (await _booted(keys)).sign()
    test_1, test_2 = (bytes.fromhex(RFC8032[n][1]) for n in ("TEST 1", "TEST 2"))
    Ed25519PublicKey.from_public_bytes(test_1).verify(signature, MESSAGE)
    for public, message in ((test_2, MESSAGE), (test_1, DIGEST)):
        with pytest.raises(InvalidSignature):
            Ed25519PublicKey.from_public_bytes(public).verify(signature, message)


async def test_the_directory_gives_the_active_key_s_public_material_and_no_seed() -> None:
    b = await _booted()
    active = await b.directory.active()
    assert active == (b.key["key_id"], b.key["public_key"], b.key["fingerprint_sha256"])
    usable = await signer._usable(b.keys, (kek(KEK_V2, 2), kek(KEK_V1, 1)))  # a rotation boot's
    assert usable is not None and usable[1].version == 1  # the KEK of the key's own version


@pytest.mark.parametrize(
    "process", ["stopped", "retired", "unopenable", "unreadable", "other_env", "no_wrap", "no_seal"]
)
async def test_the_directory_answers_none_while_export_is_unavailable(process: str) -> None:
    b = await _booted()
    await _unavailable(b, process)
    assert await b.directory.active() is None


async def test_each_capability_holds_a_closure_only_and_is_m2s() -> None:
    """As `CredentialBorrower`: no `__dict__` to reach the service, no subclass outside M2 (R7)."""
    b = await _booted()
    members = {ExportSigner: {"sign_audit_export", "_ExportSigner__sign"},
               SigningKeys: {"active", "_SigningKeys__active",
                             "listing", "_SigningKeys__listing"}}  # fmt: skip  # S7: the listing
    for capability, kind in ((b.signer, ExportSigner), (b.directory, SigningKeys)):
        assert type(capability) is kind and not hasattr(capability, "__dict__")
        assert {n for n in dir(capability) if not n.startswith("__")} == members[kind]
        with pytest.raises(TypeError, match="may not be subclassed"):
            type("Sub", (kind,), {})
        with pytest.raises((TypeError, AttributeError, pickle.PicklingError)):
            pickle.dumps(capability)


async def test_no_seed_or_dek_is_in_a_log_a_record_a_failure_or_a_repr(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """C-12.6: no seed or DEK made here is in a log, record, failure, repr or directory answer."""
    made = _made(monkeypatch)
    with capture_logs() as logs:
        b = await _booted()
        signature, active = await b.sign(), await b.directory.active()
        b.key["sealed_seed"] = bytes(60)
        with pytest.raises(CredentialUnavailable) as failed:
            await b.sign()
    seen = repr((logs, b.audit.records, failed.value, b.signer, b.directory, signature, active))
    assert len(made) == 2 and not [s for s in made if s.hex() in seen or repr(s) in seen]


@pytest.mark.parametrize(
    ("fault", "raised"),
    [(RuntimeError("the signature"), CredentialUnavailable), (asyncio.CancelledError(), None)],
    ids=["failure", "cancelled"],
)
async def test_no_seed_or_dek_is_in_a_traceback_with_its_locals(
    fault: BaseException, raised: type[BaseException] | None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AD-I16, SR-E42-15: a failure or a cancellation once the seed is open renders, with the
    locals of every frame below this test's (`capture_locals`), no seed or DEK made here."""
    made, b = _made(monkeypatch), await _booted()

    class _Signs:
        @staticmethod
        def from_private_bytes(_: bytes) -> Any:  # holds a copy of the seed when it raises
            raise fault

    xk = _export_key  # the module whose signing class fails, as `test_export_key.py` patches it
    monkeypatch.setattr(xk, "Ed25519PrivateKey", _Signs)
    with pytest.raises(raised or type(fault)) as failed:
        await b.sign()
    below = failed.value.__traceback__.tb_next if failed.value.__traceback__ else None
    shown = traceback.TracebackException(
        type(failed.value), failed.value, below, capture_locals=True
    )
    text = "".join(shown.format())
    assert len(made) == 2 and not [s for s in made if s.hex() in text or repr(s) in text]


@pytest.mark.parametrize("value", [UUID(int=7), str(UUID(int=7)), str(UUID(int=7)).upper()])
def test_the_job_and_the_owner_are_recorded_as_canonical_uuid_text(value: object) -> None:
    _, _, named = signer.request("cv-audit-export-v1:" + "a" * 16, DIGEST, value, value)
    assert named == {"job_id": str(UUID(int=7)), "actor_user_id": str(UUID(int=7))}
