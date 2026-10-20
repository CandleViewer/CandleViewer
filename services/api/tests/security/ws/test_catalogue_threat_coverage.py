"""The abuse-case catalogue accounts for every E17-X01 threat and seed (#415, E17-X02: the suite is
"mapped one-to-one against E17-X01's threats", and every threat without an executed case is a gap in
this ticket, not in the model). Each `WS-xnn` row and `AC-nn` seed of the threat model must have its
own row in `docs/security/abuse-cases/e17-ws.md`: in the first column of its cross-check table and
of its case table. A row or seed added to the model after the catalogue was written fails here, in
CI, instead of at QA, and so does one whose catalogue row was deleted while another row still names
its id (the E09-X02 pattern, by row)."""

from __future__ import annotations

import re
from pathlib import Path

_DOCS = Path(__file__).resolve().parents[5] / "docs" / "security"
_THREAT_MODEL = _DOCS / "threat-models" / "E17-ws-gateway.md"
_CATALOGUE = _DOCS / "abuse-cases" / "e17-ws.md"
# the first column of §3's tables and of the cross-check; of §7's table and of the case table
_THREAT_ROW = re.compile(r"^\| (WS-[STRIDE]\d{2}) +\|", re.MULTILINE)
_SEED_ROW = re.compile(r"^\| (AC-\d{2}) +\|", re.MULTILINE)


def _ids(path: Path, row: re.Pattern[str]) -> set[str]:
    return set(row.findall(path.read_text(encoding="utf-8")))


def test_every_x01_threat_id_has_its_cross_check_row() -> None:
    threats = _ids(_THREAT_MODEL, _THREAT_ROW)

    assert len(threats) >= 52  # the tables were read: 52 ids when this test was written
    missing = sorted(threats - _ids(_CATALOGUE, _THREAT_ROW))
    assert missing == [], "no case, test or NOT RUN row for these"


def test_every_x01_abuse_case_seed_has_its_case_row() -> None:
    seeds = _ids(_THREAT_MODEL, _SEED_ROW)

    assert len(seeds) >= 31  # AC-01 to AC-31 when this test was written
    missing = sorted(seeds - _ids(_CATALOGUE, _SEED_ROW))
    assert missing == [], "no case row for these"
