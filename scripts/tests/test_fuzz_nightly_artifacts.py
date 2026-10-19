"""#415 (E17-X02): the nightly fuzz job uploads a failing input only encrypted, on a seed it draws.

The repository is public. `fuzz-nightly.yml` writes a failure's (seed, input) pair to
`fuzz-failures/` and, when a job fails, uploads ONLY an `openssl enc` archive keyed from the Actions
secret `CV_FUZZ_ARTIFACT_KEY`, 32 characters or more. The key reaches that one step through its
environment: never on a command line, never as `${{ secrets.* }}` inside `run:` text. Without it
nothing is uploaded, and the plain directory is deleted either way. Each job's fuzz step draws its
seed from /dev/urandom, exports it to the suite alone and prints nothing; the runner never holds it
($GITHUB_ENV) and no other step, `env:` map or dispatch input names it. Static checks of the
workflow, then the encrypt and the fuzz steps run as written, against stand-ins."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
TEXT = (ROOT / ".github" / "workflows" / "fuzz-nightly.yml").read_text(encoding="utf-8")
DOC: dict[Any, Any] = yaml.safe_load(TEXT)  # PyYAML reads the key `on` as True
KEY = "CV_FUZZ_ARTIFACT_KEY"
FULL = "k" * 32  # the shortest key the encrypt step takes: 32 characters
ARCHIVES = {"python": "fuzz-failures-python.enc", "typescript": "fuzz-failures-typescript.enc"}
DECRYPT = f"openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -pass env:{KEY}"
NO_KEY = "key missing or short: nothing uploaded"
DRAW = [("python", "uv"), ("typescript", "pnpm")]  # job, the launcher of its suite
WIDTH = 8  # bytes of /dev/urandom: a 64-bit seed in both jobs
LOCAL = not os.environ.get("CI")  # off CI a missing tool skips a test; on CI it fails the test


def _steps(job: str) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = DOC["jobs"][job]["steps"]
    return steps


def _encrypt(job: str) -> dict[str, Any]:
    (step,) = [s for s in _steps(job) if "openssl" in s.get("run", "")]
    return step


def _fuzz(job: str) -> dict[str, Any]:
    (step,) = [s for s in _steps(job) if "/dev/urandom" in s.get("run", "")]
    return step


def _upload(job: str) -> dict[str, Any]:
    (step,) = [s for s in _steps(job) if str(s.get("uses", "")).startswith("actions/upload-")]
    return step


def _bash(script: str, cwd: Path, **env: str) -> subprocess.CompletedProcess[str]:
    """A step's script, run as the runner runs it (`bash -e`), with `env` added."""
    return subprocess.run(  # noqa: S603 -- fixed argv: bash and a workflow step's own text (#415)
        ["bash", "-e", "-c", script],  # noqa: S607 -- bash from PATH, as the runner finds it (#415)
        cwd=cwd,
        env={**os.environ, **env},
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize(("job", "archive"), ARCHIVES.items())
def test_each_job_uploads_only_its_archive_after_encrypting_it(job: str, archive: str) -> None:
    steps, upload = _steps(job), _upload(job)
    assert steps.index(_fuzz(job)) < steps.index(_encrypt(job)) < steps.index(upload)
    assert upload["with"]["path"] == archive  # one file, ending in .enc: not the plain directory
    assert upload["if"] == "failure()" and upload["with"]["if-no-files-found"] == "ignore"
    assert _encrypt(job)["if"] == "failure()" and "path: fuzz-failures/" not in TEXT
    # the suites write to <workspace>/fuzz-failures; the encrypt step tars `fuzz-failures` and
    # writes its archive, both relative, so it must run at the workspace root
    assert DOC["env"]["CV_FUZZ_ARTIFACT_DIR"] == "${{ github.workspace }}/fuzz-failures"
    assert "working-directory" not in _encrypt(job)


@pytest.mark.parametrize(("job", "archive"), ARCHIVES.items())
def test_openssl_reads_the_key_from_the_environment(job: str, archive: str) -> None:
    run = _encrypt(job)["run"]
    assert re.findall(r"-pass\s+(\S+)", run) == [f"env:{KEY}"]
    cipher = re.search(r"openssl enc -aes-256-cbc -pbkdf2 -salt -iter (\d+)\b", run)
    assert cipher and int(cipher.group(1)) >= 200_000 and f"-out {archive}" in run
    assert re.findall(rf"\$\{{?#?{KEY}", run) == [f"${{#{KEY}"]  # only its length is expanded
    assert NO_KEY in run and "rm -rf fuzz-failures" in run
    assert DECRYPT in TEXT  # the header names the command that reads the archive


def test_the_secret_only_reaches_the_environment_of_the_encrypt_steps() -> None:
    assert TEXT.count("secrets.") == 2
    for job in ARCHIVES:
        assert _encrypt(job)["env"] == {KEY: f"${{{{ secrets.{KEY} }}}}"}
        assert not [s for s in _steps(job) if "secrets." in s.get("run", "")]


def test_permissions_are_read_only_and_every_action_is_pinned_to_a_commit() -> None:
    assert DOC["permissions"] == {"contents": "read"}
    uses = [s["uses"] for job in DOC["jobs"].values() for s in job["steps"] if "uses" in s]
    assert uses and all(re.search(r"@[0-9a-f]{40}$", u) for u in uses)


def test_each_fuzz_step_draws_its_seed_and_nothing_else_names_it() -> None:
    for job, _ in DRAW:
        steps, fuzz = _steps(job), _fuzz(job)
        assert "mutation fuzz" in fuzz["name"] and "${{" not in fuzz["run"] and "env" not in fuzz
        assert f"od -An -N{WIDTH} -tu{WIDTH} /dev/urandom" in fuzz["run"]
        envs = [DOC["env"], DOC["jobs"][job].get("env", {}), *(s.get("env", {}) for s in steps)]
        assert not [e for e in envs if "CV_FUZZ_SEED" in e]  # no env map sets it
        assert not [s for s in steps if s is not fuzz and "seed" in s.get("run", "").lower()]
        assert not [s for s in steps if "GITHUB_ENV" in s.get("run", "")]  # the runner holds none
    assert set(DOC[True]["workflow_dispatch"]["inputs"]) == {"examples"}  # no input offers a seed


@pytest.mark.skipif(LOCAL and not all(map(shutil.which, ("od", "tr"))), reason="od, tr")
@pytest.mark.parametrize(("job", "launcher"), DRAW)
def test_the_fuzz_step_hands_the_seed_to_its_suite_as_written(
    job: str, launcher: str, tmp_path: Path
) -> None:
    run, seen, call = _fuzz(job)["run"], tmp_path / "seen", f"-An -N{WIDTH} -tu{WIDTH} /dev/urandom"
    stubs = {  # the suite's launcher records its seed; od answers only the documented call
        tmp_path / "suite" / launcher: f'printf %s "$CV_FUZZ_SEED" > {seen}',
        tmp_path / "od" / "od": f'[ "$*" = "{call}" ] && echo " 7342951"',
    }
    for stub, script in stubs.items():
        stub.parent.mkdir()
        stub.write_text(f"#!/bin/sh\n{script}\n", encoding="utf-8")
        stub.chmod(0o755)

    def go(od: bool, script: str = run) -> subprocess.CompletedProcess[str]:
        seen.unlink(missing_ok=True)
        dirs = [tmp_path / "suite", *([tmp_path / "od"] if od else [])]
        return _bash(script, tmp_path, PATH=os.pathsep.join([*map(str, dirs), os.environ["PATH"]]))

    done = go(od=True)  # the suite gets what od read, and nothing is printed
    assert (done.returncode, done.stdout, done.stderr) == (0, "", "")
    assert seen.read_text(encoding="utf-8") == "7342951"
    done = go(od=False)  # the real draw: an unsigned integer that fits its width
    assert (done.returncode, done.stdout, done.stderr) == (0, "", "")
    assert seen.read_text(encoding="utf-8").isdigit() and int(seen.read_text()) < 256**WIDTH
    done = go(od=True, script=run.replace(call, "-X"))  # od fails, prints nothing: no suite run
    assert done.returncode != 0 and not seen.exists()


@pytest.mark.skipif(LOCAL and not all(map(shutil.which, ("openssl", "tar"))), reason="openssl, tar")
@pytest.mark.parametrize(("job", "archive"), ARCHIVES.items())
def test_the_encrypt_step_works_as_written(job: str, archive: str, tmp_path: Path) -> None:
    plain = tmp_path / "fuzz-failures"

    def step(key: str) -> subprocess.CompletedProcess[str]:
        plain.mkdir(exist_ok=True)
        (plain / "t-1.json").write_text('{"input": "c2VjcmV0"}', encoding="utf-8")
        return _bash(_encrypt(job)["run"], tmp_path, **{KEY: key})

    for key in ("", FULL[:-1]):  # no key, or one character short: nothing encrypted, none left
        done = step(key)
        assert (done.returncode, done.stdout.strip()) == (0, NO_KEY)
        assert not (tmp_path / archive).exists() and not plain.exists()
    done = step(FULL)  # the shortest key taken: nothing printed, only the archive remains
    blob = (tmp_path / archive).read_bytes()
    assert (done.returncode, done.stdout, done.stderr) == (0, "", "") and not plain.exists()
    assert blob.startswith(b"Salted__")
    assert not [p for p in (b"c2VjcmV0", b"t-1.json", FULL.encode()) if p in blob]
    opened = _bash(f"{DECRYPT} -in {archive} | tar -xzf -", tmp_path, **{KEY: FULL})
    assert opened.returncode == 0, opened.stderr
    assert (plain / "t-1.json").read_text(encoding="utf-8") == '{"input": "c2VjcmV0"}'
