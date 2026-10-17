"""Unit tests for tools/ci/check_image_no_dev_modules.py (#2893 S3, CI-IMG-006).

A fake `subprocess.run` stands in for the docker CLI (no daemon in the unit lane); the real runs
happen in main.yml before every image push and in the trivy job's boot smoke.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.ci import check_image_no_dev_modules as mod

IMAGE = "candleviewer-api:ci"
SPEC_FOUND = "find_spec: ModuleSpec(name='cvdev', loader=None, origin=None)\n"
TRACEBACK = 'Traceback (most recent call last):\n  File "<string>", line 1, in <module>\n'
SETTINGS_REFUSAL = (
    "pydantic_core._pydantic_core.ValidationError: 1 validation error for Settings\n"
    "account_fixture_dir\n  Value error, CV_ACCOUNT_FIXTURE is refused unless "
    "CV_ENVIRONMENT=demo [type=value_error, input_type=NoneType]"
)
#: What `cvdev`'s own re-check would raise: the package was importable, so the fence failed.
OTHER_REFUSAL = (
    "candleviewer.account_fixture_wiring.AccountFixtureRefused: "
    "CV_ACCOUNT_FIXTURE is refused unless CV_FEED=synthetic"
)


class FakeDocker:
    """Answers the two probes by their `-c` code and records every command."""

    def __init__(self, spec: tuple[int, str], boot: tuple[int, str]) -> None:
        self.answers = {mod.FIND_SPEC: spec, mod.BOOT: boot}
        self.commands: list[list[str]] = []

    def __call__(self, cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        assert kwargs["timeout"] == mod.TIMEOUT_S
        self.commands.append(cmd)
        returncode, output = self.answers[cmd[-1]]
        stdout, stderr = (output, "") if cmd[-1] == mod.FIND_SPEC else ("", output)
        return subprocess.CompletedProcess(cmd, returncode, stdout, stderr)


def _install(
    monkeypatch: pytest.MonkeyPatch, spec: tuple[int, str], boot: tuple[int, str]
) -> FakeDocker:
    fake = FakeDocker(spec, boot)
    monkeypatch.setattr(subprocess, "run", fake)
    return fake


ABSENT = (0, f"{mod.ABSENT}\n")
REFUSED = (1, f"{TRACEBACK}{mod.REFUSAL}\n")


def test_an_image_without_the_package_that_refuses_the_switch_passes(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = _install(monkeypatch, ABSENT, REFUSED)
    assert mod.main(["--image", IMAGE]) == 0
    assert [cmd[-1] for cmd in fake.commands] == [mod.FIND_SPEC, mod.BOOT]
    assert "CI-IMG-006" not in capsys.readouterr().err


@pytest.mark.parametrize(
    "spec",
    [
        (0, SPEC_FOUND),
        (1, "ModuleNotFoundError: No module named 'importlib'\n"),
        (0, ""),
        (1, f"{mod.ABSENT}\n"),
    ],
    ids=["importable", "probe-error", "no-output", "absent-but-exit-1"],
)
def test_a_dev_package_that_is_not_proven_absent_fails(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], spec: tuple[int, str]
) -> None:
    _install(monkeypatch, spec, REFUSED)
    assert mod.main(["--image", IMAGE]) == 1
    assert "CI-IMG-006: `cvdev` must not be importable" in capsys.readouterr().err


@pytest.mark.parametrize(
    "boot",
    [
        (0, ""),
        (1, f"{TRACEBACK}{SETTINGS_REFUSAL}\n"),
        (1, f"{TRACEBACK}{OTHER_REFUSAL}\n"),
        (1, f"{TRACEBACK}{mod.REFUSAL}\n\nDuring handling ...\nRuntimeError: boom\n"),
        (125, "docker: Error response from daemon: No such image: candleviewer-api:ci.\n"),
        (0, f"{mod.REFUSAL}\n"),
    ],
    ids=["booted", "settings-refusal", "other-refusal", "not-last", "docker-error", "exit-0"],
)
def test_a_boot_that_is_not_the_package_absent_refusal_fails(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], boot: tuple[int, str]
) -> None:
    _install(monkeypatch, ABSENT, boot)
    assert mod.main(["--image", IMAGE]) == 1
    assert "CI-IMG-006: a boot with CV_ENVIRONMENT=demo" in capsys.readouterr().err


@pytest.mark.parametrize(
    "error",
    [FileNotFoundError("docker"), subprocess.TimeoutExpired(["docker"], mod.TIMEOUT_S)],
    ids=["no-docker", "timeout"],
)
def test_a_docker_failure_fails_closed(monkeypatch: pytest.MonkeyPatch, error: Exception) -> None:
    def run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise error

    monkeypatch.setattr(subprocess, "run", run)
    assert mod.main(["--image", IMAGE]) == 1


def _value(cmd: list[str], flag: str) -> str:
    return cmd[cmd.index(flag) + 1]


def test_both_runs_are_offline_and_read_only_and_pass_only_the_named_variables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install(monkeypatch, ABSENT, REFUSED)
    mod.main(["--image", IMAGE])
    spec, boot = fake.commands
    for cmd in (spec, boot):
        assert cmd[:3] == ["docker", "run", "--rm"]
        assert _value(cmd, "--network") == "none"
        assert _value(cmd, "--pull") == "never"
        assert "--read-only" in cmd
        assert cmd[-3:-1] == [IMAGE, "-c"]
    assert "-e" not in spec
    passed = [boot[i + 1] for i, arg in enumerate(boot) if arg == "-e"]
    assert passed == ["CV_ENVIRONMENT=demo", "CV_FEED=synthetic", "CV_ACCOUNT_FIXTURE=compliant"]
    assert not [arg for arg in boot if "BYBIT" in arg]


def test_the_expected_refusal_is_the_wiring_modules_own_text() -> None:
    """The traceback's last line names the exception's module and class, then its message."""
    api = ROOT / "services" / "api"
    wiring = api / "candleviewer" / "account_fixture_wiring.py"
    tree = ast.parse(wiring.read_text(encoding="utf-8"))
    message = next(
        ast.literal_eval(node.value)
        for node in tree.body
        if isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and node.target.id == "NO_FIXTURE_TRANSPORT"
        and node.value is not None
    )
    assert "AccountFixtureRefused" in {n.name for n in tree.body if isinstance(n, ast.ClassDef)}
    module = ".".join(wiring.relative_to(api).with_suffix("").parts)
    assert mod.REFUSAL == f"{module}.AccountFixtureRefused: {message}"
