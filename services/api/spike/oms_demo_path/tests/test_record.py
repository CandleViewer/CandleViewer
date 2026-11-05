# ruff: noqa: S101  (pytest asserts: the project's tests/** ignore does not reach spike/)
"""The record judges itself (#843 A4 fold 1; the coordinator's 07:16Z and 09:37Z asks): budget
#4's rule and verdict, the signing share timed on its own, the two ordering counts kept apart,
the soak's idle phase, the ADR-0006 addendum template and the README's two sentences."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

import pytest

from candleviewer.exchange.base.errors import TransportError
from candleviewer.secrets import KEY_ID_SLOT, CredentialBorrower, RequestSignature, Secret
from spike.oms_demo_path import compose as composition
from spike.oms_demo_path import measure, modes, report, run
from spike.oms_demo_path.config import RunConfig
from spike.oms_demo_path.measure import Timings, gap_stats, timed_borrower
from spike.oms_demo_path.offline import Corpus, CorpusVenue, default_corpus
from spike.oms_demo_path.tests.test_cycles import _every_output
from spike.oms_demo_path.tests.test_modes import _Rig

if TYPE_CHECKING:
    from candleviewer.secrets import Purpose
    from candleviewer.secrets.signing import SigningMessage

#: The rule #843 agreed up front, as the record must print it (the coordinator, 09:37Z).
RULE = "p95 create RTT > 250 ms ⇒ budget #4 renegotiated in `06` §5.2, never absorbed by our 50 ms"
MESSAGE = (b"1790000000000", KEY_ID_SLOT, b"5000", b'{"category":"linear"}')


def _venue(**options: Any) -> CorpusVenue:
    return CorpusVenue(Corpus(default_corpus()), **options)


def _cfg(out: Path, **fields: Any) -> RunConfig:
    base: dict[str, Any] = {"mode": "cycles", "out": out, "cycles": 4, "min_hours": 0.0}
    return RunConfig(**(base | {"fill_wait_s": 0.2} | fields))


def _summary(out: Path) -> dict[str, Any]:
    return dict(run.summary_of(out))


# -- budget #4: the rule, the three p95s, the verdict ------------------------------------------


def test_the_budget_rule_is_the_agreed_text() -> None:
    assert run.BUDGET4_RULE == RULE


@pytest.mark.parametrize(
    ("rtt_p95_ms", "verdict"),
    [
        (None, "no data"),
        (12.4, "within"),
        (250.0, "within"),
        (250.1, "renegotiate"),
        (900.0, "renegotiate"),
    ],
)
def test_budget4_verdict_falls_on_each_side_of_the_rule(
    rtt_p95_ms: float | None, verdict: str
) -> None:
    assert run.budget4_verdict(rtt_p95_ms) == verdict


def _timings(rtt: float, port: float, signing: float, n: int = 20) -> Timings:
    timings = Timings()
    timings.rtt_ms["create"] = [rtt] * n
    timings.port_ms["create"] = [port] * n
    timings.overhead_ms["create"] = [port - rtt] * n
    timings.signing_ms["create"] = [signing] * n
    return timings


def test_the_budget_block_holds_the_three_p95s_the_signing_share_and_the_verdict() -> None:
    block = run.budget(_timings(rtt=280.0, port=330.0, signing=12.0), offline=False)
    assert block["rule"] == RULE and block["verdict"] == "renegotiate"
    assert block["evidence"] is True
    assert (block["create_rtt_p95_ms"], block["create_overhead_p95_ms"]) == (280.0, 50.0)
    assert block["create_end_to_end_p95_ms"] == 330.0
    assert block["create_signing_ms"] == {"n": 20, "p50": 12.0, "p95": 12.0, "max": 12.0}
    assert block["rtt_within_250ms"] is False and block["overhead_within_50ms"] is True
    assert block["end_to_end_within_300ms"] is False
    within = run.budget(_timings(rtt=200.0, port=240.0, signing=9.0), offline=True)
    assert within["verdict"] == "within" and within["evidence"] is False
    nothing = run.budget(Timings(), offline=True)
    assert nothing["verdict"] == "no data" and nothing["create_rtt_p95_ms"] is None
    assert nothing["create_signing_ms"] == {"n": 0, "p50": None, "p95": None, "max": None}


def _write_summary(run_dir: Path, summary: dict[str, Any]) -> Path:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
    return run_dir


@pytest.mark.parametrize("verdict", ["within", "renegotiate", "no data"])
def test_the_report_prints_the_rule_verbatim_and_the_verdict(tmp_path: Path, verdict: str) -> None:
    stats = {"n": 20, "p50": 1.0, "p95": 2.0, "max": 3.0}
    summary = {
        "mode": "cycles",
        "offline": False,
        "budget4": {"rule": RULE, "verdict": verdict, "evidence": True},
        "rtt_ms": {"create": stats},
        "overhead_ms": {"create": stats},
        "signing_ms": {"create": stats},
    }
    text = report.render(_write_summary(tmp_path / "run", summary))
    assert f"Rule: {RULE}\n" in text and f"Verdict: **{verdict}**\n" in text
    assert "| of which signing: M2's key read and fsynced audit append | 20 | 1.0 |" in text
    assert "| end to end, port call to ack | missing | missing |" in text


# -- the signing share, timed on its own -----------------------------------------------------


async def test_the_timed_borrower_passes_the_call_through_unchanged() -> None:
    seen: list[tuple[UUID, object, str]] = []
    answer = RequestSignature(Secret("K" * 18), "ab" * 32)

    async def sign(key_id: UUID, message: object, purpose: str) -> RequestSignature:
        seen.append((key_id, message, purpose))
        return answer

    wrapped = timed_borrower(CredentialBorrower(sign), Timings())
    key = uuid4()
    for purpose in ("sign_rest", "sign_ws_auth"):
        assert await wrapped.sign(key, MESSAGE, purpose=purpose) is answer
    assert seen == [(key, MESSAGE, "sign_rest"), (key, MESSAGE, "sign_ws_auth")]
    assert all(message is MESSAGE for _, message, _ in seen)


async def test_the_timed_borrower_times_each_sign_under_its_call_or_its_purpose() -> None:
    ticks = iter([0.0, 1.0, 1.004, 1.5, 1.75, 2.0, 3.0, 3.5])
    timings = Timings(monotonic=lambda: next(ticks))

    async def sign(_key: UUID, _message: object, purpose: str) -> RequestSignature:
        if purpose == "key_verify":
            raise RuntimeError("refused inside M2")
        return RequestSignature(Secret("K" * 18), "ab" * 32)

    wrapped = timed_borrower(CredentialBorrower(sign), timings)
    async with timings.call("create"):
        await wrapped.sign(uuid4(), MESSAGE, purpose="sign_rest")  # 1.0 -> 1.004
        await wrapped.sign(uuid4(), MESSAGE, purpose="sign_ws_auth")  # 1.5 -> 1.75
    with pytest.raises(RuntimeError, match="refused inside M2"):
        await wrapped.sign(uuid4(), MESSAGE, purpose="key_verify")  # 3.0 -> 3.5
    assert dict(timings.signing_ms) == {
        "create": [pytest.approx(4.0)],
        "sign_ws_auth": [pytest.approx(250.0)],
        "key_verify": [pytest.approx(500.0)],
    }
    signing = timings.summary()["signing_ms"]
    assert signing["overall"]["n"] == 3 and signing["overall"]["max"] == 500.0
    assert timings.port_ms["create"] == [pytest.approx(2000.0)]


async def test_every_m2_sign_is_timed_and_no_signature_or_key_id_reaches_an_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Offline over the in-memory M2, wrapped as online: a spy under the timing wrapper keeps
    what M2 returned (the scan's targets), then every output file is scanned for it."""
    returned: list[str] = []
    real = measure.timed_borrower

    def spied(borrower: CredentialBorrower, timings: Timings) -> CredentialBorrower:
        async def sign(key_id: UUID, message: SigningMessage, purpose: Purpose) -> RequestSignature:
            signed = await borrower.sign(key_id, message, purpose=purpose)
            returned.extend((signed.api_key.reveal(), signed.signature))
            return signed

        return real(CredentialBorrower(sign), timings)

    monkeypatch.setattr(composition, "timed_borrower", spied)
    out = tmp_path / "out"
    assert await run.run(_cfg(out), venue=_venue()) == 0
    s = _summary(out)
    signs = len(returned) // 2
    assert signs > 0 and s["signing_ms"]["overall"]["n"] == signs
    assert s["signing_ms"]["create"]["n"] == s["rtt_ms"]["create"]["n"] == 8
    assert s["signing_ms"]["sign_ws_auth"]["n"] == 1
    share = s["budget4"]["create_signing_ms"]
    assert share["n"] == 8 and share["p50"] <= share["p95"] <= share["max"]
    assert s["budget4"]["verdict"] == "within" and s["budget4"]["evidence"] is False
    assert (
        'spike_signing_seconds_count{call="create",env="demo"} 8.0'
        in (out / "metrics.prom").read_text()
    )
    text = _every_output(out)
    assert not [value for value in set(returned) if value in text]


