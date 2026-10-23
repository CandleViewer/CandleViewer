"""Unit tests for tools/ci/deploy_dev.py (E03-T09 dev/staging deploy).

No docker/network: `subprocess.run` and `urllib.request.urlopen` are
monkeypatched so these run fully offline (C-13.5 / AGENTS.md §8.7).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.ci import deploy_dev as dd


@pytest.fixture()
def env_example(tmp_path: Path) -> Path:
    p = tmp_path / ".env.example"
    p.write_text(
        "CV_ENVIRONMENT=demo\nCV_FEED=synthetic\nCV_GIT_SHA=unknown\n", encoding="utf-8"
    )
    return p


CONTAINER_ID = "c0ffee000000"  # 12 hex digits, as `docker compose ps -q` prints one
COMPOSE = ("infra/compose/docker-compose.yml",)
DECOY = "decoy-decoy-decoy"  # a credential in the container's environment


def fake_docker(
    monkeypatch: pytest.MonkeyPatch,
    ps: tuple[int, str] = (0, CONTAINER_ID + "\n"),
    inspect: tuple[int, str] | list[tuple[int, str]] = (0, "CV_GIT_SHA=abc1234\n"),
) -> SimpleNamespace:
    """Fake `subprocess.run`: cosign and `compose up` succeed, the smoke test's two
    queries answer (rc, stdout); a list of `inspect` answers is used one per call.
    `.calls` logs each argv, `.kwargs` its keywords."""
    log = SimpleNamespace(calls=[], kwargs=[])
    answers = list(inspect) if isinstance(inspect, list) else [inspect]

    def run(cmd: list[str], **kwargs: object) -> SimpleNamespace:
        log.calls.append(cmd)
        log.kwargs.append(kwargs)
        if cmd[:2] == ["docker", "inspect"]:
            rc, out = answers.pop(0) if len(answers) > 1 else answers[0]
        else:
            rc, out = ps if "ps" in cmd else (0, "")
        return SimpleNamespace(returncode=rc, stdout=out, stderr="")

    monkeypatch.setattr(dd.subprocess, "run", run)
    return log


def probes(monkeypatch: pytest.MonkeyPatch, **healthz: object) -> list[str]:
    """Both probes say ok (`healthz` adds keys to its body); returns the urls polled."""
    urls: list[str] = []

    def fake_get_json(url: str, timeout_s: float = 3.0) -> dict:
        urls.append(url)
        return {"status": "ok", **healthz} if "healthz" in url else {"status": "ok"}

    monkeypatch.setattr(dd, "_get_json", fake_get_json)
    return urls


def test_render_env_file_sets_digest_and_sha(tmp_path: Path, env_example: Path) -> None:
    out = tmp_path / ".env"
    dd.render_env_file(
        env_example, out, image_digest="sha256:" + "a" * 64, git_sha="abc1234"
    )
    text = out.read_text(encoding="utf-8")
    assert "CV_GIT_SHA=abc1234" in text
    assert "CV_IMAGE_DIGEST=sha256:" + "a" * 64 in text
    assert "CV_FEED=synthetic" in text


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


def test_smoke_test_passes_when_the_container_has_the_deployed_sha(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    urls = probes(monkeypatch)
    docker = fake_docker(monkeypatch)
    dd.smoke_test("http://x", "abc1234", COMPOSE, timeout_s=5.0)
    assert urls == ["http://x/healthz", "http://x/readyz"]
    ps, inspect = docker.calls
    assert " ".join(ps) == (
        "docker compose -f infra/compose/docker-compose.yml --profile core ps -q api"
    )
    assert inspect[:5] == ["docker", "inspect", "--type", "container", "--format"]
    assert inspect[5:] == [dd._INSPECT_SHA_TEMPLATE, CONTAINER_ID]
    # The module's subprocess style: captured output, no `check`, and a bound.
    assert all(k["capture_output"] and k["check"] is False for k in docker.kwargs)
    assert all(k["timeout"] for k in docker.kwargs)


def test_inspect_template_prints_only_the_sha_entry() -> None:
    assert dd._INSPECT_SHA_TEMPLATE == (
        '{{range .Config.Env}}{{if eq (index (split . "=") 0) "CV_GIT_SHA"}}'
        "{{.}}{{end}}{{end}}"
    )


def test_smoke_test_passes_with_a_healthz_body_without_git_sha(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#4222's precondition: the probes may stop carrying the sha."""
    body = {"status": "ok", "version": "0.1.0"}
    monkeypatch.setattr(dd, "_get_json", lambda *a, **k: body)
    fake_docker(monkeypatch)
    dd.smoke_test("http://x", "abc1234", COMPOSE, timeout_s=5.0)


def test_smoke_test_sha_mismatch_raises_ci_dep_003(
    monkeypatch: pytest.MonkeyPatch, clock: None
) -> None:
    probes(monkeypatch, git_sha="new-sha")  # /healthz claims the deployed sha, the
    fake_docker(monkeypatch, inspect=(0, "CV_GIT_SHA=old-sha\n"))  # container does not
    with pytest.raises(dd.DeployError) as exc:
        dd.smoke_test("http://x", "new-sha", COMPOSE, timeout_s=5.0)
    assert exc.value.code == "CI-DEP-003"
    assert "new-sha" in str(exc.value) and "old-sha" in str(exc.value)


