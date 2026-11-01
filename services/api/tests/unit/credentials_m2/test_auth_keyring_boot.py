"""The auth keyring at boot (#2152 S4; ADR-0009 Amendment 4, D3, BQ-2/4/6/7/8/9/14): dormant without
the composition seam; with it, opened, imported once or generated, re-wrapped at the rotation boot,
covered by the KCV trial, served through `AuthKeyring` and its wiring adapter, and never a reason
to latch order entry. On M2's in-memory stores with the fixed test KEKs and integer-built keys
(C-13.5); every keyring is made in-process, never a fixture."""

from __future__ import annotations

import asyncio
import copy
import gc
import pickle
import types
from base64 import b32encode, b64encode
from typing import Any
from uuid import UUID

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from structlog.testing import capture_logs

from candleviewer.admin.wiring import secrets_audit_row, secrets_bundle
from candleviewer.auth.errors import MfaKeyringUnavailable, MfaSealInvalid
from candleviewer.observability.health import HealthStatus
from candleviewer.secrets import _auth_custody as custody
from candleviewer.secrets import _auth_keyring as ak
from candleviewer.secrets import _envelope as env
from candleviewer.secrets import _export_custody
from candleviewer.secrets import _metrics as m
from candleviewer.secrets import service as service_module
from candleviewer.secrets._kek import LoadedKek
from candleviewer.secrets.errors import AuthKeyEnvForbidden, AuthKeyringUnavailable, AuthSealInvalid
from candleviewer.secrets.service import AuthKeyring, SecretsService, mint_auth_keyring
from candleviewer.secrets.store import (
    InMemoryAuthKeyStore,
    InMemoryCredentialStore,
    InMemoryExportKeyStore,
)
from tests.unit.credentials_m2._service_fakes import KEK_V3, _bound_sources, _ctx, _Src
from tests.unit.credentials_m2._vectors import KEK_V1, KEK_V2, AuditLog, kek

AK_T, AK_R = bytes(range(140, 172)), bytes(range(172, 204))  # the env keys an import reads
SEED, CODE = bytes(range(1, 21)), "-".join(["7K3M"] * 7)
ALICE, BOB = UUID(int=0xA11CE), UUID(int=0xB0B)
TOTP_HEX, RC_HEX = "auth_totp_key_hex", "auth_recovery_hmac_key_hex"
_OWNER = {"actor_kind": "system", "actor_role": "secrets"}
_ENV_KEYS: dict[str, Any] = {TOTP_HEX: AK_T.hex(), RC_HEX: AK_R.hex()}


def _service(
    cur: _Src, prev: _Src | None = None, *, keyring: InMemoryAuthKeyStore | None,
    store: InMemoryCredentialStore | None = None, audit: AuditLog | None = None,
    export_keys: Any = None,
) -> SecretsService:  # fmt: skip
    """The service as #2152's switch-over wires it: the keyring's store passed through the seam
    (`auth_keyring`) and counted by a re-wrap run (`auth_keys`); `keyring=None`, as `main` wires
    it today, leaves the keyring dormant."""
    st = store if store is not None else InMemoryCredentialStore()
    return SecretsService(
        store=st, kcv_store=st, audit=audit or AuditLog(), sources=_bound_sources(cur, prev),
        harden=lambda: True, auth_keys=keyring or InMemoryAuthKeyStore(), auth_keyring=keyring,
        export_keys=export_keys,
    )  # fmt: skip


async def _booted(
    keyring: InMemoryAuthKeyStore | None, cur: _Src, prev: _Src | None = None, *,
    store: InMemoryCredentialStore | None = None, audit: AuditLog | None = None,
    export_keys: Any = None, **settings: Any,
) -> tuple[SecretsService, Any]:  # fmt: skip
    svc = _service(cur, prev, keyring=keyring, store=store, audit=audit, export_keys=export_keys)
    ctx = _ctx(**settings)
    await svc.start(ctx)
    return svc, ctx


def _down(svc: SecretsService, ctx: Any) -> tuple[str, HealthStatus, bool, float]:
    """Why MFA is unavailable (`""` once it opens), health, the latch, and the page's gauge."""
    gauge = float(m.auth_keyring_unavailable_state._value.get())
    health = svc.health()
    return health.detail, health.status, ctx.oms_read_only_gate.is_read_only, gauge


async def _round_trip(cap: AuthKeyring) -> bool:
    blob, ref = await cap.seal_totp_seed(SEED, ALICE)
    return bytes(await cap.open_totp_seed(blob, ref, ALICE)) == SEED


async def _generated(
    env_name: str = "demo",
) -> tuple[InMemoryAuthKeyStore, InMemoryCredentialStore]:
    """An environment whose first boot, under KEK v1, generated its keyring."""
    keyring, store = InMemoryAuthKeyStore(env_name), InMemoryCredentialStore()
    await _booted(keyring, _Src(KEK_V1, 1), store=store, environment=env_name)
    return keyring, store


def _actions(keyring: InMemoryAuthKeyStore, audit: AuditLog) -> list[str]:
    """Every keyring record of a boot: those committed with a write, then the sink's."""
    sunk = [a for a in audit.actions() if a.startswith("security.auth_keyring_")]
    return [a for a, _ in keyring.audit] + sunk


