"""C-3.2 regression guard (#2234/#2236 review): only M2's public surface is imported outside
`secrets/`; the borrow capability is minted only in `admin/wiring.py` and consumed only by
`exchange/bybit/`; `admin` itself is injected metadata only."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import candleviewer.secrets as m2
from candleviewer.admin.wiring import SecretsHandle, SecretsMeta

_PKG = Path(__file__).resolve().parents[3] / "candleviewer"


from tests.unit.credentials_m2._m2_guard import (  # noqa: E402
    MINT_SITES,
    m2_violations,
)

_MINT_SITES = MINT_SITES


def _modules(root: Path = _PKG) -> list[Path]:
    """Every module outside the top-level `secrets/` package (only `parts[0]` is exempt)."""
    return [p for p in sorted(root.rglob("*.py")) if p.relative_to(root).parts[0] != "secrets"]


def _resolve(path: Path, node: ast.ImportFrom) -> str:
    if node.level == 0:
        return node.module or ""
    parts = list(path.relative_to(_PKG.parent).with_suffix("").parts)[: -node.level]
    return ".".join([*parts, *(node.module.split(".") if node.module else [])])


def _import_violations(path: Path, tree: ast.AST) -> list[str]:
    bad: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            bad += [a.name for a in node.names if a.name.startswith("candleviewer.secrets.")]
        elif isinstance(node, ast.ImportFrom):
            module, names = _resolve(path, node), {a.name for a in node.names}
            if module == "candleviewer.secrets":
                bad += sorted(n for n in names if n.startswith("_") or n not in m2.__all__)
                rel = str(path.relative_to(_PKG))
                if "mint_borrower" in names and rel not in _MINT_SITES:
                    bad.append(f"mint_borrower in {rel}")
            elif module.startswith("candleviewer.secrets."):
                bad.append(module)
    return bad


@pytest.mark.parametrize("path", _modules(), ids=lambda p: str(p.relative_to(_PKG)))
def test_only_public_m2_surface_imported(path: Path) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    assert not _import_violations(path, tree), path


@pytest.mark.parametrize(
    "src",
    [
        "from candleviewer.secrets import _metrics",
        "import candleviewer.secrets._metrics as m",
        "from candleviewer.secrets._kek import LoadedKek",
        "from ..secrets import _kek",
        "from candleviewer.secrets import mint_borrower",
    ],
)
def test_import_rule_rejects_private_m2_imports(src: str) -> None:
    assert _import_violations(_PKG / "admin" / "_probe.py", ast.parse(src)), src


def test_import_rule_accepts_public_surface() -> None:
    src = "from candleviewer.secrets import SecretsService"
    assert not _import_violations(_PKG / "admin" / "_probe.py", ast.parse(src))


def test_modules_exempts_only_top_level_secrets(tmp_path: Path) -> None:
    for rel in ("secrets/a.py", "oms/secrets/b.py", "oms/c.py"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text("", encoding="utf-8")
    got = {str(p.relative_to(tmp_path)) for p in _modules(tmp_path)}
    assert got == {"oms/secrets/b.py", "oms/c.py"}


@pytest.mark.parametrize("path", _modules(), ids=lambda p: str(p.relative_to(_PKG)))
def test_m2_guard_over_every_module(path: Path) -> None:
    rel = str(path.relative_to(_PKG))
    assert not m2_violations(rel, ast.parse(path.read_text(encoding="utf-8")))


#: #2893 (ADR-0036): the dev-only sibling package. A `cvdev/...` path matches no M2 site, so every
#: rule holds there in full (the import-linter root and its AST test keep `secrets` out as well).
_DEV = _PKG.parent / "cvdev"


@pytest.mark.parametrize(
    "path", sorted(_DEV.rglob("*.py")), ids=lambda p: str(p.relative_to(_DEV.parent))
)
def test_m2_guard_over_the_dev_package(path: Path) -> None:
    rel = str(path.relative_to(_DEV.parent))
    assert not m2_violations(rel, ast.parse(path.read_text(encoding="utf-8")))


def test_m2_guard_exempts_no_dev_package_path() -> None:
    probe = ast.parse("k = settings.bybit_api_key\n")
    assert m2_violations("cvdev/account_fixture/wiring.py", probe)


def test_lifecycle_protocol_has_no_metadata_or_borrow() -> None:
    members = {n for n in dir(SecretsHandle) if not n.startswith("_")}
    assert members == {"start", "stop", "health"}


def test_metadata_protocol_is_metadata_only() -> None:
    members = {n for n in dir(SecretsMeta) if not n.startswith("_")}
    assert members == {"verify_kek_possession", "rewrap_deks"}


def test_capability_objects_expose_only_their_members() -> None:
    """C-3.2 at runtime: `ctx.secrets` / `ctx.admin.secrets` are facades, not the service:
    their attribute surface is exactly the allowed members, with no broker/service field."""
    from candleviewer.app import build_app_context
    from candleviewer.secrets import SecretsService
    from candleviewer.settings import Settings

    ctx = build_app_context(Settings(_env_file=None))  # type: ignore[call-arg]
    for root, allowed in (
        (ctx.secrets, {"start", "stop", "health"}),
        (ctx.admin.secrets, {"verify_kek_possession", "rewrap_deks"}),
    ):
        assert not isinstance(root, SecretsService)
        assert {n for n in dir(root) if not n.startswith("__")} == allowed
        for name in allowed:  # plain closures, not bound methods of the service
            assert not hasattr(getattr(root, name), "__self__")


_PLANTED = "k = ctx.exchange_bybit._credentials._CredentialBorrower__borrow\n"


def test_guard_fails_planted_probe_file_on_disk(tmp_path: Path) -> None:
    """A planted file is found by `_modules()` and fails the guard (tmp_path, never the package)."""
    import textwrap

    probe = tmp_path / "oms" / "_r4_probe_tmp.py"
    probe.parent.mkdir()
    src = "async def probe(ctx, key_id, aad):\n" + textwrap.indent(_PLANTED, "    ")
    probe.write_text(src, encoding="utf-8")
    assert probe in _modules(tmp_path)
    assert m2_violations("oms/_r4_probe_tmp.py", ast.parse(probe.read_text(encoding="utf-8")))


async def test_borrower_exposes_no_broker_resolver() -> None:
    """The one signing capability holds a closure only: no `_resolve`/`_broker` attribute, no
    plaintext-yielding member (#2339: `sign` only), and the exchange adapter keeps it private."""
    from candleviewer.app import build_app_context
    from candleviewer.secrets import CredentialBorrower
    from candleviewer.settings import Settings

    ctx = build_app_context(Settings(_env_file=None))  # type: ignore[call-arg]
    borrower = ctx.exchange_bybit._credentials
    assert isinstance(borrower, CredentialBorrower)
    public = {n for n in dir(borrower) if not n.startswith("__")}
    assert public == {"sign", "_CredentialBorrower__borrow"}
    assert not hasattr(borrower, "_resolve") and not hasattr(borrower, "_broker")
    assert not hasattr(ctx.exchange_bybit, "credentials")


async def test_admin_metadata_cannot_decrypt_and_writes_no_borrow() -> None:
    """Exercising every member of the admin capability never yields plaintext."""
    from candleviewer.app import build_app_context
    from candleviewer.secrets import KekUnavailable
    from candleviewer.settings import Settings

    ctx = build_app_context(Settings(_env_file=None))  # type: ignore[call-arg]
    meta = ctx.admin.secrets
    assert meta is not None
    res = await meta.verify_kek_possession()
    assert res.kcv_ok is False
    with pytest.raises(KekUnavailable):
        await meta.rewrap_deks(2, actor_user_id="u", actor_role="owner")
