"""Unit tests for tools/ci/deploy_dev.py (E03-T09 dev/staging deploy).

No docker/network: `subprocess.run` and `urllib.request.urlopen` are
monkeypatched so these run fully offline (C-13.5 / AGENTS.md §8.7).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "infra" / "scripts"))

import lint_compose
from tools.ci import deploy_dev as dd


@pytest.fixture()
def env_example(tmp_path: Path) -> Path:
    p = tmp_path / ".env.example"
    p.write_text(
        "CV_ENVIRONMENT=demo\nCV_FEED=synthetic\nCV_GIT_SHA=unknown\n", encoding="utf-8"
    )
    return p


REPO = Path(__file__).resolve().parents[2]
OVERLAY = REPO / "infra" / "compose" / "docker-compose.deploy.yml"
CONTAINER_ID = "c0ffee000000"  # 12 hex digits, as `docker compose ps -q` prints one
COMPOSE = ("infra/compose/docker-compose.yml",)
DECOY = "decoy-decoy-decoy"  # a credential in the container's environment
REF, DIGEST = "ghcr.io/o/img", "sha256:" + "a" * 64
IMAGE = f"{REF}@{DIGEST}"  # the verified image
IMAGE_ID, OTHER_ID = "sha256:" + "d" * 64, "sha256:" + "e" * 64  # its daemon id, another's
DIGEST_A, DIGEST_B = "sha256:" + "1" * 64, "sha256:" + "2" * 64
IDS = {DIGEST_A: "sha256:" + "3" * 64, DIGEST_B: "sha256:" + "4" * 64}  # daemon ids


def fake_docker(
    monkeypatch: pytest.MonkeyPatch,
    ps: tuple[int, str] = (0, CONTAINER_ID + "\n"),
    inspect: tuple[int, str] = (0, IMAGE_ID + "\n"),
    image: tuple[int, str] = (0, IMAGE_ID + "\n"),
) -> SimpleNamespace:
    """Fake `subprocess.run`: cosign and `compose up` succeed, the smoke test's three
    queries answer (rc, stdout): `compose ps`, the container's `inspect`, `image inspect`.
    `.calls` logs each argv, `.kwargs` its keywords."""
    log = SimpleNamespace(calls=[], kwargs=[])

    def run(cmd: list[str], **kwargs: object) -> SimpleNamespace:
        log.calls.append(cmd)
        log.kwargs.append(kwargs)
        if cmd[:3] == ["docker", "image", "inspect"]:
            rc, out = image
        elif cmd[:2] == ["docker", "inspect"]:
            rc, out = inspect
        else:
            rc, out = ps if "ps" in cmd else (0, "")
        return SimpleNamespace(returncode=rc, stdout=out, stderr="")

    monkeypatch.setattr(dd.subprocess, "run", run)
    return log


def stateful_docker(
    monkeypatch: pytest.MonkeyPatch, pinned: list[str] | None = None
) -> SimpleNamespace:
    """`compose up` runs the digest in its environment or, for the first ups, the next one in
    `pinned` (a later file pinning that image); ids come from `IDS`. `.ups` logs up's digests."""
    log = SimpleNamespace(calls=[], ups=[], running="")
    queue = list(pinned or [])

    def run(cmd: list[str], **kwargs: Any) -> SimpleNamespace:
        log.calls.append(cmd)
        out = CONTAINER_ID + "\n" if "ps" in cmd else ""
        if "up" in cmd:
            log.ups.append(kwargs["env"]["CV_IMAGE_DIGEST"])
            log.running = queue.pop(0) if queue else log.ups[-1]
        elif cmd[:3] == ["docker", "image", "inspect"]:
            out = IDS[cmd[-1].split("@")[1]] + "\n"
        elif cmd[:2] == ["docker", "inspect"]:
            out = IDS[log.running] + "\n"
        return SimpleNamespace(returncode=0, stdout=out, stderr="")

    monkeypatch.setattr(dd.subprocess, "run", run)
    return log


def run_deploy(tmp_path: Path, env_example: Path, ledger: Path, **overrides: Any) -> int:
    """`dd.deploy` with this module's defaults; `overrides` replace them."""
    kwargs: dict[str, Any] = dict(
        image_ref=REF, digest=DIGEST, sha="abc1234", environment="dev", actor="ci",
        repository="o/r", env_example=env_example, env_out=tmp_path / ".env",
        compose_files=COMPOSE, base_url="http://x", ledger_path=ledger, smoke_timeout_s=5.0,
        auto_rollback=False,
    )
    return dd.deploy(**{**kwargs, **overrides})


