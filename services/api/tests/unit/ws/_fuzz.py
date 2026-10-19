"""What the nightly WS fuzz suites share (#415, E17-X02): `test_cvwb_fuzz.py` (the CVWB and
msgpack decoders) and `test_ws_parser_fuzz.py` (the topic and option parsers, the JSON frame path).

The repository is public, so a failure names only its target and a sha256 digest of (seed, input):
a test takes one redacted `Input`, Hypothesis reports nothing (no failing-case report, blob or
explanation), and the pair is written to ``CV_FUZZ_ARTIFACT_DIR``, which CI uploads only encrypted
(fuzz-nightly.yml). ``CV_FUZZ_SEED`` seeds a run and ``CV_FUZZ_EXAMPLES`` sizes it (default 200).
`drive` runs a target once; with ``CV_FUZZ_SECONDS`` set, it starts runs until that many seconds
have passed, each from the next seed after ``CV_FUZZ_SEED`` (a failure replays from its input).
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import time
from collections.abc import Callable
from itertools import count
from pathlib import Path
from typing import Final

from hypothesis import HealthCheck, Phase, Verbosity, given, seed, settings
from hypothesis import strategies as st

EXAMPLES: Final[int] = int(os.environ.get("CV_FUZZ_EXAMPLES", "200"))
SEED: Final[int] = int(os.environ.get("CV_FUZZ_SEED", "12648430"))
#: How long `drive` keeps starting runs of one target (the nightly sets it); 0 starts one.
SECONDS: Final[float] = float(os.environ.get("CV_FUZZ_SECONDS", "0"))


def digest(data: bytes) -> str:
    """How a failure names its input without printing it: sha256 over the seed and the input."""
    return hashlib.sha256(f"{SEED}:".encode() + data).hexdigest()


class Input:
    """One fuzz input, built on demand. Its `repr` is its target and digest alone, so a traceback
    that prints the test's arguments shows no more than a failure message does."""

    __slots__ = ("_build", "target")

    def __init__(self, target: str, build: Callable[[], bytes]) -> None:
        self.target = target
        self._build = build

    @property
    def data(self) -> bytes:
        return self._build()

    def __repr__(self) -> str:
        return f"{self.target} sha256={digest(self.data)}"


def encode(value: object) -> bytes:
    """A parser's input as the bytes its digest and failure file hold: its JSON text, which
    `json.loads` reads back as the same value (NaN and the infinities included)."""
    return json.dumps(value).encode()


def write_record(case: Input, path: Path) -> str:
    """Writes {seed, target, input} to `path`, the seed as a decimal string (a reader that parses
    numbers as doubles would round a 64-bit one). Returns "" when it did, else the class of the
    error that stopped it: the error is dropped here, with the frames that held the input."""
    b64 = base64.b64encode(case.data).decode()
    record = {"seed": str(SEED), "target": case.target, "input": b64}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record), encoding="utf-8")
    except OSError as exc:
        return type(exc).__name__
    return ""


def save_failure(case: Input) -> str:
    """Writes the failure's file under CV_FUZZ_ARTIFACT_DIR; returns the only text a failure may
    carry: the target and the digest, and the class of the error if the file was not written."""
    name = digest(case.data)
    label = f"{case.target} sha256={name}"
    if out := os.environ.get("CV_FUZZ_ARTIFACT_DIR"):
        if failed := write_record(case, Path(out) / f"{case.target}-{name}.json"):
            label += f" (not saved: {failed})"
    return label


# print_blob: the blob encodes the input. verbosity: the failing-case report names the generated
# arguments. phases: the explanation names the code only failing inputs reach.
FUZZ_SETTINGS = settings(
    max_examples=EXAMPLES,
    deadline=None,
    suppress_health_check=list(HealthCheck),
    database=None,
    print_blob=False,
    verbosity=Verbosity.quiet,
    phases=[p for p in Phase if p is not Phase.explain],
)


def drive(cases: st.SearchStrategy[Input], check: Callable[[Input], None]) -> None:
    """Runs `check` on `cases` under `FUZZ_SETTINGS`, from `SEED`, then from each next seed while
    `SECONDS` have not passed. The first failure ends it, raised as `check` raised it."""
    deadline = time.monotonic() + SECONDS
    for n in count():
        seed(SEED + n)(FUZZ_SETTINGS(given(cases)(check)))()
        if time.monotonic() >= deadline:
            return
