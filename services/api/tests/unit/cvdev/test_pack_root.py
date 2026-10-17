"""#2893 S5: the account-pack resolver answers from the root it is given.

The resolver moved from the test tree into the dev-only `cvdev` package, so a running stack serves
the same scenarios as the tests (ADR-0036). A stack may mount the pack anywhere but at or directly
under a filesystem root, so its root is explicit (`Pack(root)`, resolved once): manifests stay
inside the pack, payloads inside the pack's parent (the pack and the shared corpus beside it), the
payload cache never answers one root with another root's file, a scenario name is never a path and
an `extends` cycle is refused. Each pack here is a copy of the checkout's pack under `tmp_path`;
every write goes to a path built from `tmp_path`, never through a `Pack`, so a broken resolver
cannot redirect a write into the checkout.
"""

from __future__ import annotations

import ast
import json
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import pytest

from cvdev.account_fixture import pack as resolver
from cvdev.account_fixture.pack import _SCENARIO_NAME, Pack, _payload, load, scenario_names, schema
from tests._account_fixtures import PACK_ROOT

NOW: Final = datetime(2026, 10, 16, 9, 0, tzinfo=UTC)
#: The shared corpus beside the pack, relative to the pack's parent.
CORPUS: Final = Path("bybit") / "2026-10-05" / "rest"
SERVER_TIME: Final = "../bybit/2026-10-05/rest/server_time.json"
#: A module the resolver may not import: one of `candleviewer`, where ADR-0036's two banned modules
#: live, or of `cvdev`, whose other modules import `candleviewer` (`wiring` does).
BANNED_MODULE: Final = re.compile(r"(candleviewer|cvdev)(\.\w+)*")
#: The calls that import a module named at run time.
DYNAMIC_IMPORTS: Final = frozenset({"__import__", "import_module"})


def _copy_pack(fixtures: Path, *scenarios: str) -> Path:
    """Copy the checkout's pack, holding only `scenarios`, and the shared corpus into `fixtures`;
    returns the copy's pack root, `fixtures/accounts`."""
    accounts = fixtures / "accounts"
    shutil.copytree(PACK_ROOT / "_base", accounts / "_base")
    for name in scenarios:
        shutil.copytree(PACK_ROOT / name, accounts / name)
    shutil.copytree(PACK_ROOT.parent / CORPUS, fixtures / CORPUS)
    return accounts


def _edit(path: Path, **fields: Any) -> None:
    body = json.loads(path.read_text(encoding="utf-8"))
    path.write_text(json.dumps(body | fields), encoding="utf-8")


def _routes_to_candleviewer(source: str) -> list[str]:
    """What in `source` could import `candleviewer` or `cvdev`: an import statement naming either,
    any relative import, any `__import__` or `import_module` call (its target may be computed) and
    any string naming a module of either, as such a call would take it."""
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found += [alias.name for alias in node.names if BANNED_MODULE.fullmatch(alias.name)]
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level or BANNED_MODULE.fullmatch(module):
                found.append("." * node.level + module)
        elif isinstance(node, ast.Call):
            func = node.func
            callee = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
            if callee in DYNAMIC_IMPORTS:
                found.append(ast.unparse(node))
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if BANNED_MODULE.fullmatch(node.value):
                found.append(node.value)
    return found


def test_pack_root_is_configurable(tmp_path: Path) -> None:
    root = _copy_pack(tmp_path / "mounted", "compliant")
    _edit(tmp_path / "mounted" / CORPUS / "server_time.json", retMsg="from the mounted pack")

    pack = Pack(root)
    reply = load(pack, "compliant", now=NOW).reply("GET", "/v5/market/time")

    assert scenario_names(pack) == ["compliant"]
    assert reply.body["retMsg"] == "from the mounted pack"


def test_pack_root_is_resolved_once(tmp_path: Path) -> None:
    """Mounted through a link, the pack answers from the real directory, inside its boundaries."""
    real = _copy_pack(tmp_path / "fixtures", "compliant")
    (tmp_path / "mnt").mkdir()
    (tmp_path / "mnt" / "accounts").symlink_to(real, target_is_directory=True)

    pack = Pack(tmp_path / "mnt" / "accounts")

    assert pack.root == real.resolve()
    assert load(pack, "compliant", now=NOW).reply("GET", "/v5/market/time").body["retCode"] == 0


@pytest.mark.parametrize("below", ["", "accounts"], ids=["at", "directly-under"])
def test_pack_root_cannot_sit_at_or_directly_under_a_filesystem_root(
    tmp_path: Path, below: str
) -> None:
    """The pack's parent is its payload boundary: mounted at `/accounts`, any file would pass."""
    with pytest.raises(ValueError, match="filesystem root"):
        Pack(Path(tmp_path.anchor) / below)


@pytest.mark.parametrize(
    "ref", ["../../outside.json", "_base/outside.json"], ids=["dotdot", "symlink"]
)
def test_payload_outside_the_fixtures_root_is_refused(tmp_path: Path, ref: str) -> None:
    root = _copy_pack(tmp_path / "fixtures", "compliant")
    outside = tmp_path / "outside.json"
    shutil.copy(PACK_ROOT.parent / CORPUS / "server_time.json", outside)
    (root / "_base" / "outside.json").symlink_to(outside)

    with pytest.raises(ValueError, match="outside the fixtures package"):
        _payload(Pack(root), ref)