# --- Dormant without the seam (BQ-7) --------------------------------------------------------------


async def test_without_the_seam_the_keyring_is_dormant(monkeypatch: pytest.MonkeyPatch) -> None:
    """As `main` wires M2 today: no keyring row is read or written, live still boots with both env
    keys set (today's required config), health and the gauge are unchanged, and the capability
    refuses every call."""

    async def unread(*_: object, **__: object) -> Any:
        raise AssertionError("the dormant keyring's store was read")

    counted = InMemoryAuthKeyStore("live")
    for name in ("rows_for", "insert_keyring", "count_mfa_material", "rewrap"):
        monkeypatch.setattr(counted, name, unread)
    m.auth_keyring_unavailable_state.set(0)
    svc = SecretsService(
        store=(st := InMemoryCredentialStore()), kcv_store=st, audit=(audit := AuditLog()),
        sources=_bound_sources(_Src(KEK_V1, 1)), harden=lambda: True, auth_keys=counted,
    )  # fmt: skip
    cap = mint_auth_keyring(svc)
    await svc.start(ctx := _ctx(environment="live", **_ENV_KEYS))
    assert _down(svc, ctx) == ("", HealthStatus.OK, False, 0) and counted.rows == []
    assert not [a for a in audit.actions() if a.startswith("security.auth_keyring_")]
    assert not await cap.available()
    with pytest.raises(AuthKeyringUnavailable, match=r"^auth_keyring_missing$"):
        await cap.seal_totp_seed(SEED, ALICE)


# --- Provisioning (Amendment 4 "Provisioning", D3, AC1, AC3, AC7, BQ-2) -------------------------


@pytest.mark.parametrize("env_name", ["live", "demo", "testnet"])
async def test_a_fresh_environment_generates_its_keyring_with_its_record(env_name: str) -> None:
    """AC1: two keys wrapped under the environment's KEK at its version, committed with
    `security.auth_keyring_enrolled`, which names ids, versions and the origin only."""
    keyring, audit = InMemoryAuthKeyStore(env_name), AuditLog()
    svc, ctx = await _booted(keyring, _Src(KEK_V1, 1), audit=audit, environment=env_name)
    assert _down(svc, ctx) == ("", HealthStatus.OK, False, 0)
    rows = {r["purpose"]: r for r in keyring.rows}
    shape = {(p, r["origin"], r["key_version"], r["kek_version"]) for p, r in rows.items()}
    assert shape == {("totp_seal", "generated", 1, 1), ("recovery_hmac", "generated", 1, 1)}
    ids = {
        "totp_seal_id": str(rows["totp_seal"]["id"]),
        "recovery_hmac_id": str(rows["recovery_hmac"]["id"]),
    }
    fields = _OWNER | {"env": env_name, "origin": "generated", "key_version": "1"}
    assert keyring.audit == [(custody.ENROLLED, fields | {"kek_version": "1"} | ids)]
    assert _actions(keyring, audit) == [custody.ENROLLED]  # no load record: nothing was loaded
    assert await _round_trip(mint_auth_keyring(svc))


async def test_a_later_boot_opens_the_keyring_with_its_record() -> None:
    keyring, store = await _generated()
    first = await _booted(keyring, _Src(KEK_V1, 1), store=store)
    blob, ref = await mint_auth_keyring(first[0]).seal_totp_seed(SEED, ALICE)
    audit = AuditLog()
    svc, ctx = await _booted(keyring, _Src(KEK_V1, 1), store=store, audit=audit)
    assert _down(svc, ctx) == ("", HealthStatus.OK, False, 0) and len(keyring.rows) == 2
    assert bytes(await mint_auth_keyring(svc).open_totp_seed(blob, ref, ALICE)) == SEED
    [(_, fields)] = [r for r in audit.records if r[0] == custody.LOADED]
    named = {r["purpose"] + "_id": str(r["id"]) for r in keyring.rows}
    assert fields == _OWNER | {"env": "demo", "origin": "generated", "key_version": "1",
                               "kek_version": "1"} | named  # fmt: skip


@pytest.mark.parametrize("env_name", ["demo", "testnet"])
async def test_the_first_boot_imports_both_env_keys_once(env_name: str) -> None:
    """AC3: imported as `imported_env` wraps with their record; a seed and a code made under the env
    keys keep working; a later boot with the settings still set warns, names them, ignores them."""
    keyring = InMemoryAuthKeyStore(env_name)
    keys: dict[str, Any] = {"environment": env_name, **_ENV_KEYS}
    store = InMemoryCredentialStore()
    svc, ctx = await _booted(keyring, _Src(KEK_V1, 1), store=store, **keys)
    assert _down(svc, ctx) == ("", HealthStatus.OK, False, 0)
    assert {r["origin"] for r in keyring.rows} == {"imported_env"}
    assert [a for a, _ in keyring.audit] == [custody.IMPORTED_ACTION]
    old = bytes(12) + AESGCM(AK_T).encrypt(bytes(12), SEED, None)  # today's no-AAD seal
    cap = mint_auth_keyring(svc)
    assert bytes(await cap.open_totp_seed(old, "local-dev-v1", ALICE)) == SEED
    assert len(await cap.recovery_code_digests(CODE, ALICE)) == 2  # the old digest is a candidate
    with capture_logs() as logs:
        again, ctx = await _booted(keyring, _Src(KEK_V1, 1), store=store, **keys)
    assert _down(again, ctx)[0] == "" and len(keyring.rows) == 2 and len(keyring.audit) == 1
    [warned] = [e for e in logs if e["event"] == "secrets.auth_keyring_env_settings_ignored"]
    assert (warned["log_level"], warned["settings"]) == ("warning", list(custody.SETTINGS))


