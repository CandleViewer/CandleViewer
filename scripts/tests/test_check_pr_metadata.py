"""Unit tests for tools/ci/check_pr_metadata.py (#2249). Fixture event JSONs under tmp_path."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.ci import check_pr_metadata as m  # noqa: E402

GOOD_TITLE = "ci(infra-devops): add pr-metadata gate"
GOOD_BODY = "Implements C-4.8.\n\nCloses #2249\n"


def event(title=GOOD_TITLE, body=GOOD_BODY, labels=()):
    return {"pull_request": {"title": title, "body": body, "labels": [{"name": n} for n in labels]}}


def run(ev, numstat="1\t1\tsrc/a.py\n"):
    rr = m._load_rule_refs(ROOT)
    return m.check(
        ev,
        numstat,
        (ROOT / ".gitattributes").read_text(encoding="utf-8"),
        (ROOT / "commitlint.config.cjs").read_text(encoding="utf-8"),
        rr.load_declared_ids(str(ROOT)),
        rr.RULE_ID_RE,
    )


def codes(errs):
    return [e.split()[0] for e in errs]


def test_clean_pr_passes():
    assert run(event()) == ([], [])


def test_size_warns_above_400():
    errs, warns = run(event(), "401\t0\tsrc/a.py\n")
    assert errs == [] and len(warns) == 1


def test_size_fails_above_800_without_label():
    errs, _ = run(event(), "801\t0\tsrc/a.py\n")
    assert codes(errs) == ["PR-SIZE-001"]


def test_size_800_boundary_ok_and_label_allows():
    assert run(event(), "800\t0\tsrc/a.py\n")[0] == []
    errs, warns = run(event(labels=["large-pr-approved"]), "900\t0\tsrc/a.py\n")
    assert errs == [] and warns


def test_generated_and_lockfiles_excluded():
    ns = (
        "5000\t0\tpackages/protocol/src/generated/x.ts\n"
        "3000\t10\tpnpm-lock.yaml\n"
        "-\t-\tlogo.png\n"
        "10\t0\tapps/web/uv.lock\n"
        "20\t5\tsrc/a.py\n"
    )
    loc, excl = m.count_loc(ns, m.generated_patterns((ROOT / ".gitattributes").read_text()))
    assert loc == 25 and excl == 8020
    assert run(event(), ns)[0] == []


def test_rename_uses_new_path():
    loc, _ = m.count_loc("1\t1\tsrc/{a => b}/c.py\n", [])
    assert loc == 2


def test_title_not_conventional():
    assert codes(run(event(title="Add stuff"))[0]) == ["PR-TITLE-001"]


def test_title_bad_type_and_scope():
    assert codes(run(event(title="wip(infra-devops): x"))[0]) == ["PR-TITLE-002"]
    assert codes(run(event(title="ci(nonsense): x"))[0]) == ["PR-TITLE-003"]
    assert codes(run(event(title="feat(oms-execution)!: x"))[0]) == []


def test_title_missing_scope():
    assert codes(run(event(title="ci: x"))[0]) == ["PR-TITLE-001"]


def test_body_requires_link():
    assert codes(run(event(body="no link"))[0]) == ["PR-BODY-001"]
    assert run(event(body="Refs #12"))[0] == []
    assert codes(run(event(body=None))[0]) == ["PR-BODY-001"]


def test_dangling_rule_reference_in_body_and_title():
    errs, _ = run(event(title="ci(docs): per C-99.99", body="C-4.7 and C-88.1\nCloses #1"))
    assert codes(errs) == ["PR-RULE-001", "PR-RULE-001"]
    assert "C-4.7" not in " ".join(errs)


def test_main_with_event_file_and_numstat(tmp_path, capsys):
    ev = tmp_path / "event.json"
    ev.write_text(json.dumps(event()), encoding="utf-8")
    ns = tmp_path / "numstat.txt"
    ns.write_text("900\t0\tsrc/a.py\n", encoding="utf-8")
    assert m.main(["--event", str(ev), "--repo-root", str(ROOT), "--numstat-file", str(ns)]) == 1
    ns.write_text("3\t0\tsrc/a.py\n", encoding="utf-8")
    assert m.main(["--event", str(ev), "--repo-root", str(ROOT), "--numstat-file", str(ns)]) == 0
    assert "ok" in capsys.readouterr().out