def test_smoke_test_retries_until_the_container_has_the_deployed_sha(
    monkeypatch: pytest.MonkeyPatch, clock: None
) -> None:
    probes(monkeypatch)
    answers = [(0, "CV_GIT_SHA=old-sha\n"), (0, "CV_GIT_SHA=abc1234\n")]
    docker = fake_docker(monkeypatch, inspect=answers)
    dd.smoke_test("http://x", "abc1234", COMPOSE, timeout_s=5.0)
    assert sum(c[:2] == ["docker", "inspect"] for c in docker.calls) == 2


def test_smoke_test_with_no_api_container_fails_closed(
    monkeypatch: pytest.MonkeyPatch, clock: None
) -> None:
    probes(monkeypatch)
    docker = fake_docker(monkeypatch, ps=(0, ""))
    with pytest.raises(dd.DeployError) as exc:
        dd.smoke_test("http://x", "abc1234", COMPOSE, timeout_s=5.0)
    assert exc.value.code == "CI-DEP-002"
    assert "printed 0 value(s)" in str(exc.value)
    assert "no attempt made" not in str(exc.value)  # the loop ran
    assert not any(c[:2] == ["docker", "inspect"] for c in docker.calls)


@pytest.mark.parametrize("query", ["ps", "inspect"])
def test_smoke_test_failed_docker_query_fails_closed(
    monkeypatch: pytest.MonkeyPatch, clock: None, query: str
) -> None:
    """The exit status decides, not stdout: a query that exits 1 yet prints a
    plausible answer must not be believed."""
    probes(monkeypatch)
    plausible = {"ps": (1, CONTAINER_ID + "\n"), "inspect": (1, "CV_GIT_SHA=abc1234\n")}
    fake_docker(monkeypatch, **{query: plausible[query]})
    with pytest.raises(dd.DeployError) as exc:
        dd.smoke_test("http://x", "abc1234", COMPOSE, timeout_s=5.0)
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
        dd.smoke_test("http://x", "abc1234", COMPOSE, timeout_s=5.0)
    assert exc.value.code == "CI-DEP-002"
    assert "did not complete" in str(exc.value)


LEAK = f"POSTGRES_PASSWORD={DECOY}"
OK_ID, OK_SHA = (0, CONTAINER_ID + "\n"), (0, "CV_GIT_SHA=abc1234\n")


@pytest.mark.parametrize(
    ("ps", "inspect"),
    [
        (OK_ID, (0, LEAK + "\n")),  # another variable, not the sha
        (OK_ID, (0, LEAK + "\nCV_GIT_SHA=abc1234\n")),  # docker did not filter
        (OK_ID, (0, "CV_GIT_SHA=abc1234\n" + LEAK + "\n")),
        ((0, LEAK + "\n"), OK_SHA),  # a variable where a container id belongs
        ((0, CONTAINER_ID + " " + LEAK + "\n"), OK_SHA),
    ],
)
def test_smoke_test_never_echoes_what_docker_printed(
    monkeypatch: pytest.MonkeyPatch,
    clock: None,
    capsys: pytest.CaptureFixture[str],
    ps: tuple[int, str],
    inspect: tuple[int, str],
) -> None:
    """Anything docker prints beyond the one CV_GIT_SHA entry is refused, and no
    message, repr or output repeats it (C-12.2, C-12.6)."""
    probes(monkeypatch)
    fake_docker(monkeypatch, ps=ps, inspect=inspect)
    with pytest.raises(dd.DeployError) as exc:
        dd.smoke_test("http://x", "abc1234", COMPOSE, timeout_s=5.0)
    assert exc.value.code == "CI-DEP-002"
    out, err = capsys.readouterr()
    assert DECOY not in f"{exc.value} {exc.value!r} {out} {err}"


def test_smoke_test_never_ready_raises_ci_dep_002(
    monkeypatch: pytest.MonkeyPatch, clock: None
) -> None:
    monkeypatch.setattr(dd, "_get_json", lambda *a, **k: {"status": "starting"})
    docker = fake_docker(monkeypatch)
    with pytest.raises(dd.DeployError) as exc:
        dd.smoke_test("http://x", "abc1234", COMPOSE, timeout_s=5.0)
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


def test_deploy_container_sha_mismatch_records_sha_mismatch(
    tmp_path: Path, env_example: Path, monkeypatch: pytest.MonkeyPatch, clock: None
) -> None:
    probes(monkeypatch)
    docker = fake_docker(monkeypatch, inspect=(0, "CV_GIT_SHA=old-sha\n"))
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
    assert "old-sha" in rows[-1]["detail"]
    assert "new-sha" in rows[-1]["detail"]
    # The container is looked up in the compose project this deploy brought up.
    ps = next(c for c in docker.calls if "ps" in c)
    assert ps[:7] == ["docker", "compose", "-f", "a.yml", "-f", "b.yml", "--profile"]


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
    tmp_path: Path, env_example: Path, monkeypatch: pytest.MonkeyPatch
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

    monkeypatch.setattr(
        dd.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0, stderr="")
    )
    monkeypatch.setattr(dd, "compose_up", lambda *a, **k: None)
    monkeypatch.setattr(dd.time, "sleep", lambda _s: None)

    call_count = {"n": 0}

    def fake_get_json(url: str, timeout_s: float = 3.0) -> dict:
        call_count["n"] += 1
        # Forward deploy never becomes ready -> CI-DEP-002; rollback's
        # readiness-only poll succeeds immediately.
        if "readyz" in url and call_count["n"] > 2:
            return {"status": "ok"}
        return {"status": "starting"}

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
        dd.compose_up(("infra/compose/docker-compose.yml",))
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
    assert "rollback smoke test did not become ready" in rows[-1]["detail"]


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