@pytest.mark.parametrize(
    ("given", "missing"), [(TOTP_HEX, custody.SETTINGS[1]), (RC_HEX, custody.SETTINGS[0])]
)
async def test_one_env_setting_alone_is_missing_and_names_the_other(
    given: str, missing: str
) -> None:
    """BQ-2: both settings or neither. One alone generates and imports nothing."""
    keyring, audit = InMemoryAuthKeyStore(), AuditLog()
    with capture_logs() as logs:
        svc, ctx = await _booted(keyring, _Src(KEK_V1, 1), audit=audit, **{given: _ENV_KEYS[given]})
    assert _down(svc, ctx) == ("auth_keyring_missing", HealthStatus.DEGRADED, False, 1)
    assert (keyring.rows, keyring.audit) == ([], [])
    [named] = [e for e in logs if e["event"] == "secrets.auth_keyring_setting_missing"]
    assert (named["log_level"], named["missing"]) == ("critical", missing)
    assert audit.actions()[-1] == custody.LOAD_FAILED


async def test_material_without_a_keyring_is_never_generated_over() -> None:
    """AC7: no row, no setting, a TOTP method or an unused code in any environment: nothing is
    generated, MFA is `auth_keyring_missing`, and the remediation is logged and recorded."""
    keyring, audit = InMemoryAuthKeyStore(mfa_material=1), AuditLog()
    with capture_logs() as logs:
        svc, ctx = await _booted(keyring, _Src(KEK_V1, 1), audit=audit)
    assert _down(svc, ctx) == ("auth_keyring_missing", HealthStatus.DEGRADED, False, 1)
    assert (keyring.rows, keyring.audit) == ([], [])
    [paged] = [e for e in logs if e["event"] == "secrets.auth_keyring_unavailable"]
    text = service_module.AUTH_REMEDIATION.format(reason="auth_keyring_missing")
    assert (paged["log_level"], paged["remediation"]) == ("critical", text)
    record = {"env": "demo", "reason": "auth_keyring_missing", "remediation": text}
    assert audit.records[-1] == (custody.LOAD_FAILED, _OWNER | record)
    assert (await svc.verify_kek_possession()).kcv_ok  # the KEK is up: MFA alone is down (D4)


@pytest.mark.parametrize("keys", [{TOTP_HEX: AK_T.hex()}, {RC_HEX: AK_R.hex()}, _ENV_KEYS])
async def test_live_refuses_either_env_setting_before_any_kek_loads(keys: dict[str, Any]) -> None:
    """AC2's backstop in M2 (`Settings` refuses first, #2152's switch-over): fatal, as a refused
    KEK source is, and no KEK was ever loaded."""
    src, keyring = _Src(KEK_V1, 1), InMemoryAuthKeyStore("live")
    with pytest.raises(AuthKeyEnvForbidden):
        await _booted(keyring, src, environment="live", **keys)
    assert src.handed == [] and keyring.rows == []


# --- Fail closed, never regenerate (AC8, BQ-9) ----------------------------------------------------

#: Each leaves MFA `auth_keyring_mismatch`, the rows as they were and nothing generated (AC8).
TAMPERED: dict[str, Any] = {
    "one_row_gone": lambda rows: rows[:1],
    "swapped_wraps": lambda rows: [rows[0] | {"dek_ref": rows[1]["dek_ref"]}, rows[1]],
    "relabelled_version": lambda rows: [rows[0] | {"kek_version": 9}, rows[1]],
}


@pytest.mark.parametrize("case", sorted(TAMPERED))
async def test_a_tampered_keyring_fails_closed_and_is_never_regenerated_over(case: str) -> None:
    keyring, store = await _generated()
    keyring.rows = TAMPERED[case](keyring.rows)
    before = copy.deepcopy((keyring.rows, keyring.audit))
    svc, ctx = await _booted(keyring, _Src(KEK_V1, 1), store=store)
    assert _down(svc, ctx) == ("auth_keyring_mismatch", HealthStatus.DEGRADED, False, 1)
    assert (keyring.rows, keyring.audit) == before
    with pytest.raises(AuthKeyringUnavailable, match=r"^auth_keyring_mismatch$"):
        await mint_auth_keyring(svc).seal_totp_seed(SEED, ALICE)


async def _store_down(*_: object, **__: object) -> Any:
    raise RuntimeError("store down")


@pytest.mark.parametrize("step", ["rows_for", "count_mfa_material", "insert_keyring"])
async def test_a_store_that_fails_at_boot_degrades_mfa_alone(step: str) -> None:
    """A restart retries; the failure's class is logged, never a row (C-12.6). The KCV is enrolled
    already, so only the keyring's own step reads the table (the trial's is the next test's)."""
    store = InMemoryCredentialStore()
    await _booted(None, _Src(KEK_V1, 1), store=store)  # enrols v1's KCV, keyring dormant
    keyring = InMemoryAuthKeyStore()
    setattr(keyring, step, _store_down)
    with capture_logs() as logs:
        svc, ctx = await _booted(keyring, _Src(KEK_V1, 1), store=store)
    assert _down(svc, ctx) == ("auth_keyring_store_unavailable", HealthStatus.DEGRADED, False, 1)
    [failed] = [e for e in logs if e["event"] == "secrets.auth_keyring_store_failed"]
    assert (failed["log_level"], failed["error"]) == ("error", "RuntimeError")


