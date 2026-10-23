"""Tests for tools/ci/prepull_images.sh (#4301, CI-INFRA-001): a fake `docker` on PATH, no network."""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "tools" / "ci" / "prepull_images.sh"
DIGEST = "f" * 8 + "1" * 56
OTHER = "e" * 8 + "2" * 56
HUB = f"postgres:16-alpine@sha256:{DIGEST}"
ECR = "public.ecr.aws/docker/library/postgres"

FAKE_DOCKER = r"""#!/bin/bash
# Fake docker. State lives in $FAKE/: calls.log, hub_pulls, ecr_pulls, served, tagged.
echo "$*" >> "$FAKE/calls.log"
count() { n=$(cat "$FAKE/$1" 2>/dev/null || echo 0); echo $((n + 1)) > "$FAKE/$1"; echo $((n + 1)); }
case "$1 $2" in
  "pull --quiet")
    ref=$3
    if [[ $ref == public.ecr.aws/* ]]; then
      n=$(count ecr_pulls)
      [ "${MIRROR_OK:-1}" = 1 ] || { echo "mirror down" >&2; exit 1; }
      echo "${MIRROR_SERVES:-${ref##*@sha256:}}" > "$FAKE/served"
      echo "${ref%%@*}" > "$FAKE/served_repo"
    else
      n=$(count hub_pulls)
      [ "$n" -gt "${HUB_FAILS:-0}" ] || { echo "token service timed out" >&2; exit 1; }
      echo "${ref##*@sha256:}" > "$FAKE/served"
      echo "${ref%%@*}" > "$FAKE/served_repo"
    fi
    echo "$ref"
    ;;
  "tag "*)
    echo "$3" >> "$FAKE/tagged"
    ;;
  "image inspect")
    if [ "$3" = "--format" ]; then
      echo "$(cat "$FAKE/served_repo" | sed 's/:[^:/]*$//')@sha256:$(cat "$FAKE/served")"
    else
      grep -qx "$3" "$FAKE/tagged" 2>/dev/null
    fi
    ;;
  *) echo "unexpected docker call: $*" >&2; exit 99 ;;
esac
"""


@pytest.fixture
def env(tmp_path: Path) -> dict[str, str]:
    bindir = tmp_path / "bin"
    bindir.mkdir()
    fake = bindir / "docker"
    fake.write_text(FAKE_DOCKER, encoding="utf-8")
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    state = tmp_path / "state"
    state.mkdir()
    return {
        "PATH": f"{bindir}:{os.environ['PATH']}",
        "FAKE": str(state),
        "PREPULL_BACKOFF": "0 0 0 0",
        "GITHUB_STEP_SUMMARY": str(tmp_path / "summary.md"),
    }


