"""E12-Q02 golden gate: a tape-only regeneration is exempt from the `BUILD_VERSIONS` bump (#2200).

The exemption holds only while the builder sources and every live spec hash equal the ones the
manifest recorded; any builder or spec change still needs the bump. Nothing here writes the bank.
"""

from __future__ import annotations

import dataclasses

import pytest

from bench.bar_conformance import bank
from bench.bar_determinism import regen_goldens, tapes
from candleviewer.exchange.base.models import TradeEvent

NAME = "edge-ticks"


@pytest.fixture
def one_tape_changed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Only the edge tape, one print shorter: a tape-only change for every builder kind."""
    real = tapes.TAPES[NAME]

    def shorter() -> tuple[list[TradeEvent], dict[str, object]]:
        out, meta = real.build()
        return out[:-1], meta

    monkeypatch.setattr(tapes, "TAPES", {NAME: dataclasses.replace(real, build=shorter)})
    monkeypatch.delenv("CI", raising=False)


def test_tape_only_regeneration_is_exempt_from_the_build_version_bump(
    one_tape_changed: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    p = bank.build("reason")
    assert p.changed and p.unbumped == []
    wrote: list[bool] = []
    monkeypatch.setattr(bank, "write", lambda _p: wrote.append(True))
    assert regen_goldens.main(["--suite", "conformance", "--write", "--reason", "r"]) == 0
    assert wrote == [True]


def test_builder_code_change_without_a_bump_is_still_refused(
    one_tape_changed: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(bank, "builder_fingerprint", lambda: "0" * 64)
    assert bank.build("reason").unbumped
    monkeypatch.setattr(bank, "write", lambda _p: pytest.fail("must not write"))
    assert regen_goldens.main(["--suite", "conformance", "--write", "--reason", "r"]) == 2


def test_spec_hash_change_without_a_bump_is_still_refused(
    one_tape_changed: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = bank.spec_hashes()
    monkeypatch.setattr(bank, "spec_hashes", lambda: {**real, "range:20": "f" * 64})
    assert bank.build("reason").unbumped


def test_committed_manifest_records_the_fingerprint_it_was_built_with() -> None:
    rec = bank._recorded()
    assert rec["builder_code_sha256"] == bank.builder_fingerprint()
    assert rec["spec_hashes"] == bank.spec_hashes()
