"""`0019_snapshot_withdraw_transfer` (#2240): offline render, statement order, reversibility."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from candleviewer.accounts._permissions import FORBIDDEN_TOKENS

_ROOT = Path(__file__).resolve().parents[3]
_REV = "0019_snapshot_withdraw_transfer"
_0017_RULE = (
    "permission_snapshot ? 'permissions' AND permission_snapshot ? 'uid' "
    "AND jsonb_typeof(permission_snapshot->'permissions') = 'object' "
    "AND COALESCE(jsonb_array_length(permission_snapshot->'permissions'->'Withdraw'), 0) = 0"
)


def _parent() -> str:
    cfg = Config(str(_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_ROOT / "candleviewer/migrations"))
    script = ScriptDirectory.from_config(cfg).get_revision(_REV)
    assert script is not None and isinstance(script.down_revision, str)
    return script.down_revision


_PREV = _parent()


def _sql(*args: str) -> str:
    r = subprocess.run(  # noqa: S603 -- fixed argv, literal alembic subcommands, no shell
        [sys.executable, "-m", "alembic", *args, "--sql"],
        cwd=_ROOT, env={**os.environ}, capture_output=True, text=True, timeout=60,
    )  # fmt: skip
    assert r.returncode == 0, r.stderr
    return " ".join(r.stdout.split())


def _in_order(sql: str, steps: list[str]) -> bool:
    positions = [sql.index(step) for step in steps]
    return positions == sorted(positions)


def test_upgrade_adds_not_valid_then_validates_then_replaces() -> None:
    assert _in_order(
        _sql("upgrade", f"{_PREV}:{_REV}"),
        [
            "ALTER TABLE api_keys ADD CONSTRAINT ak_snapshot_shape_0019 CHECK (",
            ") NOT VALID;",
            "ALTER TABLE api_keys VALIDATE CONSTRAINT ak_snapshot_shape_0019;",
            "ALTER TABLE api_keys DROP CONSTRAINT ak_snapshot_shape;",
            "ALTER TABLE api_keys RENAME CONSTRAINT ak_snapshot_shape_0019 TO ak_snapshot_shape;",
        ],
    )


def test_upgrade_keeps_the_0017_rule_and_adds_three_scans_on_the_m13_tokens() -> None:
    sql = _sql("upgrade", f"{_PREV}:{_REV}")
    assert f"CHECK ( {_0017_RULE} AND jsonb_path_exists(" in sql
    assert sql.count(f'like_regex "{"|".join(FORBIDDEN_TOKENS)}" flag "i"') == 3
    assert sql.count(") IS FALSE") == 3


def test_downgrade_restores_the_0017_rule_the_same_way() -> None:
    sql = _sql("downgrade", f"{_REV}:{_PREV}")
    assert f"ADD CONSTRAINT ak_snapshot_shape_0017 CHECK ( {_0017_RULE} ) NOT VALID;" in sql
    assert "like_regex" not in sql
    assert _in_order(
        sql,
        [
            "ALTER TABLE api_keys VALIDATE CONSTRAINT ak_snapshot_shape_0017;",
            "ALTER TABLE api_keys DROP CONSTRAINT ak_snapshot_shape;",
            "ALTER TABLE api_keys RENAME CONSTRAINT ak_snapshot_shape_0017 TO ak_snapshot_shape;",
        ],
    )


@pytest.mark.parametrize(
    ("direction", "span"),
    [("upgrade", f"{_PREV}:{_REV}"), ("downgrade", f"{_REV}:{_PREV}")],
)
def test_alters_only_api_keys(direction: str, span: str) -> None:
    sql = _sql(direction, span)
    assert re.findall(r"ALTER TABLE (\S+)", sql) == ["api_keys"] * 4
    assert "audit" not in sql