# -- two ordering counts, kept apart --------------------------------------------------------------


def test_the_two_counts_carry_distinct_self_describing_names() -> None:
    assert measure.REORDER_COUNT == "venue_reorder_execution_after_its_order_transition"
    assert measure.DROPPED_COUNT == "dropped_push_execution_only_via_backfill"


async def test_the_reorder_and_the_dropped_push_are_counted_apart(tmp_path: Path) -> None:
    venue = _venue(drop_every=2, reorder_every=3)
    out = tmp_path / "out"
    assert await run.run(_cfg(out, cycles=6, drop_every=2, reorder_every=3), venue=venue) == 0
    assert venue.dropped > 0 and venue.reordered > 0 and venue.dropped != venue.reordered
    private = _summary(out)["private"]
    assert private["ordering_counts"] == {
        measure.REORDER_COUNT: venue.reordered,
        measure.DROPPED_COUNT: venue.dropped,
    }
    assert private["ordering"]["execution_after_order"] == venue.reordered  # the old keys stay
    assert private["parity"]["rest_only"] == venue.dropped
    text = report.render(out)
    assert f"| {measure.REORDER_COUNT} | {venue.reordered} |" in text
    assert f"| {measure.DROPPED_COUNT} | {venue.dropped} |" in text
    assert await run.run(RunConfig(mode="report", out=tmp_path / "rep", run_dir=out)) == 0
    addendum = (tmp_path / "rep" / report.ADDENDUM).read_text()
    before = addendum.index("#### Execution before its order transition")
    only = addendum.index("#### Execution only via the backfill")
    assert f"`{measure.REORDER_COUNT}`: **{venue.reordered}**" in addendum[before:only]
    assert f"`{measure.DROPPED_COUNT}`: **{venue.dropped}**" in addendum[only:]
    assert "The offline venue injected one every 3 fills." in addendum[before:only]
    assert f"Rule (#843, agreed up front): {RULE}" in addendum
    assert "Verdict: **within** (offline corpus venue: not evidence)" in addendum
    assert addendum.count("(offline corpus venue: not evidence)") >= 6
    assert oct((tmp_path / "rep" / report.ADDENDUM).stat().st_mode & 0o777) == "0o600"


