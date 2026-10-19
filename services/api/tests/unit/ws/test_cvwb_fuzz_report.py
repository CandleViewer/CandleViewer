"""A failing fuzz case reports its target and a digest, never its input or its seed (#415, E17-X02).

The repository is public, so the nightly fuzz job must not print a failing input. This runs the
real fuzz tests in a subprocess, under CI=true and the settings the nightly uses, against decoders
and parsers that break their contract on every input of 24 bytes or more (a parser's input as its
JSON text), and carry the whole input in the text or the value of the breakage. Everything the run
printed is then read: no form of the final failing input may be in it (raw, repr, hex, base64, a
window of any of them; for a parser also its repr and its long strings), nor the seed, nor
Hypothesis' blob, failing-case report or explanation, nor a frame of the planted code; the digest
must be; and the local file holds the seed and the input. When that file cannot be written, the
failure says only so."""

from __future__ import annotations

import ast
import base64
import hashlib
import json
import os
import re
import subprocess
import sys
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
    "test_is_topic_name_returns_a_bool_true_only_for_a_short_string": "deep",
    "test_parse_replay_session_id_returns_none_or_a_canonical_uuid": "raise",
    "test_json_client_frames_decode_to_a_refusal_or_a_bounded_value": "check",
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

import candleviewer.ws.binary as binary
import candleviewer.ws.codec as codec
import candleviewer.ws.gateway as gateway
import candleviewer.ws.topics as topics
from tests.unit.ws._fuzz import encode
from tests.unit.ws._msgpack_bounds import peak_bound

BREAKS = @BREAKS@
SEEN = {}
QUOTE = lambda self: iter([int(f"x{self[0]}")])
BOOM = type("Boom", (list,), {"__len__": lambda self: int(f"x{self[0]}"), "__iter__": QUOTE})


def _break(data):
    name = os.environ["PYTEST_CURRENT_TEST"].split("::")[-1].split(" ")[0]
    SEEN[name] = data.hex()
    if BREAKS[name] == "raise":
        raise ValueError(f"{data!r} {data.hex()} {base64.b64encode(data).decode()}")
    if BREAKS[name] == "peak":
        bytes(peak_bound() + (1 << 20))  # past the cap, then freed: the peak stays
        return None
    if BREAKS[name] == "check":  # walking it in the bound check raises, quoting the input
        return BOOM([data.hex()])
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


def _parse(real, value, *args):
    data = encode(value)  # the input as the parser suite's digest takes it
    return real(*args) if len(data) < 24 else _break(data)


binary.decode = decode
codec.decode_client_frame = decode_client_frame
real = {f: getattr(topics, f) for f in ("parse_topic", "validate_options", "is_topic_name")}
real |= {"session": topics.parse_replay_session_id, "frame": gateway._Connection.decode}
topics.parse_topic = lambda ch: _parse(real["parse_topic"], ch, ch)
topics.validate_options = lambda f, o: _parse(real["validate_options"], [f.family, o], f, o)
topics.is_topic_name = lambda ch: _parse(real["is_topic_name"], ch, ch)
topics.parse_replay_session_id = lambda raw: _parse(real["session"], raw, raw)
gateway._Connection.decode = lambda conn, msg, cap: _parse(
    real["frame"], [conn.user_id is not None, msg["text"]], conn, msg, cap
)


def pytest_sessionfinish():
    with open(os.environ["PLANTED_LOG"], "w", encoding="utf-8") as log:
        json.dump(SEEN, log)
"""


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


@pytest.mark.parametrize("saved", [True, False], ids=["saved", "unsaved"])
@pytest.mark.parametrize(
    "show", [(), ("-l",), ("--tb=native",)], ids=["default", "locals", "native"]
)
def test_a_failing_input_reaches_no_report(
    tmp_path: Path, show: tuple[str, ...], saved: bool
) -> None:
    plugin = PLANTED.replace("@BREAKS@", repr(BREAKS))
    (tmp_path / "planted.py").write_text(plugin, encoding="utf-8")
    (tmp_path / "blocked").write_text("", encoding="utf-8")  # a file where a directory must go
    where = tmp_path / "out" if saved else tmp_path / "blocked" / "out"
    drop = ("PYTEST_", "PYTHON", "COV", "HYPOTHESIS")  # the lane's own settings, not the nightly's
    env = {k: v for k, v in os.environ.items() if not k.startswith(drop)}
    env |= {
        "CI": "true",
        "CV_FUZZ_EXAMPLES": "60",
        "CV_FUZZ_SECONDS": "0",
        "CV_FUZZ_SEED": str(SEED),
        "CV_FUZZ_ARTIFACT_DIR": str(where),
        "PLANTED_LOG": str(tmp_path / "seen.json"),
        "PYTHONPATH": os.pathsep.join([str(tmp_path), str(API)]),
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
    assert done.returncode == 1, out.decode(errors="replace")
    seen = json.loads((tmp_path / "seen.json").read_text(encoding="utf-8"))
    assert set(seen) == set(BREAKS)  # each test failed, on a planted input
    assert out.count(b"FAILED ") == len(BREAKS)
    assert str(SEED).encode() not in out  # nor the seed (it stays in the failure file)
    for marker in (b"reproduce_failure", b"Failing test case", b"Explanation", b"planted.py"):
        assert marker not in out
    for name, hexed in seen.items():
        data = bytes.fromhex(hexed)
        target = next((p for p in PARSERS if p in name), "msgpack" if "msgpack" in name else "cvwb")
        digest = hashlib.sha256(f"{SEED}:".encode() + data).hexdigest()
        # the failure line is a reason, the target and the digest, and (if the file could not be
        # written) the class of the error that stopped it: nothing else
        tail = b"" if saved else rb" \(not saved: \w+\)"
        line = rb"AssertionError: [\w -]+: %b sha256=%b%b\r?\n"
        assert re.search(line % (target.encode(), digest.encode(), tail), out)
        texts = [data]
        if target in PARSERS:  # a JSON value: its repr too, and each string of 24 or more in it
            value = json.loads(data)
            items = value if isinstance(value, list) else [value]
            texts.append(repr(value).encode())
            texts += [s.encode() for s in items if isinstance(s, str) and len(s) >= 24]
        for text in texts:
            for window in (text, text[:12], text[-12:]):
                assert not [form for form in _forms(window) if form in out], name
        if saved:
            kept = json.loads((tmp_path / "out" / f"{target}-{digest}.json").read_text("utf-8"))
            b64 = base64.b64encode(data).decode()
            assert kept == {"seed": str(SEED), "target": target, "input": b64}


def test_every_fuzz_test_takes_only_the_redacted_input() -> None:
    """A test that took the generated arguments instead would print them in its traceback. The
    parser suite's tests take none: `drive` hands their checks one redacted input."""
    tests = [
        node
        for suite in (SUITE, PARSER_SUITE)
        for node in ast.parse(suite.read_text(encoding="utf-8")).body
        if isinstance(node, ast.FunctionDef)
        and any(ast.unparse(d) == "pytest.mark.fuzz" for d in node.decorator_list)
    ]
    assert {t.name for t in tests} == set(BREAKS)
    for t in tests:
        args = [] if any(p in t.name for p in PARSERS) else ["case"]
        assert [a.arg for a in t.args.args] == args, t.name