async def test_an_insert_whose_record_is_not_written_is_an_audit_outage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """BQ-5: the keyring's record failed, so its rows rolled back with it: MFA is
    `auth_keyring_audit_unavailable` (M10's error told apart by its code), never a store outage,
    and the keyring made is zeroed."""
    made = await _opened_rings(monkeypatch)
    keyring = InMemoryAuthKeyStore()
    keyring.audit_fails = True
    with capture_logs() as logs:
        svc, ctx = await _booted(keyring, _Src(KEK_V1, 1))
    assert _down(svc, ctx) == ("auth_keyring_audit_unavailable", HealthStatus.DEGRADED, False, 1)
    assert (keyring.rows, keyring.audit) == ([], [])
    assert [made[0]._totp_key, made[0]._rc_key] == [bytearray(32)] * 2
    [failed] = [e for e in logs if e["event"] == "secrets.auth_keyring_store_failed"]
    assert failed["error"] == "_AuthKeyAuditNotWritten"


async def test_a_lost_insert_race_opens_the_winning_keyring(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Another boot stored its keyring between our read and our insert: ours is zeroed and never
    stored, and the winner's is opened like any loaded one."""
    winner_rows, winner = ak.generate_keyring(kek())
    keyring, made = InMemoryAuthKeyStore(), list[ak.LoadedAuthKeyring]()
    real_insert, real_generate = keyring.insert_keyring, ak.generate_keyring

    async def raced(records: Any, *, audit: Any) -> bool:
        await real_insert(winner_rows, audit=audit)  # the other boot commits first
        return await real_insert(records, audit=audit)

    def spied(k: LoadedKek) -> Any:
        out = real_generate(k)
        made.append(out[1])
        return out

    monkeypatch.setattr(keyring, "insert_keyring", raced)
    monkeypatch.setattr(custody, "generate_keyring", spied)
    audit = AuditLog()
    svc, _ = await _booted(keyring, _Src(KEK_V1, 1), audit=audit)
    blob, ref = winner.seal_totp_seed(SEED, ALICE)
    assert bytes(await mint_auth_keyring(svc).open_totp_seed(blob, ref, ALICE)) == SEED
    assert [made[0]._totp_key, made[0]._rc_key] == [bytearray(32)] * 2  # ours: zeroed
    assert [r["id"] for r in keyring.rows] == [r["id"] for r in winner_rows]
    assert custody.LOADED in audit.actions()


async def test_a_load_that_cannot_be_recorded_leaves_no_keyring_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A keyring is never used unrecorded: its load record lost, it is zeroed, MFA unavailable."""
    keyring, store = await _generated()
    opened = list[ak.LoadedAuthKeyring]()
    real = ak.load_keyring

    def spied(*args: Any, **kwargs: Any) -> ak.LoadedAuthKeyring:
        opened.append(real(*args, **kwargs))
        return opened[-1]

    monkeypatch.setattr(custody, "load_keyring", spied)

    class Lost(AuditLog):
        async def __call__(self, action: str, fields: dict[str, str]) -> None:
            if action == custody.LOADED:
                raise RuntimeError("audit down")
            await super().__call__(action, fields)

    svc, ctx = await _booted(keyring, _Src(KEK_V1, 1), store=store, audit=Lost())
    assert _down(svc, ctx) == ("auth_keyring_audit_unavailable", HealthStatus.DEGRADED, False, 1)
    assert not opened[0].available() and [opened[0]._totp_key] == [bytearray(32)]


# --- The rotation boot (Amendment 4 "KEK rotation", AC4, BQ-4) ------------------------------------


async def test_the_rotation_boot_rewraps_both_rows_with_their_records() -> None:
    """Each row moves to v2, its new wrap proven before the compare-and-set commits its record;
    seals made before keep opening, and after a restart without the previous handle too."""
    keyring, store = await _generated()
    first, _ = await _booted(keyring, _Src(KEK_V1, 1), store=store)
    blob, ref = await mint_auth_keyring(first).seal_totp_seed(SEED, ALICE)
    old = {r["id"]: r["dek_ref"] for r in keyring.rows}
    svc, ctx = await _booted(keyring, _Src(KEK_V2, 2), _Src(KEK_V1, 1), store=store)
    assert _down(svc, ctx) == ("", HealthStatus.OK, False, 0)
    assert {(r["kek_version"], r["dek_ref"] != old[r["id"]]) for r in keyring.rows} == {(2, True)}
    moved = [(a, f) for a, f in keyring.audit if a == custody.REWRAPPED]
    assert sorted((f["auth_key_id"], f["purpose"], f["from"], f["to"]) for _, f in moved) == sorted(
        (str(r["id"]), r["purpose"], "1", "2") for r in keyring.rows
    )
    alone, _ = await _booted(keyring, _Src(KEK_V2, 2), store=store)  # v1 is gone (AC4)
    assert bytes(await mint_auth_keyring(alone).open_totp_seed(blob, ref, ALICE)) == SEED


async def test_a_rewrap_that_fails_still_opens_under_the_previous_kek_and_is_counted() -> None:
    """BQ-4: the record of each move fails, so neither moves; the keyring opens under v1 on this
    boot, the step is counted and logged, the re-wrap run is never complete, and the next rotation
    strands it."""
    keyring, store = await _generated()
    keyring.audit_fails, audit = True, AuditLog()
    count = m.auth_keyring_boot_failures_total.labels(step="rewrap")
    before = count._value.get()
    with capture_logs() as logs:
        svc, ctx = await _booted(
            keyring, _Src(KEK_V2, 2), _Src(KEK_V1, 1), store=store, audit=audit
        )
    assert {r["kek_version"] for r in keyring.rows} == {1}
    assert _down(svc, ctx) == ("", HealthStatus.OK, False, 0) and count._value.get() == before + 2
    steps = [
        (e["step"], e["log_level"])
        for e in logs
        if e["event"] == "secrets.auth_keyring_boot_step_failed"
    ]
    assert steps == [("rewrap", "error")] * 2
    report = await svc.rewrap_deks(2, environment="demo", actor_user_id="o", actor_role="owner")
    assert (report.complete, audit.records[-1][1]["auth_left"]) == (False, "2")
    keyring.audit_fails = False
    svc, ctx = await _booted(keyring, _Src(KEK_V3, 3), _Src(KEK_V2, 2), store=store)
    assert _down(svc, ctx) == ("auth_keyring_stranded", HealthStatus.DEGRADED, False, 1)


async def test_a_new_wrap_not_proven_to_open_is_never_stored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The rotation boot's proof: a wrap under v2 that does not open to the key stores nothing."""
    keyring, store = await _generated()
    real = LoadedKek.unwrap_auth_key

    def broken(self: LoadedKek, ref: str, **kw: Any) -> bytearray:
        return bytearray(32) if self.version == 2 else real(self, ref, **kw)

    monkeypatch.setattr(LoadedKek, "unwrap_auth_key", broken)
    before = copy.deepcopy(keyring.rows)
    await _booted(keyring, _Src(KEK_V2, 2), _Src(KEK_V1, 1), store=store)
    assert keyring.rows == before and not [a for a, _ in keyring.audit if a == custody.REWRAPPED]


async def test_rows_left_at_an_older_version_without_its_kek_are_stranded() -> None:
    keyring, store = await _generated()
    await _booted(keyring, _Src(KEK_V2, 2), _Src(KEK_V1, 1), store=store)  # enrols v2's KCV
    for row in keyring.rows:
        row["kek_version"] = 1  # as if that boot's re-wrap had failed
    svc, ctx = await _booted(keyring, _Src(KEK_V2, 2), store=store)
    assert _down(svc, ctx) == ("auth_keyring_stranded", HealthStatus.DEGRADED, False, 1)


# --- The KCV trial (21 Sec.3.2.3a, BQ-4) ----------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "enrolled"), [(KEK_V1, True), (KEK_V2, False)], ids=["its_kek", "another_kek"]
)
async def test_an_auth_row_is_the_evidence_before_a_kcv_is_enrolled(
    raw: bytes, enrolled: bool
) -> None:
    """No API key row and no KCV at v1: the keyring's row at v1 must open under the KEK offered,
    else the boot is `kek_mismatch` and nothing is enrolled, so a wrong KEK never pins v1."""
    keyring, _ = await _generated()
    svc, ctx = await _booted(keyring, _Src(raw, 1), store=(fresh := InMemoryCredentialStore()))
    assert bool(fresh.kcvs) is enrolled
    if not enrolled:
        assert (svc.health().detail, ctx.oms_read_only_gate.is_read_only) == ("kek_mismatch", True)