# -- the soak's idle phase ------------------------------------------------------------------------


async def _soak(rig: _Rig, hours: float, *, plant: bool = False) -> dict[str, Any]:
    h, clock = rig.harness, rig.clock
    cfg = RunConfig(mode="soak", out=Path("/nonexistent"), hours=hours)
    task = asyncio.create_task(modes.run_soak(h, cfg))
    await clock.run_until(lambda: h.stream.live, within_s=60, what="the stream comes up")
    await clock.advance(60)
    if plant:
        rig.venue.plant_unpushed_fill()
    await clock.run_until(task.done, within_s=hours * 3600 + 600, what="the soak ends")
    result: dict[str, Any] = task.result()
    return result


async def test_a_clean_soak_holds_the_stream_with_no_orders_and_meets_zero_missed(
    tmp_path: Path,
) -> None:
    rig = _Rig(tmp_path, _venue())
    idle = (await _soak(rig, 0.05))["idle_phase"]
    assert idle["orders_sent"] == 0 and rig.venue.creates == []
    assert (idle["dials"], idle["reconnects"], idle["outages"]) == (1, 0, 0)
    assert idle["held_s"] >= 180.0
    ping, message = idle["ping_gaps_s"], idle["message_gaps_s"]
    assert ping["n"] >= 30 and ping["p50"] == ping["p95"] == ping["max"] == 5.0
    assert ping["over_threshold"] == message["over_threshold"] == 0
    assert message["n"] > ping["n"] and message["max"] <= 5.0
    assert idle["long_silence_s"] == 7.5
    assert idle["backfill"] == {"listed": 0, "on_stream": 0}
    assert idle["backfill_only_executions"] == 0
    assert idle["zero_missed_executions"] == "met"