def _run(
    tmp_path: Path, env: dict[str, str], listing: str, *names: str, **extra: str
) -> subprocess.CompletedProcess[str]:
    lst = tmp_path / "prepull.txt"
    lst.write_text(listing, encoding="utf-8")
    compose = tmp_path / "compose.yml"
    compose.write_text(
        "services:\n  q:\n    image: questdb/questdb:8.1.1@sha256:" + DIGEST + "\n",
        encoding="utf-8",
    )
    return subprocess.run(
        ["bash", str(SCRIPT), "--list", str(lst), "--compose", str(compose), *names],
        env={**env, **extra},
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def _count(env: dict[str, str], name: str) -> int:
    p = Path(env["FAKE"]) / name
    return int(p.read_text()) if p.exists() else 0


def _summary(env: dict[str, str]) -> str:
    return Path(env["GITHUB_STEP_SUMMARY"]).read_text(encoding="utf-8")


PG = f"postgres {HUB} {ECR}:16-alpine@sha256:{DIGEST}\n"


def test_hub_succeeds_first_try_and_tags_locally(tmp_path: Path, env: dict[str, str]) -> None:
    r = _run(tmp_path, env, PG, "postgres")
    assert r.returncode == 0, r.stderr
    assert _count(env, "hub_pulls") == 1 and _count(env, "ecr_pulls") == 0
    assert "postgres:16-alpine" in (Path(env["FAKE"]) / "tagged").read_text()
    assert "Docker Hub" in _summary(env) and f"sha256:{DIGEST}" in _summary(env)


def test_hub_fails_then_works_within_five_attempts(tmp_path: Path, env: dict[str, str]) -> None:
    r = _run(tmp_path, env, PG, "postgres", HUB_FAILS="4")
    assert r.returncode == 0, r.stderr
    assert _count(env, "hub_pulls") == 5 and _count(env, "ecr_pulls") == 0
    assert "Docker Hub" in _summary(env)


def test_hub_always_fails_mirror_serves(tmp_path: Path, env: dict[str, str]) -> None:
    r = _run(tmp_path, env, PG, "postgres", HUB_FAILS="99")
    assert r.returncode == 0, r.stderr
    assert _count(env, "hub_pulls") == 5 and _count(env, "ecr_pulls") == 1
    assert "postgres:16-alpine" in (Path(env["FAKE"]) / "tagged").read_text()
    assert "Public ECR mirror" in _summary(env) and f"sha256:{DIGEST}" in _summary(env)


def test_mirror_pin_with_another_digest_is_refused(tmp_path: Path, env: dict[str, str]) -> None:
    bad = f"postgres {HUB} {ECR}:16-alpine@sha256:{OTHER}\n"
    r = _run(tmp_path, env, bad, "postgres", HUB_FAILS="99")
    assert r.returncode == 1
    assert "CI-INFRA-001" in r.stderr and "digest" in r.stderr
    assert _count(env, "ecr_pulls") == 0


def test_mirror_serving_another_digest_is_refused(tmp_path: Path, env: dict[str, str]) -> None:
    r = _run(tmp_path, env, PG, "postgres", HUB_FAILS="99", MIRROR_SERVES=OTHER)
    assert r.returncode == 1
    assert "CI-INFRA-001" in r.stderr
    assert not (Path(env["FAKE"]) / "tagged").exists()


def test_both_sources_fail_ends_with_the_code(tmp_path: Path, env: dict[str, str]) -> None:
    r = _run(tmp_path, env, PG, "postgres", HUB_FAILS="99", MIRROR_OK="0")
    assert r.returncode == 1
    assert "CI-INFRA-001" in r.stderr and "postgres" in r.stderr
    assert not (Path(env["FAKE"]) / "tagged").exists()


def test_image_without_mirror_retries_hub_only_and_resolves_the_compose_pin(
    tmp_path: Path, env: dict[str, str]
) -> None:
    listing = "questdb compose:questdb/questdb -\n"
    ok = _run(tmp_path, env, listing, "questdb", HUB_FAILS="2")
    assert ok.returncode == 0, ok.stderr
    assert f"questdb/questdb:8.1.1@sha256:{DIGEST}" in (Path(env["FAKE"]) / "calls.log").read_text()
    assert _count(env, "hub_pulls") == 3 and _count(env, "ecr_pulls") == 0


def test_image_without_mirror_fails_with_the_code_after_five_attempts(
    tmp_path: Path, env: dict[str, str]
) -> None:
    r = _run(tmp_path, env, "questdb compose:questdb/questdb -\n", "questdb", HUB_FAILS="99")
    assert r.returncode == 1 and "CI-INFRA-001" in r.stderr
    assert _count(env, "hub_pulls") == 5 and _count(env, "ecr_pulls") == 0


def test_unknown_name_fails_with_the_code(tmp_path: Path, env: dict[str, str]) -> None:
    r = _run(tmp_path, env, PG, "nope")
    assert r.returncode == 1 and "CI-INFRA-001" in r.stderr


def test_ref_without_a_digest_is_refused(tmp_path: Path, env: dict[str, str]) -> None:
    r = _run(tmp_path, env, "postgres postgres:16-alpine -\n", "postgres")
    assert r.returncode == 1 and "CI-INFRA-001" in r.stderr
    assert _count(env, "hub_pulls") == 0


def test_every_lane_that_collects_a_postgres_module_pre_pulls() -> None:
    import sys

    sys.path.insert(0, str(REPO))
    from tools.ci import py_test_lanes as lanes

    manifest = lanes.load_manifest()
    tests = REPO / "services" / "api"
    pg = [
        f
        for f in lanes.suite_files()
        if "postgres:16" in (tests / f).read_text(encoding="utf-8", errors="ignore")
    ]
    assert pg
    workflow = (REPO / ".github" / "workflows" / "_job-py.yml").read_text(encoding="utf-8")
    cond = "startsWith(matrix.lane, 'db-chaos') || matrix.lane == 'contract-security-3'"
    assert cond in workflow
    need = {
        lane
        for lane in [*manifest.lanes, manifest.rest_lane]
        if any(lanes.collects(lanes.pytest_args(manifest, lane), f) for f in pg)
    }
    covered = {lane for lane in need if lane.startswith("db-chaos") or lane == "contract-security-3"}
    assert need == covered
