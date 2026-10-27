"""#2848: the E09-Q05 k6 auth profile's lane (perf-ingestion-nightly.yml, job auth-k6) and script.

The lane runs only on a dispatch with profile=auth, never on a schedule or a pull request, and no
required check reads it. These pin what its header claims: read-only permissions, no repository
secret, k6 installed exactly as the full pack installs it, a loopback target, the perf switch on a
keyless testnet only, and a users file built from the seeds seed_fixture_user.py wrote. The script
posts the contract's bodies and keeps no session-cache control (ADR-0010 addendum).
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "perf-ingestion-nightly.yml"
SCRIPT = ROOT / "tests" / "load" / "k6" / "auth.js"


def _doc() -> dict[Any, Any]:
    doc: dict[Any, Any] = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return doc


def _job() -> dict[str, Any]:
    job: dict[str, Any] = _doc()["jobs"]["auth-k6"]
    return job


def _step(prefix: str) -> dict[str, Any]:
    return next(s for s in _job()["steps"] if s.get("name", "").startswith(prefix))


def test_auth_k6_runs_on_a_dispatch_with_profile_auth_only() -> None:
    profile = _doc()[True]["workflow_dispatch"]["inputs"]["profile"]  # YAML 1.1 reads `on` as True
    assert profile["options"] == ["smoke", "full", "auth"] and profile["default"] == "smoke"
    assert _job()["if"] == "github.event_name == 'workflow_dispatch' && inputs.profile == 'auth'"
    assert "pull_request" not in _doc()[True]


def test_auth_k6_reads_no_secret_and_widens_no_permission() -> None:
    job = _job()
    assert "permissions" not in job and _doc()["permissions"] == {"contents": "read"}
    assert "secrets." not in yaml.safe_dump(job)
    assert _job()["steps"][0]["with"] == {"persist-credentials": False}
    for step in job["steps"]:
        if "uses" in step:
            assert re.fullmatch(r"[\w./-]+@[0-9a-f]{40}", step["uses"]), step["uses"]
        assert "${{" not in step.get("run", "")  # nothing is interpolated into a script


def test_auth_k6_installs_k6_as_the_full_pack_does() -> None:
    full = _doc()["jobs"]["perf-pack-full"]
    name = "Install the pinned k6 (sha256 verified twice)"
    theirs = next(s for s in full["steps"] if s.get("name") == name)
    assert _step(name) == theirs
    keys = ("K6_VERSION", "K6_SHA256", "K6_NO_USAGE_REPORT", "K6_AUTO_EXTENSION_RESOLUTION")
    assert {k: _job()["env"][k] for k in keys} == {k: full["env"][k] for k in keys}


def test_auth_k6_targets_loopback_with_the_perf_switch_on_a_keyless_testnet() -> None:
    assert _job()["env"]["BASE_URL"] == "http://127.0.0.1:8000"
    api = _step("Start the API")["env"]
    assert api["CV_AUTH_PERF_ENABLED"] == "true" and api["CV_ENVIRONMENT"] == "testnet"
    assert not [k for k in yaml.safe_dump(_job()).split() if k.startswith("CV_BYBIT")]
    assert _step("Migrate, then seed")["env"] == {"CV_ENVIRONMENT": "testnet"}


def test_auth_k6_gates_on_the_scripts_thresholds() -> None:
    step = _step("E09-Q05 k6 auth profile")
    assert step["run"].startswith("k6 run ") and step["run"].endswith(" tests/load/k6/auth.js")
    assert "continue-on-error" not in step and "if" not in step


def test_the_users_file_lists_each_seeded_identifier_with_its_seed(tmp_path: Path) -> None:
    run = _step("Migrate, then seed")["run"]
    builder = run.split("<<'PY'\n", 1)[1].split("\nPY\n", 1)[0]
    for i in (1, 2):
        (tmp_path / f"perf-{i}.totp").write_text(f"SEED{i}AAAAAAAAAAA\n", encoding="ascii")
    out = subprocess.run(
        [sys.executable, "-I", "-c", builder, str(tmp_path), "ab12", "2"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert json.loads(out) == [
        {"identifier": "perf-ab12-1", "totp_seed": "SEED1AAAAAAAAAAA"},
        {"identifier": "perf-ab12-2", "totp_seed": "SEED2AAAAAAAAAAA"},
    ]
    assert 'CV_SEED_USERNAME="perf-$suffix-$i"' in run  # the identifiers the builder names


def test_the_script_posts_the_contract_bodies_and_no_cache_control() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "identifier: user.identifier, password: PASSWORD" in text  # LoginRequest
    assert 'mfa_token: mfaToken, method: "totp", code' in text  # MfaVerifyRequest
    assert "code, password: PASSWORD, challenge_id: challengeId" in text  # authStepUp
    assert "username" not in text and "CV_CACHE_DISABLED" not in text
    assert not re.search(r"\b(warm|cold)\b", text)