async def test_a_soak_with_a_planted_backfill_only_execution_is_not_met(tmp_path: Path) -> None:
    rig = _Rig(tmp_path, _venue())
    idle = (await _soak(rig, 0.05, plant=True))["idle_phase"]
    assert idle["orders_sent"] == 0 and rig.venue.dropped == 1
    assert idle["backfill"] == {"listed": 1, "on_stream": 0}
    assert idle["backfill_only_executions"] == 1
    assert idle["zero_missed_executions"] == "not met"


async def test_a_soak_whose_backfill_read_fails_has_no_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = _Rig(tmp_path, _venue())

    async def unanswered(*_args: object) -> None:
        raise TransportError("the venue did not answer")

    monkeypatch.setattr(rig.harness.port, "executions", unanswered)
    idle = (await _soak(rig, 0.01))["idle_phase"]
    assert idle["backfill"] == {"error": "TransportError"}
    assert idle["backfill_only_executions"] is None
    assert idle["zero_missed_executions"] == "no data"


@pytest.mark.parametrize(("missed", "verdict"), [(None, "no data"), (0, "met"), (1, "not met")])
def test_zero_missed_executions_has_three_verdicts(missed: int | None, verdict: str) -> None:
    assert modes.zero_missed(missed) == verdict


def test_gap_stats_count_the_silences_over_the_threshold() -> None:
    assert gap_stats([5.0, 5.0, 8.0, 0.25, 7.5], 7.5) == {
        "n": 5,
        "p50": 5.0,
        "p95": 8.0,
        "max": 8.0,
        "over_threshold": 1,
    }
    assert gap_stats([], 7.5) == {"n": 0, "over_threshold": 0}


async def test_the_recording_socket_keeps_a_bounded_number_of_gaps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from spike.oms_demo_path import recorder
    from spike.oms_demo_path.outputs import RunOutputs
    from spike.oms_demo_path.scrub import Scrubber

    monkeypatch.setattr(recorder, "GAPS_KEPT", 3)
    venue, scrubber = _venue(), Scrubber()
    connector = recorder.RecordingConnector(
        venue.connect, scrubber=scrubber, outputs=RunOutputs(tmp_path / "out", scrubber)
    )
    sock = await connector("wss://stream-demo.bybit.com/v5/private")
    for _ in range(5):
        await sock.send(json.dumps({"op": "ping"}))
        await sock.recv(1 << 20)
    assert len(connector.message_gaps_s) == len(connector.ping_gaps_s) == 3
    assert connector.counts["received:op_pong"] == 5


# -- the ADR-0006 addendum template -----------------------------------------------------------


