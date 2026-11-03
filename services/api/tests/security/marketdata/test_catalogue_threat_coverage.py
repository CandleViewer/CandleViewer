"""E21-X02 (#652): the abuse-case catalogue accounts for every E21-X01 threat row and seed (the
E17-X02 pattern, `tests/security/ws/test_catalogue_threat_coverage.py`). Each `HM-xnn` row of the
model's §3 and each `AC-HM-nn` seed of its §7 has its own row in
`docs/security/abuse-cases/e21-dom-heatmap.md`: in the first column of its threat cross-check and
of its case table. A row or seed added to the model later fails here, in CI, not at QA."""

from __future__ import annotations

import re
from pathlib import Path

_DOCS = Path(__file__).resolve().parents[5] / "docs" / "security"
_THREAT_MODEL = _DOCS / "threat-models" / "e21-dom-heatmap.md"
_CATALOGUE = _DOCS / "abuse-cases" / "e21-dom-heatmap.md"
# the first column of §3's tables and of the cross-check; of §7's table and of the case table
_THREAT_ROW = re.compile(r"^\| (HM-[STRIDE]\d{2}) +\|", re.MULTILINE)
_SEED_ROW = re.compile(r"^\| (AC-HM-\d{2}) +\|", re.MULTILINE)


def _ids(path: Path, row: re.Pattern[str]) -> set[str]:
    return set(row.findall(path.read_text(encoding="utf-8")))


def test_every_e21_threat_row_has_its_catalogue_row() -> None:
    threats = _ids(_THREAT_MODEL, _THREAT_ROW)
    assert len(threats) >= 33  # HM-S01 to HM-E05 when this test was written
    missing = sorted(threats - _ids(_CATALOGUE, _THREAT_ROW))
    assert missing == [], "no case, test or NOT RUN row for these"


def test_every_ac_hm_seed_has_its_case_row() -> None:
    seeds = _ids(_THREAT_MODEL, _SEED_ROW)
    assert len(seeds) >= 19  # AC-HM-01 to AC-HM-19 when this test was written
    missing = sorted(seeds - _ids(_CATALOGUE, _SEED_ROW))
    assert missing == [], "no case row for these"
