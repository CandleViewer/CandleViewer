"""Meta-tests for the burn-down dashboard (E47-Q04, BQ-09): counts match the sources, the page is clean."""

from __future__ import annotations

import datetime as dt
import json
import re
import sys
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.a11y import dashboard, store

ROOT = Path(__file__).resolve().parents[2]
FINDINGS = json.loads((ROOT / "docs/plan/a11y/findings.json").read_text(encoding="utf-8"))


def _seed(tmp_path: Path, sprints: int = 5) -> Path:
    for i in range(sprints):
        day = dt.date(2026, 10, 2) + dt.timedelta(days=7 * i)  # sprints 2..6
        base = {"source": "Q04", "tags": ["epic:E47"], "build": f"abcdef{i}", "recorded": day.isoformat()}
        res = [
            {**base, "kind": "axe", "screen": "R-001", "outcome": "fail" if i < 2 else "pass",
             "metrics": {"serious": 2 - i if i < 2 else 0, "critical": 0, "moderate": 5 - i, "minor": 1}},
            {**base, "kind": "lighthouse", "screen": "SCR-001", "outcome": "pass", "metrics": {"score": 0.96 + i / 100}},
            {**base, "kind": "lighthouse", "screen": "SCR-030", "outcome": "pending", "metrics": {}},
            {**base, "kind": "inventory", "screen": "*", "outcome": "pass", "metrics": {"mounted": 27 + i, "pending": 122 - i}},
        ]
        store.append_results(tmp_path, res, dt.date(2026, 11, 3))
    return tmp_path


class _Audit(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tags: Counter[str] = Counter()
        self.attrs: list[tuple[str, str]] = []
        self.captions = self.tables = self.scoped = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags[tag] += 1
        self.attrs += [(k, v or "") for k, v in attrs]
        self.tables += tag == "table"
        self.captions += tag == "caption"
        self.scoped += tag == "th" and ("scope", "col") in attrs or ("scope", "row") in attrs


def test_open_counts_match_the_findings_register() -> None:
    b = dashboard.burn_down(FINDINGS)
    want = Counter(f["severity"] for f in FINDINGS["findings"] if f["status"] in ("open", "in-progress"))
    assert {s: b["severity"][s]["open"] for s in ("serious", "moderate", "minor")} == {
        s: want[s] for s in ("serious", "moderate", "minor")}
    assert sum(c["open"] for c in b["severity"].values()) == sum(want.values())
    assert sum(c["open"] for c in b["sc"].values()) == sum(want.values())
    assert sum(v for c in b["screen"].values() for (st, _), v in c.items() if st == "open") == sum(want.values())


def test_page_states_the_register_total_and_every_open_screen() -> None:
    page = dashboard.render(FINDINGS, {})
    total = sum(1 for f in FINDINGS["findings"] if f["status"] in ("open", "in-progress"))
    assert f"{total} open accessibility defects" in page
    for f in FINDINGS["findings"]:
        if f["status"] in ("open", "in-progress"):
            assert f["screenId"] in page and f["wcagSc"] in page


def test_trend_shows_the_last_four_sprints_with_their_latest_values(tmp_path: Path) -> None:
    rows = dashboard.trend(store.load_store(_seed(tmp_path)), 4)
    assert [r["sprint"] for r in rows] == [3, 4, 5, 6]
    assert rows[0]["blocking"] == 1 and rows[-1]["blocking"] == 0
    assert rows[-1]["lh_min"] == 1.0 and rows[-1]["lh_pending"] == 1
    assert rows[-1]["mounted"] == 31 and rows[-1]["pending"] == 118
    page = dashboard.render(FINDINGS, store.load_store(tmp_path))
    assert "Sprint 06" in page and "Sprint 02" not in page and "4 of the last 4" in page


def test_trend_takes_the_latest_build_of_a_sprint_only(tmp_path: Path) -> None:
    base = {"source": "Q04", "kind": "axe", "screen": "R-001", "tags": ["epic:E47"], "recorded": "2026-11-03"}
    store.append_results(tmp_path, [{**base, "build": "aaaaaaa", "outcome": "fail", "metrics": {"serious": 9}}], dt.date(2026, 11, 3))
    store.append_results(tmp_path, [{**base, "build": "bbbbbbb", "outcome": "pass", "metrics": {"serious": 1}}], dt.date(2026, 11, 3))
    (row,) = dashboard.trend(store.load_store(tmp_path), 4)
    assert row["blocking"] == 1  # the later build by (recorded, build), not the sum of both


def test_an_empty_store_renders_not_recorded_instead_of_failing() -> None:
    page = dashboard.render(FINDINGS, {})
    assert "0 of the last 4 sprints recorded" in page and "None" in page


def test_page_is_structurally_accessible_and_self_contained() -> None:
    page = dashboard.render(FINDINGS, {})
    a = _Audit()
    a.feed(page)
    assert page.startswith("<!doctype html>") and '<html lang="en"' in page and "<title>" in page
    assert a.tags["h1"] == 1 and a.tags["main"] == 1 and a.tags["script"] == 0
    assert a.tables == a.captions >= 4 and a.scoped >= a.tables
    assert not [k for k, _ in a.attrs if k.startswith("on")]
    assert not re.search(r'(?:src|href)="https?:', page) and "@import" not in page
    assert 'name="viewport"' in page and "prefers-color-scheme" in page and 'href="#main"' in page
    levels = [int(t[1]) for t in re.findall(r"<(h[1-6])", page)]
    assert all(b - a_ <= 1 for a_, b in zip(levels, levels[1:]))  # no skipped heading level


def test_page_escapes_register_text() -> None:
    data = json.loads(json.dumps(FINDINGS))
    data["screens"][0]["name"] = "<img src=x onerror=alert(1)>"
    data["findings"][0].update(status="open", screenId=data["screens"][0]["id"])
    page = dashboard.render(data, {})
    assert "<img src=x" not in page and "&lt;img src=x onerror" in page


def test_cli_writes_the_page_and_a_broken_store_is_infra(tmp_path: Path) -> None:
    out = tmp_path / "d" / "dashboard.html"
    assert dashboard.main(["--out", str(out), "--store", str(_seed(tmp_path / "s"))]) == 0
    assert out.read_text(encoding="utf-8").startswith("<!doctype html>")
    (tmp_path / "bad").mkdir()
    (tmp_path / "bad" / "sprint-02.json").write_text("{}", encoding="utf-8")
    assert dashboard.main(["--out", str(out), "--store", str(tmp_path / "bad")]) == 3
