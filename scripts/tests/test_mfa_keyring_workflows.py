"""#2152 (BQ-12): every workflow that signs fixture users in on the real backend boots the API
with a file KEK of the run's own and both env auth keys. MFA has no keyring without a KEK since
the switch-over (every MFA sign-in would answer `503 auth_unavailable`), and the first boot imports
the two env keys as the testnet keyring, so the seeds `seed_fixture_user.py` sealed under the TOTP
one keep working (AC3, each night)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = (
    "e2e-auth-real.yml",
    "_dast-low-priv.yml",
    "dast-admin-nightly.yml",
    "perf-ingestion-nightly.yml",
)
KEK = '(umask 277 && openssl rand 32 > "$RUNNER_TEMP/cv-kek/kek")'


def _steps(name: str) -> list[dict[str, Any]]:
    doc = yaml.safe_load((ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8"))
    return [step for job in doc["jobs"].values() for step in job.get("steps", [])]


def _one(steps: list[dict[str, Any]], needle: str) -> dict[str, Any]:
    (found,) = [step for step in steps if needle in str(step.get("run", ""))]
    return found


@pytest.mark.parametrize("name", WORKFLOWS)
def test_the_api_boots_on_the_run_s_own_file_kek(name: str) -> None:
    steps = _steps(name)
    made = _one(steps, KEK)["run"]
    assert "umask 077" in made and '"$RUNNER_TEMP/cv-kek"' in made  # its directory, 0700
    for key in ("CV_AUTH_TOTP_KEY_HEX", "CV_AUTH_RECOVERY_HMAC_KEY_HEX"):  # both: an import
        assert re.search(rf"for name in [^;]*\b{key}\b[^;]*; do secret", made, re.DOTALL), key
    env = _one(steps, "python -m candleviewer.server")["env"]
    assert (env["CV_ENVIRONMENT"], env["CV_STORAGE_BACKEND"]) == ("testnet", "real")
    assert (env["CV_KEK_SOURCE"], env["CV_KEK_VERSION"]) == ("file", "1")
    assert env["CV_KEK_HANDLE"] == "${{ runner.temp }}/cv-kek/kek"


@pytest.mark.parametrize("name", WORKFLOWS)
def test_no_step_prints_the_kek(name: str) -> None:
    text = (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")
    assert text.count("cv-kek/kek") == 2  # made once, read once by the API (CV_KEK_HANDLE)
    assert not re.search(r"(cat|base64|xxd|od|hexdump|add-mask)\b[^\n]*cv-kek", text)


@pytest.mark.parametrize("name", WORKFLOWS)
def test_the_job_that_mints_the_kek_removes_it_whatever_the_run_did(name: str) -> None:
    """Its teardown, which always runs, removes the KEK's directory: a failed or cancelled run
    leaves no KEK file on the runner (as `e2e-auth-real.yml` did first)."""
    doc = yaml.safe_load((ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8"))
    jobs = [job.get("steps", []) for job in doc["jobs"].values()]
    (steps,) = [s for s in jobs if any(KEK in str(step.get("run", "")) for step in s)]
    (teardown,) = [step for step in steps if str(step.get("name", "")).startswith("Tear down")]
    assert teardown["if"] == "always()"
    assert re.search(r'^rm -rf [^\n]*"\$RUNNER_TEMP/cv-kek"', teardown["run"], re.MULTILINE)
