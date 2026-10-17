"""#2893 S5: the account-pack resolver answers from the root it is given.

The resolver moved from the test tree into the dev-only `cvdev` package, so a running stack serves
the same scenarios as the tests (ADR-0036). A stack may mount the pack anywhere but at or directly
under a filesystem root, so its root is explicit (`Pack(root)`, resolved once): manifests stay
inside the pack, payloads inside the pack's parent (the pack and the shared corpus beside it), the
payload cache never answers one root with another root's file, and a scenario name is never a
path. Each pack here is a copy of the checkout's pack under `tmp_path`; every write goes to a path
built from `tmp_path`, never through a `Pack`, so a broken resolver cannot redirect a write into
the checkout.
"""

from __future__ import annotations

import ast
import json
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
    """ADR-0036 bans `candleviewer.secrets` and `candleviewer.audit` from `cvdev`: the resolver
    imports no `candleviewer` module and no sibling, so it reaches neither, even indirectly."""
    nodes = list(ast.walk(ast.parse(Path(resolver.__file__).read_text(encoding="utf-8"))))
    names = [alias.name for n in nodes if isinstance(n, ast.Import) for alias in n.names]
    names += ["." * n.level + (n.module or "") for n in nodes if isinstance(n, ast.ImportFrom)]

    assert [n for n in names if n.startswith(".") or n.partition(".")[0] == "candleviewer"] == []
