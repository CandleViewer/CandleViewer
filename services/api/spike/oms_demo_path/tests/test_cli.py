# ruff: noqa: S101  (pytest asserts: the project's tests/** ignore does not reach spike/)
"""The command line (#843 A4): an offline run completes under the session's no-network guard
(`conftest.py`: any connect or lookup fails the test); an online run is refused before anything
is written, signed or dialled without its flags or its typed confirmation."""

from __future__ import annotations

import json
import socket
from pathlib import Path
from uuid import uuid4

import pytest

from spike.oms_demo_path.__main__ import main
from spike.oms_demo_path.config import CONFIRMATION, parse
from spike.oms_demo_path.tests.conftest import Ledger, NetworkRefused


def test_an_offline_cycles_run_completes_with_no_network(tmp_path: Path) -> None:
    out = tmp_path / "out"
    argv = [
        "cycles",
        "--out",
        str(out),
        "--cycles",
        "2",
        "--min-hours",
        "0",
        "--fill-wait-s",
        "0.2",
    ]
    assert main(argv) == 0
    summary = json.loads((out / "summary.json").read_text())
    assert summary["offline"] is True and summary["cycles"]["completed"] == 2
    metrics = (out / "metrics.prom").read_text()
    assert 'order_submit_seconds_count{env="demo",transport="rest"} 4.0' in metrics
    for edge in ("0.05", "0.1", "0.2", "0.3", "0.4", "0.5", "0.75", "1.0", "2.0", "5.0"):
        assert f'le="{edge}"' in metrics
    assert "# HELP order_submit_seconds Order click-to-ack latency." in metrics
    assert "bybit_rest_latency_seconds" in metrics and "spike_rest_rtt_seconds" in metrics


@pytest.mark.parametrize(
    "extra",
    [
        [],
        ["--i-understand-this-places-demo-orders"],
        ["--i-understand-this-places-demo-orders", "--account-id", str(uuid4())],
    ],
)
def test_an_online_run_without_its_flags_or_ids_is_refused(
    tmp_path: Path, extra: list[str]
) -> None:
    out = tmp_path / "out"
    assert main(["cycles", "--demo", "--out", str(out), *extra]) == 2
    assert not out.exists()


def test_an_online_run_without_the_typed_confirmation_is_refused(tmp_path: Path) -> None:
    out = tmp_path / "out"
    argv = [
        "soak",
        "--demo",
        "--i-understand-this-places-demo-orders",
        "--account-id",
        str(uuid4()),
        "--key-ref",
        str(uuid4()),
        "--out",
        str(out),
    ]
    prompts: list[str] = []

    def typed(prompt: str) -> str:
        prompts.append(prompt)
        return CONFIRMATION.lower()

    assert main(argv, read_line=typed) == 2
    assert prompts == [f'Type "{CONFIRMATION}" to place demo orders: ']
    assert not out.exists()


def test_report_mode_prints_the_tables(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "out"
    assert (
        main(
            [
                "cycles",
                "--out",
                str(out),
                "--cycles",
                "1",
                "--min-hours",
                "0",
                "--fill-wait-s",
                "0.2",
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert main(["report", "--out", str(tmp_path / "unused"), "--run-dir", str(out)]) == 0
    assert "### Cycle outcomes" in capsys.readouterr().out


@pytest.mark.parametrize("online", [False, True])
def test_flatten_without_the_failed_runs_directory_is_refused(tmp_path: Path, online: bool) -> None:
    out = tmp_path / "out"
    ids = ["--account-id", str(uuid4()), "--key-ref", str(uuid4())]
    demo = ["--demo", "--i-understand-this-places-demo-orders", *ids] if online else []
    assert main(["flatten", "--out", str(out), *demo], read_line=lambda _p: CONFIRMATION) == 2
    assert not out.exists()


def test_offline_and_demo_together_is_a_usage_error() -> None:
    with pytest.raises(SystemExit) as exited:
        parse(["cycles", "--offline", "--demo", "--out", "/nonexistent"])
    assert exited.value.code == 2


def test_the_session_refuses_every_socket_loopback_included(no_network_verdict: Ledger) -> None:
    mark = len(no_network_verdict.attempts)
    with socket.socket() as sock, pytest.raises(NetworkRefused):
        sock.connect(("127.0.0.1", 9))
    with pytest.raises(NetworkRefused):
        socket.getaddrinfo("api-demo.bybit.com", 443)
    assert no_network_verdict.attempts[mark:] == ["socket.connect", "getaddrinfo"]
    del no_network_verdict.attempts[mark:]  # claimed: this test drove the guard on purpose


def test_a_run_never_reuses_an_earlier_runs_directory(tmp_path: Path) -> None:
    out = tmp_path / "out"
    out.mkdir()
    (out / "events.jsonl").write_text("{}\n")
    assert main(["cycles", "--out", str(out), "--cycles", "1", "--min-hours", "0"]) == 2
    assert (out / "events.jsonl").read_text() == "{}\n"


def test_a_setup_failure_is_refused_naming_its_class_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Ruling R1C-02 (a): any error before the run is armed, composition included, is a refused
    outcome naming the reason, with nothing touched."""
    from spike.oms_demo_path import run as runner

    def broken(_state: Path) -> None:
        raise RuntimeError("a value that must not be echoed")

    monkeypatch.setattr(runner, "offline_settings", broken)
    out = tmp_path / "out"
    assert main(["cycles", "--out", str(out), "--cycles", "1", "--min-hours", "0"]) == 2
    err = capsys.readouterr().err
    assert "refused: an error before the run was armed: RuntimeError" in err
    assert "must not be echoed" not in err
    summary = json.loads((out / "summary.json").read_text())
    assert summary["outcome"] == "refused"
    assert summary["refused"] == "an error before the run was armed: RuntimeError"
    assert summary["shutdown"]["action"] == "none" and summary["shutdown"]["armed"] is False
    assert "must not be echoed" not in (out / "summary.json").read_text()


def test_a_failure_before_any_output_reports_its_class_only(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "a-file-not-a-directory"
    out.write_text("not a run directory")
    assert main(["cycles", "--out", str(out), "--cycles", "1", "--min-hours", "0"]) == 1
    assert capsys.readouterr().err == "failed: NotADirectoryError\n"


def test_a_refused_kek_proof_writes_its_summary_and_closes_what_it_opened(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from candleviewer.secrets import KekCheckResult
    from spike.oms_demo_path import run as runner

    async def unenrolled(*_args: object) -> KekCheckResult:
        return KekCheckResult(None, False, "kek_not_enrolled")

    monkeypatch.setattr(runner, "offline_proof", unenrolled)
    out = tmp_path / "out"
    assert main(["cycles", "--out", str(out), "--cycles", "1", "--min-hours", "0"]) == 2
    summary = json.loads((out / "summary.json").read_text())
    assert summary["refused"].startswith("the KEK proof failed (kek_not_enrolled)")
    assert summary["outcome"] == "refused" and "cycles" not in summary
    assert summary["shutdown"] == {
        "reason": "refused",
        "armed": False,
        "action": "none",
        "cancelled": 0,
        "flatten_orders": 0,
        "closed_qty": "0",
    }
