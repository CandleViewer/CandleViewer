"""Tests for tools/ci/prepull_images.sh (#4301, CI-INFRA-001): a fake `docker` on PATH, no network."""

from __future__ import annotations

import os
import re
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
      [ "$n" -gt "${MIRROR_FAILS:-0}" ] || { echo "mirror 429" >&2; exit 1; }
      [ "${MIRROR_OK:-1}" = 1 ] || { echo "mirror down" >&2; exit 1; }
      echo "${MIRROR_SERVES:-${ref##*@sha256:}}" > "$FAKE/served"
      echo "${ref%%@*}" > "$FAKE/served_repo"
    else
      n=$(count hub_pulls)
      [ "$n" -gt "${HUB_FAILS:-0}" ] || { echo "token service timed out" >&2; exit 1; }
      echo "${HUB_SERVES:-${ref##*@sha256:}}" > "$FAKE/served"
      echo "${ref%%:*}@${ref##*@}" >> "$FAKE/digests"
      echo "${ref%%@*}" > "$FAKE/served_repo"
    fi
    echo "$ref"
    ;;
  "tag "*)
    [ "${TAG_FAILS:-0}" = 0 ] || exit 1
    echo "$3" >> "$FAKE/tagged"
    [ "${DIGEST_ON_TAG:-0}" = 0 ] || echo "${3%%:*}@sha256:$(cat "$FAKE/served")" >> "$FAKE/digests"
    ;;
  "image inspect")
    if [ "$3" = "--format" ]; then
      echo "$(cat "$FAKE/served_repo" | sed 's/:[^:/]*$//')@sha256:$(cat "$FAKE/served")"
    else
      grep -qx "$3" "$FAKE/tagged" 2>/dev/null || grep -qx "${3%%:*}@${3##*@}" "$FAKE/digests" 2>/dev/null
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
    nap = bindir / "sleep"
    nap.write_text('#!/bin/bash\necho "$*" >> "$FAKE/sleeps.log"\n', encoding="utf-8")
    nap.chmod(nap.stat().st_mode | stat.S_IXUSR)
    tmo = bindir / "timeout"
    tmo.write_text(
        '#!/bin/bash\necho "$1" >> "$FAKE/timeouts.log"\nshift\nexec "$@"\n',
        encoding="utf-8",
    )
    tmo.chmod(tmo.stat().st_mode | stat.S_IXUSR)
    state = tmp_path / "state"
    state.mkdir()
    return {
        "PATH": f"{bindir}:{os.environ['PATH']}",
        "FAKE": str(state),
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


def test_hub_succeeds_first_try_and_tags_locally(
    tmp_path: Path, env: dict[str, str]
) -> None:
    r = _run(tmp_path, env, PG, "postgres")
    assert r.returncode == 0, r.stderr
    assert _count(env, "hub_pulls") == 1 and _count(env, "ecr_pulls") == 0
    assert "postgres:16-alpine" in (Path(env["FAKE"]) / "tagged").read_text()
    assert "Docker Hub" in _summary(env) and f"sha256:{DIGEST}" in _summary(env)


def test_hub_fails_then_works_within_five_attempts(
    tmp_path: Path, env: dict[str, str]
) -> None:
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


def test_mirror_pin_with_another_digest_is_refused(
    tmp_path: Path, env: dict[str, str]
) -> None:
    bad = f"postgres {HUB} {ECR}:16-alpine@sha256:{OTHER}\n"
    r = _run(tmp_path, env, bad, "postgres", HUB_FAILS="99")
    assert r.returncode == 1
    assert "CI-INFRA-001" in r.stderr and "digest" in r.stderr
    assert _count(env, "ecr_pulls") == 0


def test_mirror_serving_another_digest_is_refused(
    tmp_path: Path, env: dict[str, str]
) -> None:
    r = _run(tmp_path, env, PG, "postgres", HUB_FAILS="99", MIRROR_SERVES=OTHER)
    assert r.returncode == 1
    assert "CI-INFRA-001" in r.stderr
    assert not (Path(env["FAKE"]) / "tagged").exists()


def test_both_sources_fail_ends_with_the_code(
    tmp_path: Path, env: dict[str, str]
) -> None:
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
    assert (
        f"questdb/questdb:8.1.1@sha256:{DIGEST}"
        in (Path(env["FAKE"]) / "calls.log").read_text()
    )
    assert _count(env, "hub_pulls") == 3 and _count(env, "ecr_pulls") == 0


def test_image_without_mirror_fails_with_the_code_after_five_attempts(
    tmp_path: Path, env: dict[str, str]
) -> None:
    r = _run(
        tmp_path, env, "questdb compose:questdb/questdb -\n", "questdb", HUB_FAILS="99"
    )
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
    workflow = (REPO / ".github" / "workflows" / "_job-py.yml").read_text(
        encoding="utf-8"
    )
    cond = "startsWith(matrix.lane, 'db-chaos') || matrix.lane == 'contract-security-3'"
    assert cond in workflow
    need = {
        lane
        for lane in [*manifest.lanes, manifest.rest_lane]
        if any(lanes.collects(lanes.pytest_args(manifest, lane), f) for f in pg)
    }
    covered = {
        lane
        for lane in need
        if lane.startswith("db-chaos") or lane == "contract-security-3"
    }
    assert need == covered


def _sleeps(env: dict[str, str]) -> list[str]:
    p = Path(env["FAKE"]) / "sleeps.log"
    return p.read_text().split() if p.exists() else []


def test_backoff_waits_between_hub_attempts_and_not_after_the_last(
    tmp_path: Path, env: dict[str, str]
) -> None:
    r = _run(tmp_path, env, PG, "postgres", HUB_FAILS="99")
    assert r.returncode == 0, r.stderr
    assert _sleeps(env)[:4] == ["10", "20", "40", "60"]


def test_mirror_gets_three_attempts_with_a_wait_between(
    tmp_path: Path, env: dict[str, str]
) -> None:
    r = _run(tmp_path, env, PG, "postgres", HUB_FAILS="99", MIRROR_FAILS="2")
    assert r.returncode == 0, r.stderr
    assert _count(env, "ecr_pulls") == 3
    assert _sleeps(env)[4:] == ["30", "60"]
    again = _run(tmp_path, env, PG, "postgres", HUB_FAILS="99", MIRROR_FAILS="99")
    assert again.returncode == 1 and "CI-INFRA-001" in again.stderr


def test_hub_serving_another_digest_falls_back_to_the_mirror(
    tmp_path: Path, env: dict[str, str]
) -> None:
    r = _run(tmp_path, env, PG, "postgres", HUB_SERVES=OTHER)
    assert r.returncode == 0, r.stderr
    assert _count(env, "ecr_pulls") == 1
    assert "Public ECR mirror" in _summary(env)
    assert "other than" in r.stderr


def test_every_pull_has_its_own_time_bound(tmp_path: Path, env: dict[str, str]) -> None:
    r = _run(tmp_path, env, PG, "postgres", HUB_FAILS="1")
    assert r.returncode == 0, r.stderr
    assert (Path(env["FAKE"]) / "timeouts.log").read_text().split() == ["120", "120"]


def test_a_failing_tag_ends_with_the_code(tmp_path: Path, env: dict[str, str]) -> None:
    r = _run(tmp_path, env, PG, "postgres", TAG_FAILS="1")
    assert r.returncode == 1 and "CI-INFRA-001" in r.stderr


def test_the_compose_postgres_image_resolves_to_its_pinned_tag(
    tmp_path: Path, env: dict[str, str]
) -> None:
    listing = f"postgres-compose compose:postgres {ECR}:16.4@sha256:{DIGEST}\n"
    compose = tmp_path / "compose.yml"
    compose.write_text(f"services:\n  p:\n    image: postgres:16.4@sha256:{DIGEST}\n")
    lst = tmp_path / "l.txt"
    lst.write_text(listing)
    r = subprocess.run(
        [
            "bash",
            str(SCRIPT),
            "--list",
            str(lst),
            "--compose",
            str(compose),
            "postgres-compose",
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert r.returncode == 0, r.stderr
    assert "postgres:16.4" in (Path(env["FAKE"]) / "tagged").read_text()


def test_the_real_list_names_every_image_the_jobs_pull() -> None:
    rows = (REPO / "infra/images/prepull.txt").read_text(encoding="utf-8")
    names = {
        ln.split()[0]
        for ln in rows.splitlines()
        if ln.strip() and not ln.startswith("#")
    }
    assert {"postgres", "postgres-compose", "questdb", "grafana"} <= names
    integ = (REPO / ".github/workflows/_job-integration.yml").read_text(
        encoding="utf-8"
    )
    assert "prepull_images.sh postgres postgres-compose questdb grafana" in integ


def test_the_reaper_image_is_not_pulled_mid_job() -> None:
    for wf in ("_job-py.yml", "_job-integration.yml", "_job-migrations.yml"):
        text = (REPO / ".github/workflows" / wf).read_text(encoding="utf-8")
        assert 'TESTCONTAINERS_RYUK_DISABLED: "true"' in text, wf


def test_every_job_that_builds_a_postgres_container_pre_pulls() -> None:
    for wf, marker in (
        ("_job-integration.yml", "Audit query-plan measurement"),
        ("_job-migrations.yml", "cv_app has no DDL privilege"),
    ):
        text = (REPO / ".github/workflows" / wf).read_text(encoding="utf-8")
        head = text.rpartition(marker)[0]
        assert (
            head.rstrip().rsplit("prepull_images.sh", 1)[-1].startswith(" postgres")
        ), wf
    text = (REPO / ".github/workflows/_job-integration.yml").read_text(encoding="utf-8")
    plan_job = text.partition("  audit-query-plan:")[2].partition(
        "Audit query-plan measurement"
    )[0]
    assert "prepull_images.sh postgres" in plan_job


def test_the_pull_bound_is_a_knob_with_a_default_of_120(
    tmp_path: Path, env: dict[str, str]
) -> None:
    r = _run(tmp_path, env, PG, "postgres", PREPULL_PULL_TIMEOUT="45")
    assert r.returncode == 0, r.stderr
    assert (Path(env["FAKE"]) / "timeouts.log").read_text().split() == ["45"]


def test_py_perf_sets_a_pull_bound_that_fits_its_job_timeout() -> None:
    text = (REPO / ".github/workflows/_job-py.yml").read_text(encoding="utf-8")
    job = text.partition("  py-perf:")[2]
    bound = int(re.search(r'PREPULL_PULL_TIMEOUT: "(\d+)"', job).group(1))  # type: ignore[union-attr]
    minutes = int(re.search(r"timeout-minutes: (\d+)", job).group(1))  # type: ignore[union-attr]
    # 5 source attempts + 3 mirror attempts, plus the waits (10+20+40+60 and 30+60).
    assert 8 * bound + 220 < minutes * 60


def _compose_row(
    tmp_path: Path, env: dict[str, str], **extra: str
) -> subprocess.CompletedProcess[str]:
    compose = tmp_path / "compose.yml"
    compose.write_text(f"services:\n  p:\n    image: postgres:16.4@sha256:{DIGEST}\n")
    lst = tmp_path / "l.txt"
    lst.write_text(f"postgres-compose compose:postgres {ECR}:16.4@sha256:{DIGEST}\n")
    return subprocess.run(
        [
            "bash",
            str(SCRIPT),
            "--list",
            str(lst),
            "--compose",
            str(compose),
            "postgres-compose",
        ],
        env={**env, **extra},
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def test_a_compose_mirror_ref_the_compose_file_cannot_resolve_fails_closed(
    tmp_path: Path, env: dict[str, str]
) -> None:
    r = _compose_row(tmp_path, env, HUB_FAILS="99")
    assert r.returncode == 1
    assert "CI-INFRA-001" in r.stderr and "does not resolve locally" in r.stderr


def test_a_compose_mirror_ref_resolves_when_the_daemon_records_digests_on_tag(
    tmp_path: Path, env: dict[str, str]
) -> None:
    r = _compose_row(tmp_path, env, HUB_FAILS="99", DIGEST_ON_TAG="1")
    assert r.returncode == 0, r.stderr
    assert "Public ECR mirror" in _summary(env)
