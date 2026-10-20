"""A failing fuzz case reports its target and a digest, never its input or its seed (#415, E17-X02).

The repository is public, so the nightly fuzz job must not print a failing input. This runs the
real fuzz tests in child runs, under CI=true and the settings the nightly uses (20 examples, the
shrink phase included), against decoders and parsers that break their contract on every input of
24 bytes or more (a parser's input as its JSON text), and carry the whole input in the text or the
value of the breakage. Everything a child printed is then read: no form of the final failing input
may be in it (raw, repr, hex, base64, a window of any of them; for a parser also its repr and its
long strings), nor the seed, nor Hypothesis' blob, failing-case report or explanation, nor a frame
of the planted code; the digest must be; and the local file holds the seed and the input. When
that file cannot be written, the failure says only so.

The four children start together: the default traceback, locals (`-l`) and `--tb=native`, each
with a writable artifact directory; and the default with one that is not, in which every target
breaks as a call over `CALL_SECONDS` on a fake clock (never a sleep). Every target must also have
run through `_fuzz.drive`, which `CV_FUZZ_SECONDS` governs: a run seeds Hypothesis, once, first."""

from __future__ import annotations

import ast
import base64
import hashlib
import json
import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import pytest

API = Path(__file__).resolve().parents[3]
SUITE = Path(__file__).with_name("test_cvwb_fuzz.py")
PARSER_SUITE = Path(__file__).with_name("test_ws_parser_fuzz.py")
SEED = 731904826517
#: Test name -> how its decoder or parser breaks its contract: an untyped error that quotes the
#: input, a peak past the cap, a value nested past the depth cap that holds the input, or one
#: whose bound check itself raises, quoting the input.
BREAKS = {
    "test_decode_mutated_corpus_raises_only_the_typed_error": "raise",
    "test_msgpack_client_decode_mutated_corpus_raises_only_the_typed_error": "peak",
    "test_msgpack_client_decode_structured_frames_stay_bounded": "deep",
    "test_msgpack_client_decode_open_levels_stay_bounded": "check",
    "test_parse_topic_returns_a_typed_refusal_or_a_bounded_parse": "raise",
    "test_validate_options_returns_a_typed_refusal_or_bounded_options_for_every_family": "deep",
    "test_is_topic_name_returns_a_bool_true_exactly_for_the_topic_shape": "deep",
    "test_parse_replay_session_id_returns_none_or_a_canonical_uuid": "raise",
    "test_json_client_frames_decode_to_a_refusal_or_a_bounded_value": "check",
}
#: Child name -> (traceback options, whether the artifact directory is writable, test -> break).
CHILDREN: dict[str, tuple[tuple[str, ...], bool, dict[str, str]]] = {
    "default-saved": ((), True, BREAKS),
    "locals-saved": (("-l",), True, BREAKS),
    "native-saved": (("--tb=native",), True, BREAKS),
    "default-unsaved-slow": ((), False, dict.fromkeys(BREAKS, "slow")),
}
#: The parser suite's targets, each named in its test's name (the decoder suite's: msgpack, cvwb).
PARSERS = (
    "parse_topic",
    "validate_options",
    "is_topic_name",
    "replay_session_id",
    "json_client_frame",
)
PLANTED = """\
import base64
import json
import os
import time
from types import SimpleNamespace

import candleviewer.ws.binary as binary
import candleviewer.ws.codec as codec
import candleviewer.ws.gateway as gateway
import candleviewer.ws.topics as topics
import tests.unit.ws._fuzz as fuzz
from tests.unit.ws._fuzz import encode
from tests.unit.ws._msgpack_bounds import peak_bound

BREAKS = @BREAKS@
SEEN = {}
DRIVEN = []
NOW = [0.0]  # the clock that times a call: it moves only when a call breaks as `slow`
fuzz.time = SimpleNamespace(monotonic=time.monotonic, perf_counter=lambda: NOW[0])
QUOTE = lambda self: iter([int(f"x{self[0]}")])
BOOM = type("Boom", (list,), {"__len__": lambda self: int(f"x{self[0]}"), "__iter__": QUOTE})
real_seed = fuzz.seed


def seed(value):  # `drive` seeds each run first, and this frame is gone before a check fails
    DRIVEN.append(os.environ["PYTEST_CURRENT_TEST"].split("::")[-1].split(" ")[0])
    return real_seed(value)


fuzz.seed = seed


def _break(data, valid=lambda: False):
    name = os.environ["PYTEST_CURRENT_TEST"].split("::")[-1].split(" ")[0]
    SEEN[name] = data.hex()
    if BREAKS[name] == "raise":
        raise ValueError(f"{data!r} {data.hex()} {base64.b64encode(data).decode()}")
    if BREAKS[name] == "peak":
        bytes(peak_bound() + (1 << 20))  # past the cap, then freed: the peak stays
        return None
    if BREAKS[name] == "check":  # walking it in the bound check raises, quoting the input
        return BOOM([data.hex()])
    if BREAKS[name] == "slow":  # what its target accepts, after 10 s of the fake clock
        NOW[0] += 10.0
        return valid()
    nested = [data.hex()]
    for _ in range(codec.MAX_MSGPACK_DEPTH + 1):
        nested = [nested]
    return nested


def decode(data):
    if len(data) < 24:
        raise binary.FrameMalformedError("short")
    return _break(data)


def decode_client_frame(data):
    if len(data) < 24:
        raise codec.MsgpackFrameError("short")
    return _break(data)


def _parse(real, value, *args, valid):
    data = encode(value)  # the input as the parser suite's digest takes it
    return real(*args) if len(data) < 24 else _break(data, valid)


def _refuse(code, field=None):
    def refusal():
        raise topics.TopicError(code, "planted", field)

    return refusal


binary.decode = decode
codec.decode_client_frame = decode_client_frame
real = {f: getattr(topics, f) for f in ("parse_topic", "validate_options", "is_topic_name")}
real |= {"session": topics.parse_replay_session_id, "frame": gateway._Connection.decode}
topics.parse_topic = lambda ch: _parse(real["parse_topic"], ch, ch, valid=_refuse("unknown_topic"))
topics.validate_options = lambda f, o: _parse(
    real["validate_options"], [f.family, o], f, o, valid=_refuse("invalid_options", "opts")
)
topics.is_topic_name = lambda ch: _parse(
    real["is_topic_name"], ch, ch, valid=lambda: real["is_topic_name"](ch)
)
topics.parse_replay_session_id = lambda raw: _parse(real["session"], raw, raw, valid=lambda: None)
gateway._Connection.decode = lambda conn, msg, cap: _parse(
    real["frame"],
    [conn.user_id is not None, msg["text"]],
    conn,
    msg,
    cap,
    valid=lambda: gateway._OVERSIZE,
)


def pytest_sessionfinish():
    with open(os.environ["PLANTED_LOG"], "w", encoding="utf-8") as log:
        json.dump({"seen": SEEN, "driven": DRIVEN}, log)
"""