def test_payload_cache_is_keyed_by_root(tmp_path: Path) -> None:
    first = _copy_pack(tmp_path / "first", "compliant")
    second = _copy_pack(tmp_path / "second", "compliant")
    _edit(tmp_path / "second" / CORPUS / "server_time.json", retMsg="second root")

    assert _payload(Pack(first), SERVER_TIME)["retMsg"] == "OK"
    assert _payload(Pack(second), SERVER_TIME)["retMsg"] == "second root"


@pytest.mark.parametrize(
    "name",
    ["../planted", "compliant/../../planted", "{planted}"],
    ids=["parent", "nested", "absolute"],
)
def test_scenario_name_cannot_traverse(tmp_path: Path, name: str) -> None:
    root = _copy_pack(tmp_path / "fixtures", "compliant")
    planted = tmp_path / "fixtures" / "planted"
    shutil.copytree(root / "compliant", planted)

    with pytest.raises(ValueError, match="not a scenario name"):
        load(Pack(root), name.format(planted=planted), now=NOW)


def test_scenario_name_from_a_manifest_cannot_traverse(tmp_path: Path) -> None:
    root = _copy_pack(tmp_path / "fixtures", "compliant", "expired_key")
    shutil.copytree(root / "compliant", tmp_path / "fixtures" / "planted")
    _edit(root / "expired_key" / "manifest.json", extends="../planted")

    with pytest.raises(ValueError, match="not a scenario name"):
        load(Pack(root), "expired_key", now=NOW)


def test_scenario_directory_linked_outside_the_pack_is_refused(tmp_path: Path) -> None:
    root = _copy_pack(tmp_path / "fixtures", "compliant")
    shutil.copytree(root / "compliant", tmp_path / "planted")
    (root / "planted").symlink_to(tmp_path / "planted", target_is_directory=True)

    with pytest.raises(ValueError, match="outside the pack"):
        load(Pack(root), "planted", now=NOW)


def test_extends_cycle_is_found_by_directory_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A manifest that extends its own directory under another `scenario` name is a cycle, not an
    endless walk. Manifest reads are counted, so a walk that never ends fails instead of hanging."""
    root = _copy_pack(tmp_path / "fixtures", "compliant")
    shutil.copytree(root / "compliant", root / "loopy")
    _edit(root / "loopy" / "manifest.json", scenario="other", extends="loopy")
    read = resolver.manifest
    reads: list[str] = []

    def counted(pack: Pack, name: str) -> dict[str, Any]:
        reads.append(name)
        if len(reads) > 10:
            pytest.fail(f"the extends walk has not ended after {len(reads)} manifest reads")
        return read(pack, name)

    monkeypatch.setattr(resolver, "manifest", counted)

    with pytest.raises(ValueError, match="extends cycle through loopy"):
        load(Pack(root), "loopy", now=NOW)


def test_scenario_name_rule_is_the_schemas() -> None:
    pattern = schema(Pack(PACK_ROOT))["$defs"]["scenarioName"]["pattern"]
    assert pattern == f"^{_SCENARIO_NAME.pattern}$"


def test_exact_call_answers_before_the_wildcard() -> None:
    """In one manifest the exact call answers before `*` (README lookup rule): `live_key_on_demo`
    answers server time from its own exact entry and every other call with its `*` 10003."""
    scenario = load(Pack(PACK_ROOT), "live_key_on_demo", now=NOW)

    assert scenario.reply("GET", "/v5/market/time").body["retCode"] == 0
    assert scenario.reply("GET", "/v5/user/query-api").body["retCode"] == 10003


def test_resolver_imports_nothing_from_candleviewer() -> None:
    """ADR-0036 bans `candleviewer.secrets` and `candleviewer.audit` from `cvdev`. The resolver
    imports no `candleviewer` module and no other `cvdev` one, neither by an import statement nor
    through `__import__` or `importlib`, so nothing it imports reaches either."""
    source = Path(resolver.__file__).read_text(encoding="utf-8")

    assert _routes_to_candleviewer(source) == []


@pytest.mark.parametrize(
    "added",
    [
        pytest.param("from cvdev.account_fixture import wiring", id="sibling"),
        pytest.param("import cvdev.account_fixture.wiring", id="cvdev"),
        pytest.param("from .wiring import build", id="relative"),
        pytest.param("from candleviewer import settings", id="candleviewer"),
        pytest.param("importlib.import_module('cvdev.account_fixture.wiring')", id="importlib"),
        pytest.param("__import__('candleviewer.settings')", id="dunder"),
        pytest.param("importlib.import_module(f'{__package__}.wiring')", id="computed"),
        pytest.param("getattr(importlib, 'import_module')('candleviewer.settings')", id="string"),
    ],
)
def test_import_check_flags_each_route_to_candleviewer(added: str) -> None:
    """The check above, run on the resolver with one import added. The first, an absolute import of
    `wiring`, which imports `candleviewer`, once passed it."""
    source = Path(resolver.__file__).read_text(encoding="utf-8")

    assert _routes_to_candleviewer(f"{source}\n{added}\n") != []
