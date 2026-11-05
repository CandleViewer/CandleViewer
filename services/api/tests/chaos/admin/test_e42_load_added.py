"""E42-Q03 (#1216) part 4 self-tests: SCR-143's added load and the workflow's part 4 profiles.

No network, no stack. Pins the windows and reads of `lib/loadPlan.js` against the judge (its tests
are `test_e42_load_judge.py`'s) and D05, the driver reading no WAL for it, and `perf-admin.yml`'s
part 4 wiring: the profiles, the chained-only rule run as the workflow's own step, the Managers
seeded with no grant, and the WAL path handed to the driver.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

from bench.admin import REPO, load, load_harness, run
from tests.chaos.admin.test_e42_harness_guards import K6, _node

load_results = load_harness("load_results")
WORKFLOW = REPO / ".github/workflows/perf-admin.yml"


def test_the_added_windows_and_reads_are_the_judges_and_d05s() -> None:
    body = (
        "{w: t.ADDED_WINDOWS, s: t.ADDED_WINDOW_S, lim: t.ADDED_LIMIT, noise: t.NOISE_LIMIT,"
        " reads: t.MOUNT_READS, n: t.ADDED_SESSIONS, re: t.REREAD_S,"
        " at: [0, 599, 600, 4799, 4800].map((x) => t.windowAt(x)),"
        " cpu: t.cpuSeconds('# x\\nprocess_cpu_seconds_total 12.5\\nother 1\\n'),"
        " none: t.cpuSeconds('other 1')}"
    )
    t = _node(K6 / "lib/loadPlan.js", body)
    r = load_results
    assert (t["w"], t["s"], t["lim"], t["noise"]) == (list(r.ADDED_WINDOWS), r.ADDED_WINDOW_S,
                                                      r.ADDED_LIMIT, r.NOISE_LIMIT)  # fmt: skip
    assert t["at"] == ["aa_1", "aa_1", "aa_2", "b_3", None] and (t["n"], t["re"]) == (5, 10)
    assert (t["cpu"], t["none"]) == (12.5, None)
    d05 = (REPO / "docs/design/E42/E42-D05.md").read_text()
    for read in t["reads"]:
        assert read.split("?")[0] in d05 and read.split("?")[-1].split("=")[-1] in d05
    assert load.ADDED_TIMEOUT_S > len(t["w"]) * t["s"]
    src = (K6 / "added_load.js").read_text()
    assert "${BASE}/metrics" in src and "9108" not in src  # the API's own port, never another's
    assert 'send("sub", { topics: [{ ch: "system" }] })' in src


def test_the_added_load_reads_no_wal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("CV_ADMIN_PERF_DSN", "postgresql://cv:pw@127.0.0.1:55432/admin_perf1m_test")
    monkeypatch.setenv("CV_ENVIRONMENT", "testnet")
    monkeypatch.delenv(load.WAL_ENV, raising=False)  # C-1216P4-06: not needed for `added`
    argv = ["added", "--out", str(tmp_path / "o"), "--base-url", "http://127.0.0.1:58000"]
    assert run.main([*argv, "--dry-run"]) == 0
    assert json.loads(capsys.readouterr().out)["wal_dir"] is None
    assert load.run_sampled([sys.executable, "-c", "pass"], {}, tmp_path, None) == 0
    assert not (tmp_path / load_results.WAL_JSON).exists()


def _job() -> dict[Any, Any]:
    return dict(yaml.safe_load(WORKFLOW.read_text())["jobs"]["admin-perf"])


def _step(prefix: str) -> str:
    return str(next(s["run"] for s in _job()["steps"] if s.get("name", "").startswith(prefix)))


@pytest.mark.parametrize(
    ("profile", "dataset", "ok"),
    [("audit", "bulk", True), ("flood", "chained", True), ("export", "bulk", False),
     ("added", "bulk", False), ("nope", "chained", False)],
)  # fmt: skip
def test_the_workflow_runs_part_4_profiles_on_the_chained_set_only(
    tmp_path: Path, profile: str, dataset: str, ok: bool
) -> None:
    on = yaml.safe_load(WORKFLOW.read_text())[True]["workflow_dispatch"]["inputs"]
    assert on["profile"]["options"] == ["audit", *load.SCRIPTS]
    env = {"PROFILE": profile, "DATASET": dataset, "RUNS": "1", "ROWS": ""}
    env |= {"GITHUB_ENV": str(tmp_path / "env"), "PATH": "/usr/bin:/bin"}
    done = subprocess.run(  # noqa: S603 - fixed argv; the script is the workflow's own step
        ["/bin/bash", "-c", _step("Check the inputs")], env=env, capture_output=True, text=True,
        timeout=30, check=False,
    )  # fmt: skip
    assert (done.returncode == 0) is ok, done.stderr


def test_the_workflow_seeds_managers_with_no_grant_and_hands_the_wal_to_the_driver() -> None:
    job = _job()
    assert int(job["env"]["OWNERS"]) >= 6 and int(job["env"]["MANAGERS"]) >= 6
    seed = _step("Migrate, load the dataset")
    assert "seed_fixture_user.py --role manager" in seed and re.search(r"managers\.json", seed)
    perf = _step("Admin perf")
    assert 'CV_AUDIT_WAL_PATH="$RUNNER_TEMP/cv/audit/audit.wal"' in perf
    assert 'export CV_AUDIT_WAL_PATH="$RUNNER_TEMP/cv/audit/audit.wal"' in _step("Start the API")
    assert "CV_ADMIN_MANAGERS_FILE=" in perf
    assert '--base-url "http://127.0.0.1:${CV_BIND_PORT}"' in perf
    assert '--secret-file "$RUNNER_TEMP/cv/*.totp"' in _step("No credential")  # the Managers' too
