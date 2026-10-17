"""#2893 S5: the account-pack resolver answers from the root it is given.

The resolver moved from the test tree into the dev-only `cvdev` package, so a running stack serves
the same scenarios as the tests (ADR-0036). A stack may mount the pack anywhere, so its root is
explicit (`Pack(root)`): payloads stay inside the pack's parent (the pack and the shared corpus
beside it), the payload cache never answers one root with another root's file, and a scenario name
is never a path. Each pack here is a copy of the checkout's pack under `tmp_path`; every write
goes to a path built from `tmp_path`, never through a `Pack`, so a broken resolver cannot redirect
a write into the checkout.
"""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import pytest

from cvdev.account_fixture.pack import Pack, _payload, load, scenario_names
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