@dataclass(frozen=True)
class Child:
    """What one child run left: its output, exit code, the planted log and its directory."""

    out: bytes
    returncode: int
    seen: dict[str, str]
    driven: list[str]
    root: Path


def _forms(data: bytes) -> list[bytes]:
    """The ways a report could print `data`, as bytes of the report."""
    b64 = base64.b64encode(data)
    return [
        data,
        repr(data).encode(),
        repr(data)[2:-1].encode(),
        data.hex().encode(),
        data.hex().upper().encode(),
        b64,
        b64.rstrip(b"="),
        base64.urlsafe_b64encode(data),
    ]


def _run_child(root: Path, show: tuple[str, ...], saved: bool, breaks: dict[str, str]) -> Child:
    """Both fuzz suites in a child pytest run, against the planted decoders and parsers."""
    (root / "planted.py").write_text(PLANTED.replace("@BREAKS@", repr(breaks)), encoding="utf-8")
    (root / "blocked").write_text("", encoding="utf-8")  # a file where a directory must go
    where = root / "out" if saved else root / "blocked" / "out"
    drop = ("PYTEST_", "PYTHON", "COV", "HYPOTHESIS")  # the lane's own settings, not the nightly's
    env = {k: v for k, v in os.environ.items() if not k.startswith(drop)}
    env |= {
        "CI": "true",
        "CV_FUZZ_EXAMPLES": "20",
        "CV_FUZZ_SECONDS": "0",
        "CV_FUZZ_SEED": str(SEED),
        "CV_FUZZ_ARTIFACT_DIR": str(where),
        "PLANTED_LOG": str(root / "seen.json"),
        "PYTHONPATH": os.pathsep.join([str(root), str(API)]),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    flags = ["-p", "planted", "-p", "no:cacheprovider", "-o", "addopts=", "-m", "fuzz", *show]
    done = subprocess.run(  # noqa: S603 -- fixed argv: this interpreter, the suites' paths (#415)
        [sys.executable, "-m", "pytest", *flags, str(SUITE), str(PARSER_SUITE)],
        cwd=API,
        env=env,
        capture_output=True,
        timeout=300,
        check=False,
    )
    out = done.stdout + done.stderr
    if not (root / "seen.json").exists():  # the child never reached its end: say why
        raise AssertionError(out.decode(errors="replace"))
    log = json.loads((root / "seen.json").read_text(encoding="utf-8"))
    return Child(out, done.returncode, log["seen"], log["driven"], root)


@pytest.fixture(scope="module")
def children(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Child]:
    """The children, run together: each is its interpreter's start-up and nine short runs."""
    with ThreadPoolExecutor(max_workers=len(CHILDREN)) as pool:
        started = {
            name: pool.submit(_run_child, tmp_path_factory.mktemp(name), *spec)
            for name, spec in CHILDREN.items()
        }
        return {name: run.result() for name, run in started.items()}


@pytest.mark.parametrize("name", list(CHILDREN))
def test_a_failing_input_reaches_no_report(children: dict[str, Child], name: str) -> None:
    _, saved, breaks = CHILDREN[name]
    child = children[name]
    out = child.out
    assert child.returncode == 1, out.decode(errors="replace")
    assert set(child.seen) == set(breaks)  # each test failed, on a planted input
    assert sorted(child.driven) == sorted(breaks)  # each ran through `drive`, once
    assert out.count(b"FAILED ") == len(breaks)
    assert str(SEED).encode() not in out  # nor the seed (it stays in the failure file)
    for marker in (b"reproduce_failure", b"Failing test case", b"Explanation", b"planted.py"):
        assert marker not in out
    for test, hexed in child.seen.items():
        data = bytes.fromhex(hexed)
        target = next((p for p in PARSERS if p in test), "msgpack" if "msgpack" in test else "cvwb")
        digest = hashlib.sha256(f"{SEED}:".encode() + data).hexdigest()
        # the failure line is a reason, the target and the digest, and (if the file could not be
        # written) the class of the error that stopped it: nothing else
        tail = b"" if saved else rb" \(not saved: \w+\)"
        why = rb"slow input" if breaks[test] == "slow" else rb"[\w -]+"
        line = rb"AssertionError: %b: %b sha256=%b%b\r?\n"
        assert re.search(line % (why, target.encode(), digest.encode(), tail), out)
        texts = [data]
        if target in PARSERS:  # a JSON value: its repr too, and each string of 24 or more in it
            value = json.loads(data)
            items = value if isinstance(value, list) else [value]
            texts.append(repr(value).encode())
            texts += [s.encode() for s in items if isinstance(s, str) and len(s) >= 24]
        for text in texts:
            for window in (text, text[:12], text[-12:]):
                assert not [form for form in _forms(window) if form in out], test
        if saved:
            kept = json.loads((child.root / "out" / f"{target}-{digest}.json").read_text("utf-8"))
            b64 = base64.b64encode(data).decode()
            assert kept == {"seed": str(SEED), "target": target, "input": b64}


#: What a fuzz target may be decorated with: its marker and C-9.3's quarantine marker, which the
#: nightly's `-m "fuzz and not flaky"` honours.
MARKS = ("pytest.mark.fuzz", "pytest.mark.flaky")


def _stray(node: ast.FunctionDef) -> list[str]:
    """The decorators of `node` that are none of `MARKS`: a `given`, `settings` or `seed` of its
    own would take the arguments and the seed that `drive` owns."""
    return [d for d in map(ast.unparse, node.decorator_list) if d not in MARKS]


def test_every_fuzz_test_takes_no_arguments() -> None:
    """A test that took the generated arguments instead would print them in its traceback. None
    does, and none has a `given` or `seed` of its own: `drive` hands each check one redacted
    input, and applies the seed and the time box. A quarantined target keeps its `MARKS`."""
    tests = [
        node
        for suite in (SUITE, PARSER_SUITE)
        for node in ast.parse(suite.read_text(encoding="utf-8")).body
        if isinstance(node, ast.FunctionDef)
        and any(ast.unparse(d) == "pytest.mark.fuzz" for d in node.decorator_list)
    ]
    assert {t.name for t in tests} == set(BREAKS)
    for t in tests:
        assert [a.arg for a in t.args.args] == [], t.name
        assert _stray(t) == [], t.name


@pytest.mark.parametrize(
    ("decorators", "stray"),
    [
        (("pytest.mark.fuzz",), []),
        (("pytest.mark.fuzz", "pytest.mark.flaky"), []),  # C-9.3: a target that turns flaky
        (("pytest.mark.flaky", "pytest.mark.fuzz"), []),
        (("pytest.mark.fuzz", "given(st.integers())"), ["given(st.integers())"]),
        (("pytest.mark.fuzz", "settings(max_examples=1)"), ["settings(max_examples=1)"]),
        (("pytest.mark.fuzz", "seed(1)"), ["seed(1)"]),
        (("pytest.mark.fuzz", "pytest.mark.skip"), ["pytest.mark.skip"]),
        (("pytest.mark.fuzz", "pytest.mark.flaky", "seed(1)"), ["seed(1)"]),
    ],
)
def test_a_fuzz_target_may_carry_the_quarantine_marker_and_no_other_decorator(
    decorators: tuple[str, ...], stray: list[str]
) -> None:
    source = "".join(f"@{d}\n" for d in decorators) + "def test_x() -> None: ...\n"
    (node,) = ast.parse(source).body
    assert isinstance(node, ast.FunctionDef)
    assert _stray(node) == stray