async def test_an_unreadable_keyring_table_at_a_kcv_enrolment_is_a_kek_failure() -> None:
    """BQ-4, as the export key's (ADR-0039 decision 6): with no API key row as evidence, a KCV is
    never enrolled past a keyring table it cannot read: `kcv_store_unavailable`, latched."""
    keyring = InMemoryAuthKeyStore()
    setattr(keyring, "rows_for", _store_down)  # noqa: B010 -- a table that cannot be read
    svc, ctx = await _booted(keyring, _Src(KEK_V1, 1), store=(fresh := InMemoryCredentialStore()))
    assert (svc.health().detail, ctx.oms_read_only_gate.is_read_only, fresh.kcvs) == (
        "kcv_store_unavailable", True, {}
    )  # fmt: skip


# --- The capability and its lifecycle (BQ-6, BQ-9) ------------------------------------------------


def _reachable(cap: object) -> list[object]:
    """What the capability holds: its slots, and every cell of their closures but the service."""
    held = [getattr(cap, n) for n in dir(cap) if n.startswith("_AuthKeyring__")]
    held += [v for n, v in vars(cap).items()] if hasattr(cap, "__dict__") else []
    return held


async def test_the_capability_holds_closures_only_and_resolves_per_call() -> None:
    """Minted before `start()`: it refuses, then serves the keyring the boot opened, holding no
    keyring, service or broker of its own; masked, unpicklable and final."""
    keyring = InMemoryAuthKeyStore()
    svc = _service(_Src(KEK_V1, 1), keyring=keyring)
    cap = service_module.mint_auth_keyring(svc)  # the production mint, as wiring calls it
    assert not await cap.available()
    with pytest.raises(AuthKeyringUnavailable, match=r"^kek_unavailable$"):
        await cap.seal_totp_seed(SEED, ALICE)
    await svc.start(_ctx())
    assert await cap.available() and await _round_trip(cap)
    held = _reachable(cap)
    assert len(held) == 4 and all(isinstance(f, types.FunctionType) for f in held)
    rings = [
        o for o in gc.get_referents(cap) if isinstance(o, ak.LoadedAuthKeyring | SecretsService)
    ]
    assert rings == [] and repr(cap) == str(cap) == "***"
    with pytest.raises(TypeError):
        pickle.dumps(cap)
    with pytest.raises(TypeError, match="may not be subclassed"):
        type("Evil", (AuthKeyring,), {"__module__": "candleviewer.auth.evil"})