def _demo_soak_summary() -> dict[str, Any]:
    gaps = {"n": 17279, "p50": 5.0, "p95": 5.004, "max": 6.1, "over_threshold": 0}
    return {
        "mode": "soak",
        "offline": False,
        "started_at_ms": 1_793_000_000_000,
        "shutdown": {"reason": "completed"},
        "budget4": {"rule": RULE, "verdict": "no data", "evidence": True},
        "private": {
            "ordering_counts": {measure.REORDER_COUNT: 0, measure.DROPPED_COUNT: 0},
            "ordering": {"executions": 0},
            "parity": {"rest": 0},
        },
        "soak": {
            "hours": 24.0,
            "meets_ticket": True,
            "idle_phase": {
                "held_s": 86400.0,
                "orders_sent": 0,
                "dials": 1,
                "reconnects": 0,
                "outages": 0,
                "long_silence_s": 7.5,
                "ping_gaps_s": gaps,
                "message_gaps_s": gaps,
                "backfill": {"listed": 0, "on_stream": 0},
                "backfill_only_executions": 0,
                "zero_missed_executions": "met",
            },
        },
        "error_shapes": {"10002": {"retCode": 10002}, "110001": {"retCode": 110001}},
        "shapes": {"10002": {"raised": "ClockDriftError"}},
        "retention": {"rows": 400, "older_than_7d": 0, "by_state": {"cancelled": 400}},
    }


def test_the_addendum_of_a_demo_soak_fills_the_idle_phase_and_says_nothing_is_offline(
    tmp_path: Path,
) -> None:
    text = report.addendum(_write_summary(tmp_path / "run", _demo_soak_summary()))
    assert "not evidence" not in text and "Run on the demo venue" in text
    assert "Verdict: **no data**" in text
    assert "- **Zero missed executions: met.**" in text
    assert "- Ping gaps (s): n 17279, p50 5.0, p95 5.004, max 6.1; over 7.5 s: 0." in text
    assert "the ticket's 24 h: met" in text and "orders sent: 0" in text
    assert "None in this run." in text
    assert "| 10002 (clock drift) | captured: 10002 (`summary.error_shapes`) |" in text
    assert "| 110072 / 10001 (duplicate `orderLinkId`) | missing | missing |" in text
    assert "| other codes met | 110001 | |" in text
    assert "400 orders read back since the run's start; 0 older than 7 days" in text


def test_the_report_renders_the_idle_phase_as_a_section_of_its_own(tmp_path: Path) -> None:
    text = report.render(_write_summary(tmp_path / "run", _demo_soak_summary()))
    section = text[text.index("### Soak idle phase (ADR-0006 S3: zero missed executions)") :]
    assert section.index("Zero missed executions: **met**") < section.index("### Shutdown")
    assert "| orders_sent | 0 |" in section and "| backfill | listed 0, on_stream 0 |" in section
    assert "| ping_gaps_s | 17279 | 5.0 | 5.004 | 6.1 | 0 |" in section
    assert "| message_gaps_s | 17279 |" in section


def test_the_addendum_marks_what_a_run_did_not_measure(tmp_path: Path) -> None:
    text = report.addendum(_write_summary(tmp_path / "run", {"mode": "shapes", "offline": True}))
    assert text.startswith("<!-- A template for ADR-0006 §Validation")
    assert "**Offline run: every number below comes from the offline corpus venue" in text
    assert "missing: this is a `shapes` run; a `soak` run's summary has it." in text
    assert "missing: a `retention` run on day 8 or later carries it." in text
    assert "missing: no execution was measured." in text
    assert "started missing" in text and "| create RTT at the seam | missing |" in text
    rendered = report.render(tmp_path / "run")
    assert "### Budget #4" not in rendered and "### Soak idle phase" not in rendered


# -- the README's two sentences (the coordinator, 07:16Z) ----------------------------------------


def test_the_readme_carries_both_sentences_verbatim_and_says_throwaway_first() -> None:
    readme = (Path(run.__file__).parent / "README.md").read_text(encoding="utf-8")
    first, flat = readme.splitlines()[0], " ".join(readme.split())
    assert "throwaway" in first and "never merged" in first
    runbook = flat[flat.index("## Host runbook") :]
    for sentence in (
        "No manual trading on that demo account during a run.",
        "cv-api stopped or untouched: it opens no private stream and runs no reconciler, so it"
        " never acts on the harness's orders.",
    ):
        assert sentence in runbook[:1200]
