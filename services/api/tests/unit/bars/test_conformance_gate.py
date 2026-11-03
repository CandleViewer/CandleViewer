"""E12-Q02 golden gate: a tape-only regeneration is exempt from the `BUILD_VERSIONS` bump (#2200).

The exemption holds only while the builder sources and every live spec hash equal the ones the
manifest recorded; any builder or spec change still needs the bump. Nothing here writes the bank.
"""

from __future__ import annotations

import dataclasses
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

from bench.bar_conformance import bank, runner
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


def test_golden_change_on_an_unchanged_tape_still_needs_the_bump(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The exemption is per tape: builder behaviour moved by a file outside the fingerprint (here
    a limit patched at runtime, so the fingerprint is unchanged) changes goldens of tapes whose
    bytes did not change, and those kinds are refused without the bump."""
    from candleviewer.bars import activity_builders, renko_builder

    monkeypatch.setattr(tapes, "TAPES", {NAME: tapes.TAPES[NAME]})
    for mod in (activity_builders, renko_builder):  # both bind the name at import time
        monkeypatch.setattr(mod, "MAX_BRICKS_PER_TRADE", 1)
    assert not bank.builder_code_changed(bank._recorded())
    p = bank.build("reason")
    assert not any(f.endswith(".jsonl.gz") for f in p.changed)
    assert p.changed and p.unbumped


def _temp_closure_copy(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, mod: str, edit: Callable[[bytes], bytes]
) -> None:
    real = bank._module_file
    src = real(mod)
    assert src is not None
    copy = tmp_path / src.name
    copy.write_bytes(edit(src.read_bytes()))
    monkeypatch.setattr(bank, "_module_file", lambda m: copy if m == mod else real(m))


def test_editing_limits_py_changes_the_fingerprint(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _temp_closure_copy(
        monkeypatch, tmp_path, "candleviewer.bars.limits", lambda b: b + b"MAX_BRICKS = 1\n"
    )
    assert bank.builder_code_changed(bank._recorded())


def test_fingerprint_ignores_crlf_and_bom(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _temp_closure_copy(
        monkeypatch,
        tmp_path,
        "candleviewer.bars.limits",
        lambda b: b"\xef\xbb\xbf" + b.replace(b"\n", b"\r\n"),
    )
    assert not bank.builder_code_changed(bank._recorded())


def test_missing_fingerprint_or_spec_hashes_fail_closed() -> None:
    rec = bank._recorded()
    assert bank.builder_code_changed({k: v for k, v in rec.items() if k != "builder_code_sha256"})
    assert bank.builder_code_changed({k: v for k, v in rec.items() if k != "spec_hashes"})


def test_hashed_set_covers_every_module_the_runner_loads() -> None:
    """The closure is derived from imports; a runtime import must never fall outside it."""
    code = (
        "import sys, bench.bar_conformance.runner;"
        "print('\\n'.join(sorted(m for m in sys.modules if m.startswith('candleviewer'))))"
    )
    root = Path(str(runner.__file__)).parents[2]
    out = subprocess.run(  # noqa: S603 -- fixed argv, no shell, no network
        [sys.executable, "-I", "-c", code],
        cwd=root,
        env={**os.environ, "PYTHONPATH": str(root)},
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    loaded = {m for m in out if bank._module_file(m) is not None}
    assert loaded - set(bank.builder_closure()) <= bank._EXCLUDED
    assert "candleviewer.bars.limits" in bank.builder_closure()
    assert "candleviewer.bars.rows" not in bank.builder_closure()