async def _opened_rings(monkeypatch: pytest.MonkeyPatch) -> list[ak.LoadedAuthKeyring]:
    """Every keyring the boot generates, as made (the test seam)."""
    made: list[ak.LoadedAuthKeyring] = []
    real = ak.generate_keyring

    def spied(k: LoadedKek) -> Any:
        out = real(k)
        made.append(out[1])
        return out

    monkeypatch.setattr(custody, "generate_keyring", spied)
    return made


async def test_stop_closes_the_keyring_and_the_capability_refuses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """BQ-9: `closed` at `stop()` is a 503, never a 500; both keys are zeroed with the KEKs."""
    made = await _opened_rings(monkeypatch)
    svc, _ = await _booted(InMemoryAuthKeyStore(), _Src(KEK_V1, 1))
    cap = mint_auth_keyring(svc)
    await svc.stop(1.0)
    assert [made[0]._totp_key, made[0]._rc_key] == [bytearray(32)] * 2
    assert not await cap.available()
    with pytest.raises(AuthKeyringUnavailable, match=r"^auth_keyring_closed$"):
        await cap.recovery_code_digests(CODE, ALICE)


async def test_a_boot_cancelled_after_the_keyring_opened_closes_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A KEK unpublished by a cancelled boot takes the keyring with it: zeroed, refused, latched."""
    made = await _opened_rings(monkeypatch)

    async def cancelled(*_: object) -> Any:
        raise asyncio.CancelledError

    monkeypatch.setattr(_export_custody, "open_at_boot", cancelled)
    svc = _service(
        _Src(KEK_V1, 1), keyring=InMemoryAuthKeyStore(), export_keys=InMemoryExportKeyStore()
    )
    cap, ctx = mint_auth_keyring(svc), _ctx()
    with pytest.raises(asyncio.CancelledError):
        await svc.start(ctx)
    assert [made[0]._totp_key, made[0]._rc_key] == [bytearray(32)] * 2
    assert ctx.oms_read_only_gate.is_read_only and not await cap.available()
    with pytest.raises(AuthKeyringUnavailable):
        await cap.seal_totp_seed(SEED, ALICE)


async def test_a_boot_closed_by_the_collector_after_the_keyring_opened_closes_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The collector's `GeneratorExit` at the export step: the KEKs zeroed without the guard's
    lock, as before the keyring, and the keyring zeroed with them."""
    made = await _opened_rings(monkeypatch)

    async def collected(*_: object) -> Any:
        raise GeneratorExit

    monkeypatch.setattr(_export_custody, "open_at_boot", collected)
    keys = InMemoryExportKeyStore()
    svc = _service(_Src(KEK_V1, 1), keyring=InMemoryAuthKeyStore(), export_keys=keys)
    with pytest.raises(GeneratorExit):
        await svc.start(_ctx())
    assert [made[0]._totp_key, made[0]._rc_key] == [bytearray(32)] * 2
    assert not await mint_auth_keyring(svc).available()


async def _raises(*_: object) -> Any:
    raise RuntimeError("a row M2 cannot read")


async def _no_reason(*_: object) -> Any:
    return None, None


@pytest.mark.parametrize(
    ("opened", "error"),
    [(_raises, ["RuntimeError"]), (_no_reason, [])],
    ids=["raises", "no_reason"],
)
async def test_an_open_that_fails_unexpectedly_is_unopenable_never_a_mismatch(
    monkeypatch: pytest.MonkeyPatch, opened: Any, error: list[str]
) -> None:
    """A row M2 cannot read is never a reason to stop the boot, nor to generate, nor to restore
    the rows from a backup (`_mismatch`'s remediation): MFA alone is `auth_keyring_unopenable`."""
    monkeypatch.setattr(custody, "open_at_boot", opened)
    audit = AuditLog()
    with capture_logs() as logs:
        svc, ctx = await _booted(InMemoryAuthKeyStore(), _Src(KEK_V1, 1), audit=audit)
    assert _down(svc, ctx) == ("auth_keyring_unopenable", HealthStatus.DEGRADED, False, 1)
    failed = [e for e in logs if e["event"] == "secrets.auth_keyring_open_failed"]
    assert [(e["log_level"], e["error"]) for e in failed] == [("error", e) for e in error]
    text = service_module.AUTH_REMEDIATION.format(reason="auth_keyring_unopenable")
    record = {"env": "demo", "reason": "auth_keyring_unopenable", "remediation": text}
    assert audit.records[-1] == (custody.LOAD_FAILED, _OWNER | record)
    assert "_unopenable: " in text and "keep the rows" in text


