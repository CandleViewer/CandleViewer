"""Every Alembic revision id fits `alembic_version.version_num`, which is VARCHAR(32).

A longer id passes the revision's own DDL and then fails the stamp, `UPDATE alembic_version SET
version_num=...`, with SQLSTATE 22001: the whole migration fails and the head cannot advance. The id
first proposed for `0044_account_no_hard_delete` (#2758) had 37 characters. Owned here, for every
revision and tip-agnostic, like `test_single_head.py`, rather than copied into each revision's test.
"""

from __future__ import annotations

import ast
import warnings
from pathlib import Path

import pytest

_VERSIONS = Path(__file__).resolve().parents[3] / "candleviewer" / "migrations" / "versions"
_MAX_LENGTH = 32  # `alembic_version.version_num VARCHAR(32)`, Alembic's own DDL


def _revision_ids(directory: Path) -> dict[str, str]:
    """`{file name: its module-level revision id}`, read from the source, plain or annotated."""
    ids: dict[str, str] = {}
    for path in sorted(directory.glob("*.py")):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SyntaxWarning)  # a `\:` in 0001's SQL text
            tree = ast.parse(path.read_text(encoding="utf-8"))
        found = [
            node.value.value
            for node in tree.body
            if isinstance(node, ast.Assign | ast.AnnAssign)
            and _assigns_revision(node)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ]
        assert len(found) == 1, f"{path.name}: expected one string `revision`, found {found!r}"
        ids[path.name] = found[0]
    return ids


def _assigns_revision(node: ast.Assign | ast.AnnAssign) -> bool:
    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
    return any(isinstance(target, ast.Name) and target.id == "revision" for target in targets)


def _too_long(ids: dict[str, str]) -> list[str]:
    return [f"{name}: {len(rev)} characters" for name, rev in ids.items() if len(rev) > _MAX_LENGTH]


def test_every_revision_id_fits_alembics_version_column() -> None:
    ids = _revision_ids(_VERSIONS)
    assert "0001_identity_rbac_sessions_mfa" in ids.values()  # the scan sees the revisions
    assert _too_long(ids) == []


@pytest.mark.parametrize(
    ("assignment", "reported"),
    [
        pytest.param('revision: str = "' + "a" * 32 + '"', 0, id="annotated-at-the-limit"),
        pytest.param('revision: str = "' + "a" * 33 + '"', 1, id="annotated-one-over"),
        pytest.param('revision = "' + "a" * 33 + '"', 1, id="plain-one-over"),
    ],
)
def test_the_scan_reports_an_id_over_the_limit_and_only_that(
    tmp_path: Path, assignment: str, reported: int
) -> None:
    (tmp_path / "0001_x.py").write_text(assignment + "\n", encoding="utf-8")
    assert len(_too_long(_revision_ids(tmp_path))) == reported
