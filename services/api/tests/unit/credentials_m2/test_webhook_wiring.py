"""The alert webhook's capabilities as `admin.wiring` mints them (#1400 S3, ADR-0009 Amendment 9):
`alerts`' ports over M2's, served by a started service and refused without a KEK; and the mint
site, pinned to `admin/wiring.py` once per capability (BQ-02's rider: a second site fails)."""

from __future__ import annotations

import ast
import hashlib
import hmac
from pathlib import Path
from uuid import UUID

import pytest

from candleviewer.admin.wiring import SecretsBundle, secrets_bundle
from candleviewer.alerts.ports import WebhookSealerPort, WebhookSignerPort, WebhookTargetOpenerPort
from candleviewer.secrets import SecretsService, WebhookCapabilityRefused
from candleviewer.secrets._kek import LoadedKek
from candleviewer.secrets.store import InMemoryAuthKeyStore, InMemoryExportKeyStore
from tests.unit.credentials_m2._m2_guard import MINT_SITES, MINTS, PKG, m2_violations
from tests.unit.credentials_m2._service_fakes import _ctx, _Src, _svc
from tests.unit.credentials_m2._vectors import KEK_V1, AuditLog

ALERT = UUID("00000000-0000-4000-8000-0000000c0de5")
URL = "https://hooks.example.test/a/receiver"
SECRET = b"synthetic wiring test secret, never a key, 01"
BODY = b'{"alert_id":"00000000-0000-4000-8000-0000000c0de5","event":"alert.fired"}'
WEBHOOK_MINTS = ("mint_webhook_sealer", "mint_webhook_opener", "mint_webhook_signer")


def _ports(
    bundle: SecretsBundle,
) -> tuple[WebhookSealerPort, WebhookTargetOpenerPort, WebhookSignerPort]:
    """The bundle's members as `alerts`' ports: mypy checks they conform, with no import edge."""
    return bundle.webhook_sealer, bundle.webhook_opener, bundle.webhook_signer


async def _started() -> tuple[SecretsBundle, SecretsService]:
    svc = _svc(
        _Src(KEK_V1, 1), audit=AuditLog(), auth_keys=InMemoryAuthKeyStore(),
        export_keys=InMemoryExportKeyStore(),
    )  # fmt: skip
    await svc.start(_ctx())
    return secrets_bundle(svc), svc


async def test_the_bundle_seals_opens_and_signs_once_started() -> None:
    bundle, svc = await _started()
    sealer, opener, signer = _ports(bundle)
    target, secret = await sealer.seal_target(URL, ALERT), await sealer.seal_secret(SECRET, ALERT)
    assert await opener.open_target(target, ALERT) == URL
    sig = await signer.sign_delivery(secret, ALERT, 9, 1_767_225_600, hashlib.sha256(BODY).digest())
    signed = f"cv.alert.webhook.v1:1767225600:9:{hashlib.sha256(BODY).hexdigest()}".encode()
    assert hmac.compare_digest(sig, hmac.new(SECRET, signed, hashlib.sha256).hexdigest())
    await svc.stop(1.0)
    with pytest.raises(WebhookCapabilityRefused, match=r"^kek_unavailable$"):
        await opener.open_target(target, ALERT)  # the KEK went with stop(): nothing opens


async def test_the_bundle_refuses_every_call_before_start() -> None:
    sealer, opener, signer = _ports(secrets_bundle(SecretsService()))
    digest = hashlib.sha256(BODY).digest()
    for call in (
        sealer.seal_target(URL, ALERT),
        sealer.seal_secret(SECRET, ALERT),
        opener.open_target(b"x" * 100, ALERT),
        signer.sign_delivery(b"x" * 100, ALERT, 1, 1, digest),
    ):
        with pytest.raises(WebhookCapabilityRefused) as info:
            await call
        assert info.value.reason == "kek_unavailable"


# --- the mint site ---------------------------------------------------------------------------


def _mint_calls(trees: dict[str, ast.AST]) -> dict[str, list[str]]:
    """Each webhook mint's call sites, by file, across the given modules; a call through an
    aliased import (`from … import mint_webhook_signer as m`) counts as the mint's."""
    sites: dict[str, list[str]] = {name: [] for name in WEBHOOK_MINTS}
    for rel, tree in trees.items():
        aliases = {
            alias.asname: alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
            for alias in node.names
            if alias.asname and alias.name in sites
        }
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                fn = node.func
                name = fn.id if isinstance(fn, ast.Name) else getattr(fn, "attr", "")
                name = aliases.get(name, name)
                if name in sites:
                    sites[name].append(rel)
    return sites