async def test_a_page_whose_record_is_lost_still_stands_and_is_counted() -> None:
    class Lost(AuditLog):
        async def __call__(self, action: str, fields: dict[str, str]) -> None:
            if action == custody.LOAD_FAILED:
                raise RuntimeError("audit down")
            await super().__call__(action, fields)

    lost = m.credential_outcome_audit_failures_total._value.get()
    keyring = InMemoryAuthKeyStore(mfa_material=1)
    svc, ctx = await _booted(keyring, _Src(KEK_V1, 1), audit=Lost())
    assert _down(svc, ctx) == ("auth_keyring_missing", HealthStatus.DEGRADED, False, 1)
    assert m.credential_outcome_audit_failures_total._value.get() == lost + 1


@pytest.mark.parametrize("value", ["zz", AK_T.hex()[2:]], ids=["not_hex", "31_bytes"])
async def test_a_malformed_env_setting_imports_nothing_and_shows_no_value(value: str) -> None:
    keyring = InMemoryAuthKeyStore()
    with capture_logs() as logs:
        settings: dict[str, Any] = {TOTP_HEX: value, RC_HEX: AK_R.hex()}
        svc, ctx = await _booted(keyring, _Src(KEK_V1, 1), **settings)
    assert _down(svc, ctx)[0] == "auth_keyring_missing" and keyring.rows == []
    [refused] = [e for e in logs if e["event"] == "secrets.auth_keyring_not_made"]
    assert (refused["settings"], refused["error"]) == (list(custody.SETTINGS), "ValueError")
    assert AK_T.hex()[2:] not in repr(logs) and AK_R.hex() not in repr(logs)


async def test_a_cancellation_in_the_kcv_trial_propagates_and_is_never_a_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    keyring, _ = await _generated()

    def cancelled(*_: object, **__: object) -> bytearray:
        raise asyncio.CancelledError

    monkeypatch.setattr(LoadedKek, "unwrap_auth_key", cancelled)
    svc, ctx = _service(_Src(KEK_V1, 1), keyring=keyring), _ctx()
    with pytest.raises(asyncio.CancelledError):
        await svc.start(ctx)
    assert (svc.health().detail, ctx.oms_read_only_gate.is_read_only) == ("kek_unavailable", True)


