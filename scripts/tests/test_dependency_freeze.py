"""E43-T05: freeze invariants (SR-130, SR-134, SR-156)."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_accepted_risks_are_time_boxed_and_never_critical() -> None:
    doc = yaml.safe_load((ROOT / "security/accepted-risks.yaml").read_text(encoding="utf-8"))
    for e in doc["entries"]:
        assert e["severity"] in {"HIGH", "MEDIUM", "LOW"}, e["id"]  # never Critical (#3558)
        exp = (
            e["expires"]
            if isinstance(e["expires"], dt.date)
            else dt.date.fromisoformat(e["expires"])
        )
        assert exp <= dt.date(2027, 3, 25), e["id"]
        assert e["approver"] == "basiltt"


def test_tar_override_pinned_past_critical_advisory() -> None:
    assert 'tar: ">=7.5.21"' in (ROOT / "pnpm-workspace.yaml").read_text(encoding="utf-8")


def test_vitest_not_on_vulnerable_major() -> None:
    for pkg in list(ROOT.glob("apps/*/package.json")) + list(ROOT.glob("packages/*/package.json")):
        dev = json.loads(pkg.read_text(encoding="utf-8")).get("devDependencies", {})
        for name in ("vitest", "@vitest/coverage-v8"):
            if name in dev:
                assert dev[name] == "^3.2.6", (pkg, name)


def test_dependabot_sla_labels_present() -> None:
    text = (ROOT / ".github/dependabot.yml").read_text(encoding="utf-8")
    assert "sla/48h" in text and "sla/7d" in text


def test_unpinned_action_rule_and_fixture_exist() -> None:
    assert (ROOT / ".semgrep/cv-unpinned-action.yml").is_file()
    assert (ROOT / ".semgrep-fixtures/cv-unpinned-action.yml").is_file()


def test_known_vulnerable_dependency_without_exception_fails_gate() -> None:
    import sys

    sys.path.insert(0, str(ROOT))
    from tools.ci.security_gate import Finding, evaluate_findings, load_accepted_risks

    risks = load_accepted_risks(ROOT / "security/accepted-risks.yaml")
    f = Finding(
        tool="pip-audit",
        finding_id="GHSA-fixture-0000",
        severity="HIGH",
        package="fixture-vuln",
        detail="known vulnerable fixture",
    )
    result = evaluate_findings([f], risks, run_date=dt.date(2026, 10, 3))
    assert result.blocked and result.code == "CI-SEC-001"


def test_prohibited_licence_fails_gate_with_real_allowlist() -> None:
    import sys

    sys.path.insert(0, str(ROOT))
    from tools.ci.security_gate import (
        LicenseFinding,
        evaluate_licenses,
        load_license_allowlist,
    )

    allow = load_license_allowlist(ROOT / "tools/ci/licenses-allowlist.json")
    prohibited = allow["prohibited"]["licenses"][0]
    dep = LicenseFinding(package="fixture-prohibited", version="1.0.0", license=prohibited)
    result = evaluate_licenses([dep], allow, risks=[], run_date=dt.date(2026, 10, 3))
    assert result.blocked and result.code == "CI-SEC-002"


def test_prohibited_licence_message_names_package_and_licence() -> None:
    import sys

    sys.path.insert(0, str(ROOT))
    from tools.ci.security_gate import (
        LicenseFinding,
        evaluate_licenses,
        load_license_allowlist,
    )

    allow = load_license_allowlist(ROOT / "tools/ci/licenses-allowlist.json")
    prohibited = allow["prohibited"]["licenses"][0]
    dep = LicenseFinding(package="fixture-prohibited", version="1.0.0", license=prohibited)
    result = evaluate_licenses([dep], allow, risks=[], run_date=dt.date(2026, 10, 3))
    text = "\n".join(result.messages)
    assert "fixture-prohibited" in text and prohibited in text


def test_api_image_is_digest_pinned_and_non_root() -> None:
    """Static non-root check (the runtime probe is tools/ci/check_image_non_root.py, needs docker)."""
    lines = (ROOT / "infra/images/Dockerfile.api").read_text(encoding="utf-8").splitlines()
    froms = [x for x in lines if x.strip().upper().startswith("FROM ")]
    assert froms and all("@sha256:" in x for x in froms)
    users = [x.split()[1] for x in lines if x.strip().upper().startswith("USER ")]
    assert users and users[-1].split(":")[0] not in ("0", "root")


def test_frozen_lockfiles_are_integrity_pinned() -> None:
    """Frozen installs are byte-identical only if every entry carries a hash."""
    import re

    pnpm = (ROOT / "pnpm-lock.yaml").read_text(encoding="utf-8")
    assert pnpm.count("resolution: {integrity: sha512-") > 100
    assert not re.search(r"resolution: \{tarball:", pnpm)
    uv = (ROOT / "services/api/uv.lock").read_text(encoding="utf-8")
    assert uv.count('hash = "sha256:') > 50


def test_freeze_manifest_lock_hashes_match_committed_lockfiles() -> None:
    import hashlib

    lines = (ROOT / "security/freeze-manifest.sha256").read_text(encoding="utf-8").splitlines()
    got = {name: digest for digest, name in (ln.split("  ", 1) for ln in lines)}
    assert set(got) == {"pnpm-lock.yaml", "uv.lock", "pnpm-graph", "uv-graph"}
    for name, path in (("pnpm-lock.yaml", "pnpm-lock.yaml"), ("uv.lock", "services/api/uv.lock")):
        data = (ROOT / path).read_bytes().replace(b"\r\n", b"\n")
        assert hashlib.sha256(data).hexdigest() == got[name], name


def test_freeze_manifest_pnpm_graph_normalisation_drops_paths() -> None:
    import sys

    sys.path.insert(0, str(ROOT))
    from tools.ci.check_freeze_manifest import normalise_pnpm_graph

    a = normalise_pnpm_graph([{"name": "x", "path": "C:/a", "dependencies": {"y": {"path": "/b"}}}])
    b = normalise_pnpm_graph(
        [{"name": "x", "path": "/home/c", "dependencies": {"y": {"path": "/d"}}}]
    )
    assert a == b


def test_freeze_manifest_pnpm_graph_ignores_unsaved_hoisted_devdeps() -> None:
    """``unsavedDependencies`` reflects local install state, not the lockfile (#1737)."""
    import sys

    sys.path.insert(0, str(ROOT))
    from tools.ci.check_freeze_manifest import canonical_json, normalise_pnpm_graph

    fresh_ci = [{"name": "@cv/web", "dependencies": {"react": {"version": "18.3.1"}}}]
    dev_box = [
        {
            "name": "@cv/web",
            "dependencies": {"react": {"version": "18.3.1"}},
            "unsavedDependencies": {
                "husky": {"version": "9.1.7"},
                "prettier": {"version": "3.3.3"},
            },
            "deduped": True,
            "dedupedDependenciesCount": 3,
        }
    ]
    assert canonical_json(normalise_pnpm_graph(fresh_ci)) == canonical_json(
        normalise_pnpm_graph(dev_box)
    )


def test_freeze_manifest_pnpm_graph_hash_equal_for_windows_and_linux_inputs() -> None:
    import sys

    sys.path.insert(0, str(ROOT))
    from tools.ci.check_freeze_manifest import canonical_json, normalise_pnpm_graph

    win = [
        {
            "name": "x",
            "path": "C:/a",
            "z": 1,
            "a": "dir" + chr(92) + "sub" + chr(13) + chr(10) + "l",
            "b": [2, 1],
        }
    ]
    lin = [{"b": [1, 2], "a": "dir/sub" + chr(10) + "l", "z": 1, "path": "/home/c", "name": "x"}]
    assert canonical_json(normalise_pnpm_graph(win)) == canonical_json(normalise_pnpm_graph(lin))


def test_electron_toolchain_past_high_advisories() -> None:
    dev = json.loads((ROOT / "apps/desktop/package.json").read_text(encoding="utf-8"))[
        "devDependencies"
    ]
    assert dev["electron"] == "^41.10.7"
    assert dev["electron-builder"] == "^26.15.3"


# --- Dependabot-aware freeze flow (35-dependency-freeze-policy.md §2.1, Refs #1234) ----------


def _dependabot_updates() -> list[dict]:
    doc = yaml.safe_load((ROOT / ".github/dependabot.yml").read_text(encoding="utf-8"))
    assert doc["version"] == 2
    return doc["updates"]


def test_dependabot_every_ecosystem_is_weekly_grouped_and_labelled_dependencies() -> None:
    updates = _dependabot_updates()
    assert {u["package-ecosystem"] for u in updates} == {"github-actions", "pip", "npm", "docker"}
    for u in updates:
        assert u["schedule"]["interval"] == "weekly", u["package-ecosystem"]
        assert u.get("groups"), f"{u['package-ecosystem']} must be grouped (policy §2.1.1)"
        assert "dependencies" in u["labels"], u["package-ecosystem"]
        assert "security" in u["labels"], u["package-ecosystem"]


def test_dependabot_every_entry_waits_a_week_after_a_release() -> None:
    # #3672: a version pulled or found malicious soon after publishing is not proposed
    # (the Semgrep dependabot-missing-cooldown rule asks for default-days >= 7).
    for u in _dependabot_updates():
        # Exactly the default: a shorter per-semver override or an `exclude` would cut the wait.
        assert u["cooldown"] == {"default-days": 7}, (u["package-ecosystem"], u["directory"])


def test_dependabot_github_actions_bumps_carry_security_review_label() -> None:
    (gha,) = [u for u in _dependabot_updates() if u["package-ecosystem"] == "github-actions"]
    assert "security-review" in gha["labels"]


def test_dependabot_ignores_majors_on_pinned_runtime_sensitive_packages() -> None:
    (npm,) = [u for u in _dependabot_updates() if u["package-ecosystem"] == "npm"]
    ignored = {i["dependency-name"]: i.get("update-types") for i in npm["ignore"]}
    # npm majors are sequenced manually (#1819) until the Node 22 floor lands (#1778 F);
    # the wildcard subsumes the former size-limit / @size-limit/* entries.
    assert ignored["*"] == ["version-update:semver-major"]
    assert "pnpm" in ignored
    # only minor/patch flow automatically; no stale npm-major group may re-raise the bundle
    assert set(npm["groups"]) == {"npm-minor-patch"}
    assert npm["groups"]["npm-minor-patch"]["update-types"] == ["minor", "patch"]
    (pip,) = [u for u in _dependabot_updates() if u["directory"] == "/services/api"]
    assert "xstate-statemachine" in {i["dependency-name"] for i in pip["ignore"]}


def test_dependabot_docker_ignores_python_base_image_minor_and_major_only() -> None:
    # #3314 was declined and #3430 added the rule: the backend targets Python 3.12
    # (services/api/.python-version, the python:3.12-slim pin in infra/images/PINS.md), so
    # the `python` base image must not offer 3.13+ every week, while patch and digest
    # updates of the 3.12 line still arrive.
    (docker,) = [u for u in _dependabot_updates() if u["package-ecosystem"] == "docker"]
    assert docker["directory"] == "/infra/images"
    (python,) = [i for i in docker.get("ignore", []) if i["dependency-name"] == "python"]
    assert sorted(python["update-types"]) == [
        "version-update:semver-major",
        "version-update:semver-minor",
    ]
    assert "versions" not in python
    for rule in docker["ignore"]:
        # a rule without update-types ignores every update, digest refreshes included
        assert rule.get("update-types"), rule
        assert "version-update:semver-patch" not in rule["update-types"], rule


def test_license_scan_proposes_manifest_and_uploads_only_for_dependency_prs() -> None:
    text = (ROOT / ".github/workflows/_job-security.yml").read_text(encoding="utf-8")
    assert "check_freeze_manifest.py --propose freeze-manifest-proposal" in text
    assert "name: freeze-manifest-proposal" in text
    assert "github.actor == 'dependabot[bot]'" in text
    assert "contains(github.event.pull_request.labels.*.name, 'dependencies')" in text
    # never auto-commit: no push / commit step and no write permission in the lane
    assert "git push" not in text and "git commit" not in text
    assert "contents: write" not in text
    assert "pull_request_target" not in text
    # #3104: the freeze step is continue-on-error in a folded job, where failure() never fires.
    steps = [s for job in yaml.safe_load(text)["jobs"].values() for s in job["steps"]]
    (upload,) = [s for s in steps if s.get("with", {}).get("name") == "freeze-manifest-proposal"]
    assert "steps.freeze.outcome == 'failure'" in upload["if"] and "failure()" not in upload["if"]


def test_write_proposal_writes_manifest_diff_and_step_summary(tmp_path: Path, monkeypatch) -> None:
    import sys

    sys.path.insert(0, str(ROOT))
    from tools.ci.check_freeze_manifest import write_proposal

    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    expected = "aaa  pnpm-lock.yaml\nbbb  uv.lock\n"
    actual = "ccc  pnpm-lock.yaml\nbbb  uv.lock\n"
    out = tmp_path / "proposal"
    proposed = write_proposal(out, expected, actual)
    assert proposed == out / "freeze-manifest.sha256"
    assert proposed.read_text(encoding="utf-8") == actual
    diff = (out / "freeze-manifest.diff").read_text(encoding="utf-8")
    assert "-aaa  pnpm-lock.yaml" in diff and "+ccc  pnpm-lock.yaml" in diff
    body = summary.read_text(encoding="utf-8")
    assert "policy §2.1" in body and "Nothing was committed" in body and "+ccc" in body


def test_propose_mode_never_touches_committed_manifest_and_still_fails(
    tmp_path: Path, monkeypatch
) -> None:
    import sys

    sys.path.insert(0, str(ROOT))
    import tools.ci.check_freeze_manifest as m

    committed = tmp_path / "freeze-manifest.sha256"
    committed.write_text("old  pnpm-lock.yaml\n", encoding="utf-8")
    monkeypatch.setattr(m, "MANIFEST", committed)
    monkeypatch.setattr(m, "compute", lambda: {"pnpm-lock.yaml": "new"})
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    rc = m.main(["--propose", str(tmp_path / "out")])
    assert rc == 1
    assert committed.read_text(encoding="utf-8") == "old  pnpm-lock.yaml\n"
    assert (tmp_path / "out" / "freeze-manifest.sha256").read_text(encoding="utf-8") == (
        "new  pnpm-lock.yaml\n"
    )


def test_propose_mode_is_silent_when_manifest_matches(tmp_path: Path, monkeypatch) -> None:
    import sys

    sys.path.insert(0, str(ROOT))
    import tools.ci.check_freeze_manifest as m

    committed = tmp_path / "freeze-manifest.sha256"
    committed.write_text("same  pnpm-lock.yaml\n", encoding="utf-8")
    monkeypatch.setattr(m, "MANIFEST", committed)
    monkeypatch.setattr(m, "compute", lambda: {"pnpm-lock.yaml": "same"})
    assert m.main(["--propose", str(tmp_path / "out")]) == 0
    assert not (tmp_path / "out").exists()


def test_policy_doc_describes_propose_flow() -> None:
    text = (ROOT / "docs/plan/35-dependency-freeze-policy.md").read_text(encoding="utf-8")
    assert "### 2.1" in text and "--propose" in text and "freeze-manifest-proposal" in text


def test_http_cache_semantics_override_clears_high_advisory() -> None:
    root = Path(__file__).resolve().parents[2]
    assert "http-cache-semantics:" in (root / "pnpm-workspace.yaml").read_text(encoding="utf-8")
    lock = (root / "pnpm-lock.yaml").read_text(encoding="utf-8")
    assert "http-cache-semantics@4.2.0:" not in lock
    assert "http-cache-semantics@4.3.0:" in lock


def _locked_versions(name: str) -> set[tuple[int, ...]]:
    """Every version of `name` that pnpm-lock.yaml resolves, as integer tuples."""
    import re

    lock = (ROOT / "pnpm-lock.yaml").read_text(encoding="utf-8")
    keys = re.findall(rf"^  '?{re.escape(name)}@(\d+\.\d+\.\d+)'?:$", lock, re.MULTILINE)
    return {tuple(int(part) for part in key.split(".")) for key in keys}


def test_tinypool_and_source_map_js_overrides_clear_their_advisories() -> None:
    # #3494 (policy §8.4): tinypool <2.1.2 is Critical twice and source-map-js <1.2.2 is High.
    # vitest 3.2.7 asks for tinypool ^1.1.1 and no 1.x is fixed, so only the override fixes it.
    # postcss (^1.2.1) and magicast (^1.2.0) already accept source-map-js 1.2.2: that override
    # is a floor, without which a lockfile that pins 1.2.1 keeps it.
    overrides = yaml.safe_load((ROOT / "pnpm-workspace.yaml").read_text(encoding="utf-8"))
    assert overrides["overrides"]["tinypool"] == ">=2.1.2 <3"
    assert overrides["overrides"]["source-map-js"] == ">=1.2.2 <2"
    tinypool, source_map_js = _locked_versions("tinypool"), _locked_versions("source-map-js")
    assert tinypool and min(tinypool) >= (2, 1, 2)
    assert source_map_js and min(source_map_js) >= (1, 2, 2)