def _package() -> dict[str, ast.AST]:
    return {
        str(p.relative_to(PKG)): ast.parse(p.read_text(encoding="utf-8"))
        for p in sorted(PKG.rglob("*.py"))
        if p.relative_to(PKG).parts[0] != "secrets"
    }


def test_each_webhook_capability_is_minted_once_in_wiring() -> None:
    assert set(WEBHOOK_MINTS) <= MINTS and MINT_SITES == {"admin/wiring.py"}
    assert _mint_calls(_package()) == {name: ["admin/wiring.py"] for name in WEBHOOK_MINTS}


@pytest.mark.parametrize("mint", WEBHOOK_MINTS)
def test_a_second_mint_site_fails(mint: str) -> None:
    """A second call in wiring itself fails the count; one anywhere else fails the M2 guard too."""
    trees = _package()
    wiring = trees["admin/wiring.py"]
    assert isinstance(wiring, ast.Module)
    second = ast.parse(f"again = {mint}(svc)\n")
    trees["admin/wiring.py"] = ast.Module(body=[*wiring.body, *second.body], type_ignores=[])
    assert _mint_calls(trees)[mint] == ["admin/wiring.py", "admin/wiring.py"]
    elsewhere = f"from candleviewer.secrets import {mint}\nsigner = {mint}(svc)\n"
    assert m2_violations("alerts/dispatcher.py", ast.parse(elsewhere))
    assert m2_violations("app.py", ast.parse(elsewhere))


@pytest.mark.parametrize("mint", WEBHOOK_MINTS)
def test_an_aliased_second_mint_is_counted(mint: str) -> None:
    trees = _package()
    wiring = trees["admin/wiring.py"]
    assert isinstance(wiring, ast.Module)
    second = ast.parse(f"from candleviewer.secrets import {mint} as m\nagain = m(svc)\n")
    trees["admin/wiring.py"] = ast.Module(body=[*wiring.body, *second.body], type_ignores=[])
    assert _mint_calls(trees)[mint] == ["admin/wiring.py", "admin/wiring.py"]


async def test_the_service_holds_the_brokers_guard_across_each_wrap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """C-2.7, Amendment 9: every wrap and unwrap runs under `broker._guard`, so no `drop_kek`
    zeroes the KEK mid-wrap (#913 L3b)."""
    bundle, svc = await _started()
    guard = svc._require()._guard
    seen: list[bool] = []
    real_wrap, real_unwrap = LoadedKek.wrap_webhook_dek, LoadedKek.unwrap_webhook_dek

    def wrap(self: LoadedKek, dek: bytearray, *, alert_id: UUID, field: str) -> bytes:
        seen.append(guard.locked())
        return real_wrap(self, dek, alert_id=alert_id, field=field)

    def unwrap(self: LoadedKek, wrapped: bytes, *, alert_id: UUID, field: str) -> bytearray:
        seen.append(guard.locked())
        return real_unwrap(self, wrapped, alert_id=alert_id, field=field)

    monkeypatch.setattr(LoadedKek, "wrap_webhook_dek", wrap)
    monkeypatch.setattr(LoadedKek, "unwrap_webhook_dek", unwrap)
    sealer, opener, signer = _ports(bundle)
    target, secret = await sealer.seal_target(URL, ALERT), await sealer.seal_secret(SECRET, ALERT)
    assert await opener.open_target(target, ALERT) == URL
    await signer.sign_delivery(secret, ALERT, 1, 1, hashlib.sha256(BODY).digest())
    assert seen == [True, True, True, True] and not guard.locked()
    await svc.stop(1.0)


@pytest.mark.parametrize(
    "src",
    [
        "dek = kek.unwrap_webhook_dek(blob, alert_id=a, field='secret')",
        "ref = kek.wrap_webhook_dek(dek, alert_id=a, field='url')",
        "aad = env.webhook_aad('demo', a, 'secret')",
        "aad = env.webhook_dek_aad('demo', a, 'secret', 1)",
        "s = signer._WebhookSigner__sign",
    ],
)
def test_the_m2_guard_pins_the_webhook_last_hops(src: str) -> None:
    assert m2_violations("alerts/webhook.py", ast.parse(src)), src


def test_alerts_holds_no_m2_import() -> None:
    root = PKG / "alerts"
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith("candleviewer.secrets"), path
            elif isinstance(node, ast.Import):
                assert not any(a.name.startswith("candleviewer.secrets") for a in node.names)
    assert Path(root / "ports.py").is_file()