async def test_a_cancellation_at_the_load_record_zeroes_the_keyring(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    keyring, store = await _generated()
    opened: list[ak.LoadedAuthKeyring] = []
    real = ak.load_keyring

    def spied(*args: Any, **kwargs: Any) -> ak.LoadedAuthKeyring:
        opened.append(real(*args, **kwargs))
        return opened[-1]

    class Cancelled(AuditLog):
        async def __call__(self, action: str, fields: dict[str, str]) -> None:
            if action == custody.LOADED:
                raise asyncio.CancelledError
            await super().__call__(action, fields)

    monkeypatch.setattr(custody, "load_keyring", spied)
    svc = _service(_Src(KEK_V1, 1), keyring=keyring, store=store, audit=Cancelled())
    with pytest.raises(asyncio.CancelledError):
        await svc.start(_ctx())
    assert [opened[0]._totp_key, opened[0]._rc_key] == [bytearray(32)] * 2


def test_m2_alone_may_specialise_the_capability() -> None:
    inner = type("Inner", (AuthKeyring,), {"__module__": "candleviewer.secrets.probe"})
    assert issubclass(inner, AuthKeyring)


async def test_available_names_only_the_keys_this_keyring_holds() -> None:
    """BQ-6: metadata only. A generated keyring holds its own `akey:` ref alone; an imported one
    also the env key's `local-dev-v1`."""
    keyring, _ = await _generated()
    svc, _ = await _booted(keyring, _Src(KEK_V1, 1))
    cap, own = (
        mint_auth_keyring(svc),
        f"akey:{next(r['id'] for r in keyring.rows if r['purpose'] == 'totp_seal')}",
    )
    assert [await cap.available(*refs) for refs in ((), (own,), (own, own))] == [True] * 3
    assert not await cap.available(own, "local-dev-v1") and not await cap.available(f"akey:{BOB}")
    imported, _ = await _booted(InMemoryAuthKeyStore(), _Src(KEK_V1, 1), **_ENV_KEYS)
    assert await mint_auth_keyring(imported).available("local-dev-v1")


async def test_health_reads_the_keyring_after_the_kek_and_before_export() -> None:
    """BQ-14: KEK, stranded rows and rotation first, then the keyring, then the export key."""
    keyring = InMemoryAuthKeyStore(mfa_material=1)
    svc, ctx = await _booted(keyring, _Src(KEK_V1, 1))
    svc._export_reason = "export_key_unopenable"
    assert _down(svc, ctx)[:3] == ("auth_keyring_missing", HealthStatus.DEGRADED, False)
    svc._latched, svc._reason = True, "kek_rows_stranded"
    assert svc.health().detail == "kek_rows_stranded"


# --- The wiring adapter (BQ-6) and the records (BQ-8) ---------------------------------------------


async def test_the_wiring_adapter_maps_every_m2_refusal_with_nothing_chained() -> None:
    """`auth` sees its own errors: a 503's reason, a wrong code, a bad code; no M2 frame."""
    keyring, _ = await _generated()
    svc = _service(_Src(KEK_V1, 1), keyring=keyring)
    mfa = secrets_bundle(svc).mfa_keyring
    refused: list[BaseException] = []
    with pytest.raises(MfaKeyringUnavailable, match=r"^kek_unavailable$") as before_start:
        await mfa.seal_totp_seed(SEED, ALICE)
    refused.append(before_start.value)
    await svc.start(_ctx())
    blob, ref = await mfa.seal_totp_seed(SEED, ALICE)
    assert bytes(await mfa.open_totp_seed(blob, ref, ALICE)) == SEED and await mfa.available(ref)
    with pytest.raises(MfaSealInvalid) as moved:
        await mfa.open_totp_seed(blob, ref, BOB)  # AC9: another user's seal is a wrong code
    with pytest.raises(MfaKeyringUnavailable, match=r"^auth_key_not_held$") as not_held:
        await mfa.open_totp_seed(blob, "local-dev-v1", ALICE)  # AC6: never "no method"
    with pytest.raises(ValueError, match="too long"):
        await mfa.recovery_code_digests("A" * 513, ALICE)
    await svc.stop(1.0)
    with pytest.raises(MfaKeyringUnavailable, match=r"^auth_keyring_closed$") as closed:
        await mfa.recovery_code_digests(CODE, ALICE)
    refused += [moved.value, not_held.value, closed.value]
    assert [(e.__context__, e.__cause__) for e in refused] == [(None, None)] * 4


async def test_every_keyring_record_is_registered_and_kept_whole_at_its_severity() -> None:
    """Each record as the boot emits it, through the audit row builder: registered, `auth_key`,
    kept whole by the redactor (ids, purpose, versions, origin), the page's at error."""
    keyring, store = await _generated()  # enrolled
    audit = AuditLog()
    await _booted(
        keyring, _Src(KEK_V2, 2), _Src(KEK_V1, 1), store=store, audit=audit
    )  # loaded, rewrapped
    await _booted(InMemoryAuthKeyStore(mfa_material=1), _Src(KEK_V1, 1), audit=audit)  # load_failed
    await _booted((ring := InMemoryAuthKeyStore()), _Src(KEK_V1, 1), **_ENV_KEYS)  # imported
    emitted = dict(keyring.audit) | dict(ring.audit) | dict(audit.records)
    levels = dict.fromkeys((custody.ENROLLED, custody.IMPORTED_ACTION, custody.LOADED), "info")
    levels |= {custody.REWRAPPED: "info", custody.LOAD_FAILED: "error"}
    for action, severity in levels.items():
        row = secrets_audit_row("demo")(action, emitted[action])
        named = emitted[action].get("auth_key_id")
        assert (row["object_kind"], row["object_id"], row["severity"]) == (
            "auth_key",
            named,
            severity,
        )
        assert row["after_state"] == emitted[action], action


async def test_no_key_or_kek_reaches_a_log_a_record_or_a_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC13 for the boot: every key made here (captured as made, M2 zeroes its own), both env keys
    and both KEKs, raw, hex, base32 and base64, are in no log, record, health detail or failure."""
    made: list[bytes] = []
    real = env.new_dek

    def recorded() -> bytearray:
        out = real()
        made.append(bytes(out))
        return out

    monkeypatch.setattr(env, "new_dek", recorded)
    audit = AuditLog()
    with capture_logs() as logs:
        keyring, store = await _generated()
        svc, _ = await _booted(keyring, _Src(KEK_V2, 2), _Src(KEK_V1, 1), store=store, audit=audit)
        bad = InMemoryAuthKeyStore()
        bad.rows = [r | {"dek_ref": keyring.rows[0]["dek_ref"]} for r in keyring.rows]
        broken, _ = await _booted(bad, _Src(KEK_V2, 2), store=store, audit=audit)
        imported, _ = await _booted(InMemoryAuthKeyStore("testnet"), _Src(KEK_V1, 1),
                                    environment="testnet", audit=audit, **_ENV_KEYS)  # fmt: skip
    failures: list[BaseException] = []
    for cap in (mint_auth_keyring(broken), mint_auth_keyring(svc)):
        try:
            await cap.open_totp_seed(b"\x00" * 40, "akey:" + str(BOB), ALICE)
        except (AuthKeyringUnavailable, AuthSealInvalid) as exc:
            failures.append(exc)
    seen = repr((logs, keyring.audit, bad.audit, audit.records, svc.health(), broken.health(),
                 imported.health(), failures, [str(e) for e in failures]))  # fmt: skip
    forms = (bytes.hex, lambda b: b.hex().upper(), lambda b: b64encode(b).decode(),
             lambda b: b32encode(b).decode(), repr)  # fmt: skip
    secrets_made = [*made, AK_T, AK_R, KEK_V1, KEK_V2]
    assert len(made) == 2 and not [s for s in secrets_made for f in forms if f(s) in seen]