def probes(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Both probes say ok; returns the urls polled."""
    urls: list[str] = []

    def fake_get_json(url: str, timeout_s: float = 3.0) -> dict:
        urls.append(url)
        return {"status": "ok"}

    monkeypatch.setattr(dd, "_get_json", fake_get_json)
    return urls


def test_render_env_file_sets_the_image_and_the_sha(tmp_path: Path, env_example: Path) -> None:
    out = tmp_path / ".env"
    dd.render_env_file(env_example, out, image_ref=REF, image_digest=DIGEST, git_sha="abc1234")
    text = out.read_text(encoding="utf-8")
    assert "CV_GIT_SHA=abc1234" in text
    assert f"CV_API_IMAGE_REF={REF}\n" in text
    assert f"CV_IMAGE_DIGEST={DIGEST}\n" in text
    assert "CV_FEED=synthetic" in text


def test_default_compose_files_are_the_base_and_the_deploy_overlay() -> None:
    assert dd.DEFAULT_COMPOSE_FILES == (
        "infra/compose/docker-compose.yml",
        "infra/compose/docker-compose.deploy.yml",
    )
    assert all((REPO / name).is_file() for name in dd.DEFAULT_COMPOSE_FILES)


def test_compose_up_never_builds_and_pins_the_verified_image(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CV_IMAGE_DIGEST", "stale")  # never wins compose's interpolation
    monkeypatch.setenv("DOCKER_HOST", "unix:///run/docker.sock")
    docker = fake_docker(monkeypatch)
    dd.compose_up(COMPOSE, image_ref=REF, digest=DIGEST)
    (up,) = docker.calls
    assert up[-4:] == ["up", "-d", "--wait", "--no-build"]
    env = docker.kwargs[0]["env"]
    assert (env["CV_API_IMAGE_REF"], env["CV_IMAGE_DIGEST"]) == (REF, DIGEST)
    assert env["DOCKER_HOST"] == "unix:///run/docker.sock"  # the rest of the environment


def test_verify_signature_raises_ci_dep_001_on_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        dd.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=1, stderr="no matching signatures"),
    )
    with pytest.raises(dd.DeployError) as exc:
        dd.verify_signature("ghcr.io/o/img", "sha256:" + "a" * 64, repository="o/r")
    assert exc.value.code == "CI-DEP-001"


def test_verify_signature_passes_on_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        dd.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0, stderr="")
    )
    dd.verify_signature(
        "ghcr.io/o/img", "sha256:" + "a" * 64, repository="o/r"
    )  # no raise


def test_verify_signature_pins_identity_to_signer_workflow_and_ref(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A bare `^https://github.com/{repo}/` prefix matches any workflow in the
    repo (including a PR-branch run). The regexp passed to `cosign verify`
    must pin `main.yml`'s job identity and an allowed ref for the target
    environment."""
    captured: dict = {}

    def fake_run(cmd: list[str], **kwargs: object) -> SimpleNamespace:
        captured["cmd"] = cmd
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr(dd.subprocess, "run", fake_run)

    dd.verify_signature(
        "ghcr.io/o/img", "sha256:" + "a" * 64, repository="o/r", environment="dev"
    )
    idx = captured["cmd"].index("--certificate-identity-regexp")
    regexp = captured["cmd"][idx + 1]
    assert r"\.github/workflows/main\.yml" in regexp
    assert regexp.endswith(r"@(?:refs/heads/main)$")
    # A build on a PR branch or a different workflow must not match.
    import re as _re

    signer_main = "https://github.com/o/r/.github/workflows/main.yml@refs/heads/main"
    signer_pr = "https://github.com/o/r/.github/workflows/main.yml@refs/pull/9/merge"
    other_workflow = (
        "https://github.com/o/r/.github/workflows/deploy-dev.yml@refs/heads/main"
    )
    assert _re.match(regexp, signer_main)
    assert not _re.match(regexp, signer_pr)
    assert not _re.match(regexp, other_workflow)


def test_verify_signature_staging_also_allows_release_branch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict = {}

    def fake_run(cmd: list[str], **kwargs: object) -> SimpleNamespace:
        captured["cmd"] = cmd
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr(dd.subprocess, "run", fake_run)

    dd.verify_signature(
        "ghcr.io/o/img", "sha256:" + "a" * 64, repository="o/r", environment="staging"
    )
    idx = captured["cmd"].index("--certificate-identity-regexp")
    regexp = captured["cmd"][idx + 1]
    import re as _re

    signer_release = (
        "https://github.com/o/r/.github/workflows/main.yml@refs/heads/release/1.2"
    )
    assert _re.match(regexp, signer_release)


@pytest.fixture()
def clock(monkeypatch: pytest.MonkeyPatch) -> None:
    """A fake clock: `sleep` advances `monotonic`, so a poll loop ends on its own."""
    now = [0.0]

    def sleep(seconds: float) -> None:
        now[0] += seconds

    monkeypatch.setattr(dd.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(dd.time, "sleep", sleep)


def test_smoke_test_passes_when_the_api_runs_the_verified_image(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    urls = probes(monkeypatch)
    fake_docker(monkeypatch)
    dd.smoke_test("http://x", IMAGE, COMPOSE, timeout_s=5.0)
    assert urls == ["http://x/healthz", "http://x/readyz"]
    out = capsys.readouterr().out
    assert out == f"smoke: the api container runs {IMAGE} (image id {IMAGE_ID})\n"


def test_the_image_id_queries_are_fixed_and_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    """The running container's image id and the verified image's id, each queried by its
    object type with a fixed argv."""
    probes(monkeypatch)
    docker = fake_docker(monkeypatch)
    dd.smoke_test("http://x", IMAGE, COMPOSE, timeout_s=5.0)
    ps, inspect, image = docker.calls
    assert " ".join(ps) == (
        "docker compose -f infra/compose/docker-compose.yml --profile core ps -q api"
    )
    assert inspect[:6] == ["docker", "inspect", "--type", "container", "--format", "{{.Image}}"]
    assert inspect[6:] == [CONTAINER_ID]
    assert image == ["docker", "image", "inspect", "--format", "{{.Id}}", IMAGE]
    # The module's subprocess style: captured output, no `check`, and a bound.
    assert all(k["capture_output"] and k["check"] is False for k in docker.kwargs)
    assert all(k["timeout"] for k in docker.kwargs)


def test_smoke_test_passes_with_a_healthz_body_without_git_sha(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#4222's precondition: the probes may stop carrying the sha."""
    body = {"status": "ok", "version": "0.1.0"}
    monkeypatch.setattr(dd, "_get_json", lambda *a, **k: body)
    fake_docker(monkeypatch)
    dd.smoke_test("http://x", IMAGE, COMPOSE, timeout_s=5.0)


def test_smoke_test_image_mismatch_raises_ci_dep_003_naming_both_ids(
    monkeypatch: pytest.MonkeyPatch, clock: None
) -> None:
    """At once: a container's image changes only when it is recreated, and `up --wait` is done."""
    urls = probes(monkeypatch)
    fake_docker(monkeypatch, inspect=(0, OTHER_ID + "\n"))
    with pytest.raises(dd.DeployError) as exc:
        dd.smoke_test("http://x", IMAGE, COMPOSE, timeout_s=5.0)
    assert str(exc.value) == (
        "CI-DEP-003: image mismatch after deploy: the running api container's image id is "
        f"{OTHER_ID}, the image id of {IMAGE} is {IMAGE_ID}"
    )
    assert urls == ["http://x/healthz", "http://x/readyz"]  # one poll, no retry


def test_smoke_test_with_no_api_container_fails_closed(
    monkeypatch: pytest.MonkeyPatch, clock: None
) -> None:
    probes(monkeypatch)
    docker = fake_docker(monkeypatch, ps=(0, ""))
    with pytest.raises(dd.DeployError) as exc:
        dd.smoke_test("http://x", IMAGE, COMPOSE, timeout_s=5.0)
    assert exc.value.code == "CI-DEP-002"
    assert "printed 0 value(s)" in str(exc.value)
    assert "no attempt made" not in str(exc.value)  # the loop ran
    assert str(exc.value).count("CI-DEP-002") == 1
    retries = [c[-3:] for c in docker.calls]  # every 2 s until the 5 s deadline
    assert retries == [["ps", "-q", "api"]] * 3


@pytest.mark.parametrize("query", ["ps", "inspect", "image"])
def test_smoke_test_failed_docker_query_fails_closed(
    monkeypatch: pytest.MonkeyPatch, clock: None, query: str
) -> None:
    """The exit status decides, not stdout: a query that exits 1 yet prints a
    plausible answer must not be believed."""
    probes(monkeypatch)
    plausible = {"ps": CONTAINER_ID + "\n", "inspect": IMAGE_ID + "\n", "image": IMAGE_ID + "\n"}
    fake_docker(monkeypatch, **{query: (1, plausible[query])})
    with pytest.raises(dd.DeployError) as exc:
        dd.smoke_test("http://x", IMAGE, COMPOSE, timeout_s=5.0)
    assert exc.value.code == "CI-DEP-002"
    assert "failed (exit 1)" in str(exc.value)
    assert "no attempt made" not in str(exc.value)


@pytest.mark.parametrize(
    "error",
    [
        FileNotFoundError("docker"),
        dd.subprocess.TimeoutExpired("docker", 20.0),
        UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte"),
    ],
    ids=["no-docker-binary", "docker-hangs", "not-utf-8"],
)
def test_smoke_test_docker_that_cannot_run_fails_closed(
    monkeypatch: pytest.MonkeyPatch, clock: None, error: Exception
) -> None:
    probes(monkeypatch)

    def boom(*args: object, **kwargs: object) -> None:
        raise error

    monkeypatch.setattr(dd.subprocess, "run", boom)
    with pytest.raises(dd.DeployError) as exc:
        dd.smoke_test("http://x", IMAGE, COMPOSE, timeout_s=5.0)
    assert exc.value.code == "CI-DEP-002"
    assert "did not complete" in str(exc.value)


LEAK = f"POSTGRES_PASSWORD={DECOY}"


@pytest.mark.parametrize(
    "answer",
    [
        {"inspect": (0, LEAK + "\n")},  # a variable, not an image id
        {"inspect": (0, LEAK + "\n" + IMAGE_ID + "\n")},  # more than the one id
        {"inspect": (0, IMAGE_ID + "\n" + LEAK + "\n")},
        {"image": (0, LEAK + "\n")},
        {"image": (0, f"{IMAGE_ID} {LEAK}\n")},
        {"ps": (0, LEAK + "\n")},  # a variable where a container id belongs
        {"ps": (0, CONTAINER_ID + " " + LEAK + "\n")},
    ],
)
def test_smoke_test_never_echoes_what_docker_printed(
    monkeypatch: pytest.MonkeyPatch,
    clock: None,
    capsys: pytest.CaptureFixture[str],
    answer: dict[str, tuple[int, str]],
) -> None:
    """Anything docker prints beyond one container id or one image id is refused, and no
    message, repr or output repeats it (C-12.2, C-12.6)."""
    probes(monkeypatch)
    fake_docker(monkeypatch, **answer)
    with pytest.raises(dd.DeployError) as exc:
        dd.smoke_test("http://x", IMAGE, COMPOSE, timeout_s=5.0)
    assert exc.value.code == "CI-DEP-002"
    out, err = capsys.readouterr()
    assert DECOY not in f"{exc.value} {exc.value!r} {out} {err}"


@pytest.mark.parametrize("starting", ["healthz", "readyz"])
def test_smoke_test_never_ready_raises_ci_dep_002(
    monkeypatch: pytest.MonkeyPatch, clock: None, starting: str
) -> None:
    """Both probes must say ok: either one still starting fails the smoke test."""
    monkeypatch.setattr(
        dd, "_get_json", lambda url, *a, **k: {"status": "starting" if starting in url else "ok"}
    )
    docker = fake_docker(monkeypatch)
    with pytest.raises(dd.DeployError) as exc:
        dd.smoke_test("http://x", IMAGE, COMPOSE, timeout_s=5.0)
    assert exc.value.code == "CI-DEP-002"
    assert "not ready" in str(exc.value)
    assert docker.calls == []  # the container is only looked at once the probes are ok


def test_ledger_append_and_read_last_success(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    dd.append_ledger(
        dd.LedgerEntry(
            sha="s1",
            digest="sha256:" + "1" * 64,
            environment="dev",
            actor="ci",
            timestamp="2026-01-01T00:00:00Z",
            outcome="success",
        ),
        ledger,
    )
    dd.append_ledger(
        dd.LedgerEntry(
            sha="s2",
            digest="sha256:" + "2" * 64,
            environment="dev",
            actor="ci",
            timestamp="2026-01-02T00:00:00Z",
            outcome="signature-verification-failed",
        ),
        ledger,
    )
    lines = ledger.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["outcome"] == "success"
    assert dd.read_last_success_digest("dev", ledger) == "sha256:" + "1" * 64
    assert dd.read_last_success_digest("staging", ledger) is None


def test_deploy_success_path_writes_success_ledger(
    tmp_path: Path, env_example: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_docker(monkeypatch)
    probes(monkeypatch)
    ledger = tmp_path / "ledger.jsonl"
    rc = dd.deploy(
        image_ref="ghcr.io/o/img",
        digest="sha256:" + "a" * 64,
        sha="abc1234",
        environment="dev",
        actor="ci",
        repository="o/r",
        env_example=env_example,
        env_out=tmp_path / ".env",
        compose_files=("infra/compose/docker-compose.yml",),
        base_url="http://x",
        ledger_path=ledger,
        smoke_timeout_s=5.0,
        auto_rollback=False,
    )
    assert rc == 0
    rows = [json.loads(l) for l in ledger.read_text(encoding="utf-8").splitlines()]
    assert rows[-1]["outcome"] == "success"


def test_deploy_image_mismatch_records_sha_mismatch(
    tmp_path: Path, env_example: Path, monkeypatch: pytest.MonkeyPatch, clock: None
) -> None:
    probes(monkeypatch)
    docker = fake_docker(monkeypatch, inspect=(0, OTHER_ID + "\n"))
    ledger = tmp_path / "ledger.jsonl"
    rc = dd.deploy(
        image_ref="ghcr.io/o/img",
        digest="sha256:" + "b" * 64,
        sha="new-sha",
        environment="dev",
        actor="ci",
        repository="o/r",
        env_example=env_example,
        env_out=tmp_path / ".env",
        compose_files=("a.yml", "b.yml"),
        base_url="http://x",
        ledger_path=ledger,
        smoke_timeout_s=5.0,
        auto_rollback=False,
    )
    assert rc == 1
    rows = [json.loads(x) for x in ledger.read_text(encoding="utf-8").splitlines()]
    assert rows[-1]["outcome"] == "sha-mismatch"
    assert OTHER_ID in rows[-1]["detail"]
    assert IMAGE_ID in rows[-1]["detail"]
    # The container is looked up in the compose project this deploy brought up.
    up = next(c for c in docker.calls if "up" in c)
    ps = next(c for c in docker.calls if "ps" in c)
    assert ps[: ps.index("ps")] == up[: up.index("up")]


def test_deploy_tampered_image_aborts_before_compose_up(
    tmp_path: Path, env_example: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Acceptance scenario: unsigned/tampered image is refused, ledger records
    `signature-verification-failed`, and `docker compose up` is never called."""
    compose_up_called = {"n": 0}

    monkeypatch.setattr(
        dd.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=1, stderr="bad sig"),
    )

    def fake_compose_up(*a, **k):
        compose_up_called["n"] += 1

    monkeypatch.setattr(dd, "compose_up", fake_compose_up)
    ledger = tmp_path / "ledger.jsonl"
    rc = dd.deploy(
        image_ref="ghcr.io/o/img",
        digest="sha256:" + "b" * 64,
        sha="deadbee",
        environment="dev",
        actor="ci",
        repository="o/r",
        env_example=env_example,
        env_out=tmp_path / ".env",
        compose_files=("infra/compose/docker-compose.yml",),
        base_url="http://x",
        ledger_path=ledger,
        smoke_timeout_s=5.0,
        auto_rollback=False,
    )
    assert rc == 1
    assert compose_up_called["n"] == 0
    rows = [json.loads(l) for l in ledger.read_text(encoding="utf-8").splitlines()]
    assert rows[-1]["outcome"] == "signature-verification-failed"


def test_deploy_failed_smoke_triggers_dev_auto_rollback(
    tmp_path: Path, env_example: Path, monkeypatch: pytest.MonkeyPatch, clock: None
) -> None:
    """Acceptance scenario: a failed smoke test marks the deployment failed
    and the previous digest is automatically restored (dev only)."""
    good_digest = "sha256:" + "1" * 64
    ledger = tmp_path / "ledger.jsonl"
    dd.append_ledger(
        dd.LedgerEntry(
            sha="prev-sha",
            digest=good_digest,
            environment="dev",
            actor="ci",
            timestamp="2026-01-01T00:00:00Z",
            outcome="success",
        ),
        ledger,
    )
    docker = fake_docker(monkeypatch)

    def fake_get_json(url: str, timeout_s: float = 3.0) -> dict:
        # The forward deploy never becomes ready (CI-DEP-002); the rollback's stack does.
        rolled_back = sum("up" in c for c in docker.calls) > 1
        return {"status": "ok" if rolled_back else "starting"}

    monkeypatch.setattr(dd, "_get_json", fake_get_json)

    rc = dd.deploy(
        image_ref="ghcr.io/o/img",
        digest="sha256:" + "b" * 64,
        sha="bad-sha",
        environment="dev",
        actor="ci",
        repository="o/r",
        env_example=env_example,
        env_out=tmp_path / ".env",
        compose_files=("infra/compose/docker-compose.yml",),
        base_url="http://x",
        ledger_path=ledger,
        smoke_timeout_s=0.05,
        auto_rollback=True,
    )
    assert rc == 1
    rows = [json.loads(l) for l in ledger.read_text(encoding="utf-8").splitlines()]
    outcomes = [r["outcome"] for r in rows]
    assert "smoke-failed" in outcomes
    assert "rolled-back" in outcomes
    rolled_back_row = next(r for r in rows if r["outcome"] == "rolled-back")
    assert rolled_back_row["digest"] == good_digest


def test_dev_rollback_runs_the_previous_digest_and_checks_its_image_id(
    tmp_path: Path, env_example: Path, monkeypatch: pytest.MonkeyPatch, clock: None
) -> None:
    """The api runs A while B was verified: CI-DEP-003 names both ids, then dev runs the
    previous digest A through the same compose files and the smoke test checks A's id."""
    ledger = tmp_path / "ledger.jsonl"
    previous = dd.LedgerEntry("prev-sha", DIGEST_A, "dev", "ci", "2026-01-01T00:00:00Z", "success")
    dd.append_ledger(previous, ledger)
    docker = stateful_docker(monkeypatch, pinned=[DIGEST_A])
    probes(monkeypatch)
    assert run_deploy(tmp_path, env_example, ledger, digest=DIGEST_B, auto_rollback=True) == 1
    assert docker.ups == [DIGEST_B, DIGEST_A]
    forward_up, rollback_up = (c for c in docker.calls if "up" in c)
    assert forward_up == rollback_up  # the same files, overlay and --no-build
    checked = [c[-1] for c in docker.calls if c[:3] == ["docker", "image", "inspect"]]
    assert checked == [f"{REF}@{DIGEST_B}", f"{REF}@{DIGEST_A}"]
    rows = [json.loads(x) for x in ledger.read_text(encoding="utf-8").splitlines()][1:]
    outcomes = [(r["outcome"], r["digest"]) for r in rows]
    assert outcomes == [("sha-mismatch", DIGEST_B), ("rolled-back", DIGEST_A)]
    assert IDS[DIGEST_A] in rows[0]["detail"] and IDS[DIGEST_B] in rows[0]["detail"]


@pytest.mark.parametrize("pinned", [[], [DIGEST_B]], ids=["runs-it", "runs-another-image"])
def test_staging_rollback_checks_the_rollback_digests_image_id(
    tmp_path: Path, env_example: Path, monkeypatch: pytest.MonkeyPatch, clock: None, pinned: Any
) -> None:
    """A staging rollback deploys the previous digest A: the smoke test checks A's image id,
    and a mismatch fails it with CI-DEP-003 and no rollback of its own."""
    ledger = tmp_path / "ledger.jsonl"
    docker = stateful_docker(monkeypatch, pinned=pinned)
    probes(monkeypatch)
    rollback = {"digest": DIGEST_A, "sha": "rollback", "environment": "staging"}
    assert run_deploy(tmp_path, env_example, ledger, **rollback) == (1 if pinned else 0)
    assert docker.ups == [DIGEST_A]
    checked = [c[-1] for c in docker.calls if c[:3] == ["docker", "image", "inspect"]]
    assert checked == [f"{REF}@{DIGEST_A}"]
    outcomes = [json.loads(x)["outcome"] for x in ledger.read_text(encoding="utf-8").splitlines()]
    assert outcomes == ["sha-mismatch" if pinned else "success"]


def test_read_last_success_digest_missing_ledger_returns_none(tmp_path: Path) -> None:
    assert dd.read_last_success_digest("dev", tmp_path / "nope.jsonl") is None


def test_read_last_success_digest_skips_seed_and_blank_lines(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text(
        "\n"
        + json.dumps(
            {
                "sha": "seed-sha",
                "digest": "sha256:" + "9" * 64,
                "environment": "dev",
                "actor": "seed",
                "outcome": "success",
            }
        )
        + "\n\n"
        + json.dumps(
            {
                "sha": "real-sha",
                "digest": "sha256:" + "8" * 64,
                "environment": "dev",
                "actor": "ci",
                "outcome": "success",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    assert dd.read_last_success_digest("dev", ledger) == "sha256:" + "8" * 64


def test_read_last_success_digest_before_line_excludes_later_entries(
    tmp_path: Path,
) -> None:
    ledger = tmp_path / "ledger.jsonl"
    dd.append_ledger(
        dd.LedgerEntry(
            sha="s1",
            digest="sha256:" + "1" * 64,
            environment="dev",
            actor="ci",
            timestamp="t1",
            outcome="success",
        ),
        ledger,
    )
    dd.append_ledger(
        dd.LedgerEntry(
            sha="s2",
            digest="sha256:" + "2" * 64,
            environment="dev",
            actor="ci",
            timestamp="t2",
            outcome="success",
        ),
        ledger,
    )
    assert (
        dd.read_last_success_digest("dev", ledger, before_line=1)
        == "sha256:" + "1" * 64
    )


def test_compose_up_raises_ci_dep_002_on_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        dd.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(
            returncode=1, stderr="compose failed: port in use"
        ),
    )
    with pytest.raises(dd.DeployError) as exc:
        dd.compose_up(COMPOSE, image_ref=REF, digest=DIGEST)
    assert exc.value.code == "CI-DEP-002"
    assert "port in use" in str(exc.value)


def test_auto_rollback_no_previous_digest_logs_and_returns(
    tmp_path: Path, env_example: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ledger = tmp_path / "ledger.jsonl"
    dd._auto_rollback(
        environment="dev",
        actor="ci",
        repository="o/r",
        image_ref="ghcr.io/o/img",
        env_example=env_example,
        env_out=tmp_path / ".env",
        compose_files=("infra/compose/docker-compose.yml",),
        base_url="http://x",
        ledger_path=ledger,
        smoke_timeout_s=1.0,
        failed_digest="sha256:" + "b" * 64,
    )
    assert not ledger.exists() or ledger.read_text(encoding="utf-8") == ""
    assert "no previous known-good digest" in capsys.readouterr().err


def test_auto_rollback_signature_failure_records_smoke_failed(
    tmp_path: Path, env_example: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ledger = tmp_path / "ledger.jsonl"
    good_digest = "sha256:" + "1" * 64
    dd.append_ledger(
        dd.LedgerEntry(
            sha="prev-sha",
            digest=good_digest,
            environment="dev",
            actor="ci",
            timestamp="2026-01-01T00:00:00Z",
            outcome="success",
        ),
        ledger,
    )
    monkeypatch.setattr(
        dd.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=1, stderr="bad sig"),
    )
    dd._auto_rollback(
        environment="dev",
        actor="ci",
        repository="o/r",
        image_ref="ghcr.io/o/img",
        env_example=env_example,
        env_out=tmp_path / ".env",
        compose_files=("infra/compose/docker-compose.yml",),
        base_url="http://x",
        ledger_path=ledger,
        smoke_timeout_s=0.05,
        failed_digest="sha256:" + "b" * 64,
    )
    rows = [json.loads(l) for l in ledger.read_text(encoding="utf-8").splitlines()]
    assert rows[-1]["outcome"] == "smoke-failed"
    assert "auto-rollback failed" in rows[-1]["detail"]


def test_auto_rollback_never_ready_raises_ci_dep_002(
    tmp_path: Path, env_example: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ledger = tmp_path / "ledger.jsonl"
    good_digest = "sha256:" + "1" * 64
    dd.append_ledger(
        dd.LedgerEntry(
            sha="prev-sha",
            digest=good_digest,
            environment="dev",
            actor="ci",
            timestamp="2026-01-01T00:00:00Z",
            outcome="success",
        ),
        ledger,
    )
    monkeypatch.setattr(
        dd.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0, stderr="")
    )
    monkeypatch.setattr(dd, "compose_up", lambda *a, **k: None)
    monkeypatch.setattr(dd.time, "sleep", lambda _s: None)
    monkeypatch.setattr(dd, "_get_json", lambda *a, **k: {"status": "starting"})
    dd._auto_rollback(
        environment="dev",
        actor="ci",
        repository="o/r",
        image_ref="ghcr.io/o/img",
        env_example=env_example,
        env_out=tmp_path / ".env",
        compose_files=("infra/compose/docker-compose.yml",),
        base_url="http://x",
        ledger_path=ledger,
        smoke_timeout_s=0.05,
        failed_digest="sha256:" + "b" * 64,
    )
    rows = [json.loads(l) for l in ledger.read_text(encoding="utf-8").splitlines()]
    assert rows[-1]["outcome"] == "smoke-failed"
    assert "auto-rollback failed: CI-DEP-002: smoke test timed out" in rows[-1]["detail"]


def test_main_success_returns_zero_and_defaults_auto_rollback_for_dev(
    tmp_path: Path, env_example: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_docker(monkeypatch)
    probes(monkeypatch)
    ledger = tmp_path / "ledger.jsonl"
    rc = dd.main(
        [
            "--image-ref",
            "ghcr.io/o/img",
            "--digest",
            "sha256:" + "a" * 64,
            "--sha",
            "abc1234",
            "--environment",
            "dev",
            "--actor",
            "ci",
            "--repository",
            "o/r",
            "--env-example",
            str(env_example),
            "--env-out",
            str(tmp_path / ".env"),
            "--compose-file",
            "infra/compose/docker-compose.yml",
            "--base-url",
            "http://x",
            "--ledger",
            str(ledger),
            "--smoke-timeout-s",
            "5.0",
        ]
    )
    assert rc == 0
    rows = [json.loads(l) for l in ledger.read_text(encoding="utf-8").splitlines()]
    assert rows[-1]["outcome"] == "success"


def test_main_no_auto_rollback_flag_disables_rollback_for_dev(
    tmp_path: Path, env_example: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        dd.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=1, stderr="bad sig"),
    )
    ledger = tmp_path / "ledger.jsonl"
    rc = dd.main(
        [
            "--image-ref",
            "ghcr.io/o/img",
            "--digest",
            "sha256:" + "b" * 64,
            "--sha",
            "bad-sha",
            "--environment",
            "dev",
            "--actor",
            "ci",
            "--repository",
            "o/r",
            "--env-example",
            str(env_example),
            "--env-out",
            str(tmp_path / ".env"),
            "--compose-file",
            "infra/compose/docker-compose.yml",
            "--base-url",
            "http://x",
            "--ledger",
            str(ledger),
            "--no-auto-rollback",
        ]
    )
    assert rc == 1
    rows = [json.loads(l) for l in ledger.read_text(encoding="utf-8").splitlines()]
    assert rows[-1]["outcome"] == "signature-verification-failed"


def test_deploy_staging_never_auto_rolls_back(
    tmp_path: Path, env_example: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ledger = tmp_path / "ledger.jsonl"
    dd.append_ledger(
        dd.LedgerEntry(
            sha="prev-sha",
            digest="sha256:" + "1" * 64,
            environment="staging",
            actor="ci",
            timestamp="2026-01-01T00:00:00Z",
            outcome="success",
        ),
        ledger,
    )
    monkeypatch.setattr(
        dd.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0, stderr="")
    )
    monkeypatch.setattr(dd, "compose_up", lambda *a, **k: None)
    monkeypatch.setattr(dd.time, "sleep", lambda _s: None)
    monkeypatch.setattr(dd, "_get_json", lambda *a, **k: {"status": "starting"})

    rc = dd.deploy(
        image_ref="ghcr.io/o/img",
        digest="sha256:" + "b" * 64,
        sha="bad-sha",
        environment="staging",
        actor="ci",
        repository="o/r",
        env_example=env_example,
        env_out=tmp_path / ".env",
        compose_files=("infra/compose/docker-compose.yml",),
        base_url="http://x",
        ledger_path=ledger,
        smoke_timeout_s=0.05,
        auto_rollback=False,
    )
    assert rc == 1
    rows = [json.loads(l) for l in ledger.read_text(encoding="utf-8").splitlines()]
    assert all(r["outcome"] != "rolled-back" for r in rows)


def test_committed_deploy_overlay_passes_lint() -> None:
    """lint_compose's overlay rule, also run with this suite (infra/scripts/tests has the rest)."""
    assert lint_compose.lint(OVERLAY, deploy_overlay=True) == []


@pytest.mark.parametrize(
    ("key", "value", "why"),
    [
        ("build", {"context": "../..", "target": "builder"}, "builds locally"),
        ("volumes", ["../../services/api/candleviewer:/app/candleviewer:ro"], "mounts"),
    ],
    ids=["build", "source-mount"],
)
def test_deploy_overlay_lint_refuses(key: str, value: object, why: str) -> None:
    overlay = yaml.safe_load(OVERLAY.read_text(encoding="utf-8"))
    overlay["services"]["api"][key] = value
    errors = lint_compose.check_deploy_overlay(overlay)
    assert len(errors) == 1 and why in errors[0], errors
