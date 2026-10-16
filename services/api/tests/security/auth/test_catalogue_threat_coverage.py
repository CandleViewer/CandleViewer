"""The abuse-case catalogue accounts for every E09-X01 threat (#298 AC1). QA verifies AC1 by a
literal search for each `U<n>` of the threat model in `docs/security/abuse-cases/e09-auth.md`, so a
threat added to X01 after the catalogue was written fails here, in CI, instead of at QA."""

from __future__ import annotations

import re
from pathlib import Path

_DOCS = Path(__file__).resolve().parents[5] / "docs" / "security"
_THREAT_MODEL = _DOCS / "threat-models" / "e09-auth-rbac.md"
_CATALOGUE = _DOCS / "abuse-cases" / "e09-auth.md"
_THREAT_ROW = re.compile(r"^\| (U\d+) \|", re.MULTILINE)  # first column of the threat tables


def test_catalogue_names_every_x01_threat_id() -> None:
    threats = set(_THREAT_ROW.findall(_THREAT_MODEL.read_text(encoding="utf-8")))
    catalogue = _CATALOGUE.read_text(encoding="utf-8")

    by_number = sorted(threats, key=lambda threat: int(threat[1:]))
    missing = [threat for threat in by_number if not re.search(rf"\b{threat}\b", catalogue)]

    assert len(threats) >= 33  # the tables were read: 33 ids when this test was written
    assert missing == [], f"no case, cross-check row or NOT RUN reason for {missing}"
