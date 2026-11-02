"""E49-Q01 (#1335): tools/ga/scrub_artifacts.py (credentials out of traces, HARs and logs before
upload) and tools/ga/report.py (per-area report, seeded-failure detection, flake rates, budget,
metrics, determinism). Fake values are low-entropy and built at run time."""

from __future__ import annotations

import json
import sys
import time
import zipfile
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.ga import report, scrub_artifacts, specs

MASK = scrub_artifacts.MASK
FAKE = "-".join(["fake", "seed", "value"])

# --- scrub_artifacts ------------------------------------------------------------------------


def test_self_test_removes_every_seeded_form() -> None:
    assert scrub_artifacts.self_test() == []
    assert scrub_artifacts.main(["--self-test"]) == 0


@pytest.mark.parametrize(
    "header",
    [
        "Authorization",
        "proxy-authorization",
        "Cookie",
        "set-cookie",
        "X-Demo-Api-Key",
        "x-sign",
        "x-foo-signature",
        "X-CSRF-Token",
    ],
)
def test_sensitive_header_records_are_redacted(header: str) -> None:
    text = json.dumps([{"name": header, "value": FAKE}, {"name": "accept", "value": "text/html"}])
    out = scrub_artifacts.scrub_text(text)
    assert FAKE not in out and MASK in out and "text/html" in out


def test_a_body_inside_a_json_string_is_redacted_at_its_depth() -> None:
    body = json.dumps({"username": "ann", "password": FAKE, "nested": {"api_key": FAKE}})
    text = json.dumps({"postData": body})
    out = scrub_artifacts.scrub_text(text)
    assert FAKE not in out and "ann" in out
    assert json.loads(json.loads(out)["postData"])["password"] == MASK


@pytest.mark.parametrize(
    "key", ["access_token", "refreshToken", "secret", "totp", "otp_code", "signature", "passphrase"]
)
def test_credential_named_members_are_redacted(key: str) -> None:
    out = scrub_artifacts.scrub_text(json.dumps({key: FAKE, "status": "ok"}))
    assert json.loads(out) == {key: MASK, "status": "ok"}


def test_recovery_code_arrays_raw_header_lines_and_schemes_are_redacted() -> None:
    text = (
        json.dumps({"recovery_codes": [FAKE, FAKE]})
        + f"\nAuthorization: Basic {FAKE}\n  cookie: sid={FAKE}\nsent Bearer {FAKE} on retry\n"
    )
    out = scrub_artifacts.scrub_text(text)
    assert FAKE not in out
    assert json.loads(out.splitlines()[0]) == {"recovery_codes": MASK}


def test_ordinary_text_is_unchanged_and_scrubbing_is_idempotent() -> None:
    text = json.dumps({"status": "ok", "code": "E1001", "title": "Forbidden", "tokens_used": 3})
    assert scrub_artifacts.scrub_text(text) == text
    once = scrub_artifacts.scrub_text(json.dumps({"password": FAKE}))
    assert scrub_artifacts.scrub_text(once) == once


def test_scrub_tree_rewrites_traces_and_text_files_and_leaves_media(tmp_path: Path) -> None:
    trace = tmp_path / "t" / "trace.zip"
    trace.parent.mkdir()
    png = b"\x89PNG\r\n\x1a\n" + FAKE.encode()
    with zipfile.ZipFile(trace, "w") as z:
        z.writestr("trace.network", json.dumps({"name": "cookie", "value": FAKE}))
        z.writestr("resources/abc.png", png)
        z.writestr("resources/0f0f", "plain body")
    (tmp_path / "t" / "error-context.md").write_text(f"Authorization: {FAKE}\n", encoding="utf-8")
    (tmp_path / "t" / "video.webm").write_bytes(FAKE.encode())
    counts = scrub_artifacts.scrub_tree(tmp_path)
    assert counts == {"files": 2, "changed": 2, "failed": 0}
    with zipfile.ZipFile(trace) as z:
        assert FAKE not in z.read("trace.network").decode()
        assert z.read("resources/abc.png") == png
        assert z.read("resources/0f0f") == b"plain body"
    assert FAKE not in (tmp_path / "t" / "error-context.md").read_text(encoding="utf-8")
    assert (tmp_path / "t" / "video.webm").read_bytes() == FAKE.encode()


def test_cli_scrubs_directories_and_tolerates_a_missing_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "a.har").write_text(json.dumps({"name": "Cookie", "value": FAKE}), encoding="utf-8")
    assert scrub_artifacts.main([str(tmp_path), str(tmp_path / "missing")]) == 0
    assert FAKE not in (tmp_path / "a.har").read_text(encoding="utf-8")
    assert "nothing to scrub" in capsys.readouterr().out
    assert scrub_artifacts.main([]) == 2


def _scrubbed(text: str) -> str:
    out = scrub_artifacts.scrub_text(text)
    assert scrub_artifacts.scrub_text(out) == out  # idempotent
    return out


NUMERIC = 271828


@pytest.mark.parametrize(
    "text",
    [
        # Playwright's HAR/trace cookie arrays: any record inside `cookies`, whatever its name.
        json.dumps({"request": {"cookies": [{"name": "theme", "value": FAKE}]}}),
        json.dumps({"response": {"cookies": [{"name": "a]b", "value": FAKE}, {"value": FAKE}]}}),
        # A record whose name is a session cookie name, outside a cookies array.
        json.dumps([{"name": "cv_session", "value": FAKE}]),
        # Header maps in object form (route and fulfil logs, some trace events).
        json.dumps({"headers": {"authorization": FAKE, "Cookie": f"a={FAKE}"}}),
        # Credentials in URLs, form bodies and otpauth URIs; invite tokens in paths.
        json.dumps({"url": f"http://127.0.0.1:4173/api?page=2&token={FAKE}&x=1"}),
        json.dumps({"url": f"http://127.0.0.1:4173/api?sig={FAKE}"}),
        json.dumps({"postData": {"text": f"username=ann&password={FAKE}"}}),
        json.dumps({"otpauth_uri": f"otpauth://totp/CV:ann?secret={FAKE}&issuer=CV"}),
        f"console: scan otpauth://totp/CV:ann?secret={FAKE}&period=30",
        json.dumps({"url": f"http://127.0.0.1:4173/invite/{FAKE}"}),
        # Numeric credentials.
        json.dumps({"otp": NUMERIC, "status": "ok"}),
        json.dumps({"code": str(NUMERIC) + "0", "status": "ok"}),
        # Typed values of a trace's typing actions.
        json.dumps({"method": "fill", "params": {"selector": "#pw", "value": FAKE}}),
        json.dumps({"apiName": "keyboard.type", "params": {"text": FAKE}})
        + "\n"
        + json.dumps({"method": "pressSequentially", "params": {"text": FAKE}}),
    ],
)
def test_r1_forms_are_redacted(text: str) -> None:
    out = _scrubbed(text)
    assert FAKE not in out and str(NUMERIC) not in out
    assert "otpauth://totp" not in out


def test_r1_forms_keep_what_is_not_a_credential() -> None:
    text = json.dumps(
        {
            "url": "http://127.0.0.1:4173/api?page=2&side=buy",
            "headers": {"accept": "text/html"},
            "cookies_enabled": True,
            "tokens_used": 3,
            "code": "E1001",
            "method": "click",
            "params": {"selector": "#ok", "value": "kept"},
            "route": "/invite/:inviteToken",
        }
    )
    assert scrub_artifacts.scrub_text(text) == text


def test_a_non_utf8_text_file_is_still_scrubbed(tmp_path: Path) -> None:
    log = tmp_path / "console.log"
    log.write_bytes(b"\xff\xfe stray bytes\nAuthorization: Bearer " + FAKE.encode() + b"\n")
    assert scrub_artifacts.scrub_tree(tmp_path)["changed"] == 1
    data = log.read_bytes()
    assert FAKE.encode() not in data and data.startswith(b"\xff\xfe")


def test_a_truncated_trace_is_deleted_the_walk_goes_on_and_the_cli_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    good = tmp_path / "a" / "trace.zip"
    good.parent.mkdir()
    with zipfile.ZipFile(good, "w") as z:
        z.writestr("trace.network", json.dumps({"name": "cookie", "value": FAKE}))
    whole = good.read_bytes()
    (tmp_path / "a" / "broken.zip").write_bytes(whole[: len(whole) // 2])  # a killed worker's
    later = tmp_path / "b" / "network.har"  # sorts after the broken archive
    later.parent.mkdir()
    later.write_text(json.dumps({"cookies": [{"name": "sid", "value": FAKE}]}), encoding="utf-8")
    assert scrub_artifacts.scrub_tree(tmp_path) == {"files": 3, "changed": 2, "failed": 1}
    assert not (tmp_path / "a" / "broken.zip").exists()
    assert FAKE not in later.read_text(encoding="utf-8")
    with zipfile.ZipFile(good) as z:
        assert FAKE not in z.read("trace.network").decode()
    (tmp_path / "c.zip").write_bytes(b"PK\x03\x04 not an archive")
    assert scrub_artifacts.main([str(tmp_path)]) == 1
    assert "fail-closed" in capsys.readouterr().out
    assert not (tmp_path / "c.zip").exists()


# Recorded shapes (Playwright 1.64.1 trace + error-context, hand-minimised; fake values only).
def _event(**fields: Any) -> str:
    return json.dumps({"callId": "c@1", **fields}, separators=(",", ":"))


@pytest.mark.parametrize("method", ["keyboardType", "keyboardInsertText"])
def test_keyboard_typing_actions_are_redacted(method: str) -> None:
    fields = {"type": "before", "class": "Page", "method": method, "params": {"text": FAKE}}
    text = _event(**fields)
    out = _scrubbed(text)
    assert FAKE not in out and json.loads(out)["params"]["text"] == MASK


@pytest.mark.parametrize("action", ["fill", "type", "pressSequentially", "insertText"])
def test_typing_log_messages_are_redacted_raw_and_escaped(action: str) -> None:
    escaped = _event(type="log", time=2.0, message=f'  {action}("{FAKE}")')
    raw = f'Call log:\n  - locator.{action}("{FAKE}")\n  - {action}("{NUMERIC}")\n'
    for text in (escaped, raw):
        out = _scrubbed(text)
        assert (
            FAKE not in out and str(NUMERIC) not in out and f'{action}("' in out.replace("\\", "")
        )
    assert json.loads(_scrubbed(escaped))["message"] == f'  {action}("{MASK}")'


def test_input_values_in_frame_snapshots_are_all_redacted() -> None:
    inputs = [
        ["INPUT", {"__playwright_value_": FAKE, "type": "password", "name": "pw"}],
        ["INPUT", {"__playwright_value_": str(NUMERIC), "name": "code", "inputmode": "numeric"}],
        ["INPUT", {"__playwright_value_": "ann@example.test", "name": "email"}],
    ]
    snap = {"callId": "c@1", "phase": "after", "html": ["HTML", {}, ["BODY", {}, *inputs]]}
    out = _scrubbed(json.dumps({"type": "frame-snapshot", "snapshot": snap}, separators=(",", ":")))
    assert FAKE not in out and str(NUMERIC) not in out and "ann@example.test" not in out
    assert out.count(f'"__playwright_value_":"{MASK}"') == 3 and '"type":"password"' in out


# Recorded node shapes (Playwright 1.64.1 frame-snapshot of a page whose input handler sets the
# `value` attribute, as React 18 does for a controlled field; values replaced by fakes).
FIELD_NODES: list[Any] = [
    [
        "INPUT",
        {
            "__playwright_value_": FAKE,
            "__playwright_target__": "",
            "type": "password",
            "name": "pw",
            "value": FAKE,
        },
    ],
    [
        "INPUT",
        {
            "__playwright_value_": str(NUMERIC),
            "name": "code",
            "inputmode": "numeric",
            "value": str(NUMERIC),
        },
    ],
    ["INPUT", {"name": "email", "value": "ann@example.test"}],
    ["TEXTAREA", {"__playwright_value_": FAKE, "name": "note"}, FAKE],
    ["SELECT", {"name": "pick"}, ["OPTION", {"__playwright_selected_": "true", "value": "b"}, "b"]],
]


def test_input_value_attributes_in_frame_snapshots_are_all_redacted_raw_and_escaped() -> None:
    snap = {"callId": "c@1", "html": ["HTML", {}, ["BODY", {}, ["FORM", {}, *FIELD_NODES]]]}
    raw = json.dumps({"type": "frame-snapshot", "snapshot": snap}, separators=(",", ":"))
    for text in (raw, json.dumps({"text": raw}), json.dumps({"text": json.dumps({"t": raw})})):
        out = _scrubbed(text)
        assert FAKE not in out and str(NUMERIC) not in out and "ann@example.test" not in out
    out = _scrubbed(raw)
    assert out.count(f'"value":"{MASK}"') == 3 and f'"name":"note"}},"{MASK}"]' in out
    # Option values are the page's own, not typed: they stay.
    assert '"value":"b"},"b"]' in out and '"type":"password"' in out
    assert json.loads(json.loads(_scrubbed(json.dumps({"text": raw})))["text"])


def test_page_html_input_values_and_textarea_bodies_are_redacted() -> None:
    html = (
        f'<form><input type="password" value="{FAKE}" name=pw><input value={NUMERIC}>'
        f"<input name=e value='{FAKE}'><textarea name=n>{FAKE}</textarea>"
        '<select><option value="b">b</option></select></form>'
    )
    for text in (html, json.dumps({"text": html})):
        out = _scrubbed(text)
        assert FAKE not in out and str(NUMERIC) not in out and "option value=" in out
    assert json.loads(_scrubbed(json.dumps({"text": html})))["text"].count(MASK) == 4


@pytest.mark.parametrize("suffix", [".html", ".xml"])
def test_html_and_xml_files_and_trace_members_are_scrubbed(tmp_path: Path, suffix: str) -> None:
    body = f"<r><input value='{FAKE}'/><a href='?token={FAKE}'/></r>"
    (tmp_path / f"page{suffix}").write_text(body, encoding="utf-8")
    with zipfile.ZipFile(tmp_path / "trace.zip", "w") as z:
        z.writestr(f"resources/0a1b{suffix}", body)
    assert scrub_artifacts.scrub_tree(tmp_path) == {"files": 2, "changed": 2, "failed": 0}
    assert FAKE not in (tmp_path / f"page{suffix}").read_text(encoding="utf-8")
    with zipfile.ZipFile(tmp_path / "trace.zip") as z:
        assert FAKE not in z.read(f"resources/0a1b{suffix}").decode()


def test_url_userinfo_is_redacted_and_plain_hosts_stay() -> None:
    text = json.dumps(
        {"url": f"http://ann:{FAKE}@127.0.0.1:4173/", "log": f"wss://u:{NUMERIC}@h.test/ws"}
    )
    out = _scrubbed(text)
    assert FAKE not in out and str(NUMERIC) not in out
    assert json.loads(out)["url"] == f"http://{MASK}@127.0.0.1:4173/"
    keep = "http://127.0.0.1:4173/login and mailto:ann@example.test"
    assert _scrubbed(keep) == keep


def test_a_bracket_inside_a_quoted_html_value_does_not_end_the_input() -> None:
    out = _scrubbed(f'<input name=pw value="a>{FAKE}"><p>after</p>')
    assert FAKE not in out and "<p>after</p>" in out


def test_long_url_userinfo_passwords_are_redacted() -> None:
    long_pw = FAKE + "x" * 300
    out = _scrubbed(f"https://ann:{long_pw}@127.0.0.1:4173/")
    assert FAKE not in out and out == f"https://{MASK}@127.0.0.1:4173/"


MB = 1 << 20
#: The seven shapes added for the last three patterns run at 256 KB: their old cost there was
#: tens of seconds (55 s for `fill("`), so the signal stays loud, and the margin holds on a loaded host.
QMB = MB // 4


@pytest.mark.parametrize(
    "run",
    [
        "password" * (MB // 8),
        "\\" * MB,
        "\\" * MB + '"x',
        '"' + "api_key" * (MB // 7),
        "x-" + "token" * (MB // 5),
        '["INPUT",{' * (MB // 10),
        "<input " * (MB // 7),
        "https://" * (MB // 8),
        '"name":"' * (MB // 8),
        "\n" * QMB,
        " \n" * (QMB // 2),
        '"token":[' * (QMB // 9),
        'fill("' * (QMB // 6),
        ("fill(" + "\\" * 8 + '"') * (QMB // 14),
        '["INPUT",{"k":' * (QMB // 14),
        '["TEXTAREA",{"k":"\\"' * (QMB // 20),
    ],
    ids=[
        "words",
        "backslashes",
        "backslash-quote",
        "quoted-key",
        "header",
        "nodes",
        "html",
        "urls",
        "records",
        "blank-lines",
        "blank-space-lines",
        "key-arrays",
        "typing-logs",
        "deep-typing-logs",
        "bad-attribute-maps",
        "escaped-attribute-maps",
    ],
)
def test_a_large_token_run_scrubs_within_a_generous_wall_budget(run: str) -> None:
    # Unbounded key wrappers and quote depths made these quadratic (minutes per megabyte), and so
    # did a header match crossing blank lines and a fresh scan to the line's (or text's) end for
    # each unclosed `fill("` or credential-key `[`.
    start = time.perf_counter()
    scrub_artifacts.scrub_text(run)
    assert time.perf_counter() - start < 5.0


# Attribute maps a pair-by-pair walk can lose its place in: a key holding an escaped quote, a
# value ending in an escaped backslash (`"a\\"`), a key ending in one, a value that is not a
# string. Every `value` after such a pair, and a TEXTAREA's text child, must still be masked.
SEEDED_ATTRIBUTES: list[dict[str, Any]] = [
    {'data-x"y': "a", "value": FAKE},
    {"title": "a\\", "value": FAKE},
    {"a": "b", "data-k\\": "c", "value": FAKE},
    {"checked": True, "value": FAKE},
]


@pytest.mark.parametrize("attrs", SEEDED_ATTRIBUTES, ids=["quote", "value-bs", "key-bs", "bool"])
def test_a_value_after_an_escaped_or_unparsed_attribute_is_still_redacted(
    attrs: dict[str, Any],
) -> None:
    nodes = [["INPUT", attrs], ["TEXTAREA", attrs, FAKE], ["P", {"title": "kept"}, "after"]]
    raw = json.dumps({"snapshot": {"html": ["BODY", {}, *nodes]}}, separators=(",", ":"))
    for text in (raw, json.dumps({"text": raw}), json.dumps({"text": json.dumps({"t": raw})})):
        out = _scrubbed(text)
        assert FAKE not in out and '"kept"' in out.replace("\\", "")
        json.loads(out)
    assert _scrubbed(raw).endswith(f',"{MASK}"],["P",{{"title":"kept"}},"after"]]}}}}')


ARIA = (
    "- generic [ref=e2]:\n"
    "  - text: Password\n"
    f'  - textbox "Password" [ref=e4]: {FAKE}\n'
    f'  - textbox "Code: 6 digits" [ref=e6]: "{NUMERIC}"\n'
    f'  - textbox "Email" [active] [ref=e8]: ann@example.test{FAKE}\n'
    f"  - textbox [ref=e9]: {FAKE}\n"
    '  - textbox "Search" [ref=e10]\n'
    '  - button "Sign in" [ref=e11]'
)


def test_aria_snapshot_textbox_values_are_redacted_in_error_context() -> None:
    out = _scrubbed("# Page snapshot\n\n```yaml\n" + ARIA + "\n```\n")
    assert FAKE not in out and str(NUMERIC) not in out
    assert f'- textbox "Password" [ref=e4]: {MASK}' in out
    assert '- textbox "Search" [ref=e10]\n' in out and '- button "Sign in" [ref=e11]' in out


def test_aria_snapshot_textbox_values_are_redacted_inside_json() -> None:
    text = _event(type="after", endTime=3.0, result={"snapshot": ARIA})
    out = _scrubbed(text)
    assert FAKE not in out and str(NUMERIC) not in out
    snapshot = json.loads(out)["result"]["snapshot"]
    assert f'- textbox "Code: 6 digits" [ref=e6]: {MASK}' in snapshot
    assert snapshot.endswith('- button "Sign in" [ref=e11]')


def test_credentials_under_unquoted_keys_in_evaluated_source_are_redacted() -> None:
    src = f'() => fetch("/x", {{ body: JSON.stringify({{ password: "{FAKE}", otp: {NUMERIC} }}) }})'
    out = _scrubbed(_event(type="before", method="evaluateExpression", params={"expression": src}))
    assert FAKE not in out and str(NUMERIC) not in out and 'fetch(\\"/x\\"' in out


def test_dat_trace_resources_are_scrubbed_and_binary_dat_is_left(tmp_path: Path) -> None:
    trace = tmp_path / "trace.zip"
    binary = b"\x00\x01" + FAKE.encode()
    with zipfile.ZipFile(trace, "w") as z:
        z.writestr("resources/393f.dat", f"username=ann&password={FAKE}")
        z.writestr("resources/0000.dat", binary)
    assert scrub_artifacts.scrub_tree(tmp_path) == {"files": 1, "changed": 1, "failed": 0}
    with zipfile.ZipFile(trace) as z:
        assert z.read("resources/393f.dat").decode() == f"username=ann&password={MASK}"
        assert z.read("resources/0000.dat") == binary


# --- report ---------------------------------------------------------------------------------


def _spec(
    title: str, status: str, tags: list[str], seconds: float = 1.0, axe: int = 0
) -> dict[str, Any]:
    notes = [{"type": "ga-axe-p2", "description": "rule: help"}] * axe
    results = [{"status": "passed", "duration": seconds * 1000, "annotations": notes}]
    return {
        "title": title,
        "tags": tags,
        "tests": [{"status": status, "annotations": notes, "results": results}],
    }


def _results(
    tmp_path: Path, lane: str, shard: int, specs_by_file: dict[str, list[dict[str, Any]]]
) -> None:
    d = tmp_path / "results" / f"ga-results-{lane}-{shard}"
    d.mkdir(parents=True)
    suites = [{"title": f, "file": f, "specs": s, "suites": []} for f, s in specs_by_file.items()]
    (d / "results.json").write_text(json.dumps({"suites": suites, "stats": {}}), encoding="utf-8")


def _pack(area: str, status: str = "expected", extra: tuple[str, ...] = ()) -> dict[str, Any]:
    return _spec(f"{area} scenario @plan-X", status, ["ga-regression", f"ga-area-{area}", *extra])


def _night(tmp_path: Path, failing: str | None = None) -> list[report.TestResult]:
    _results(
        tmp_path,
        "web-chromium",
        1,
        {
            f"{a}.spec.ts": [_pack(a, "unexpected" if a == failing else "expected")]
            for a in specs.AREAS
        },
    )
    _results(tmp_path, "electron", 1, {"shell-smoke.spec.ts": [_pack("shell")]})
    return report.load_results(tmp_path / "results")


@pytest.mark.parametrize("area", specs.AREAS)
def test_a_seeded_failure_is_reported_in_its_own_area(tmp_path: Path, area: str) -> None:
    built = report.build(_night(tmp_path, failing=area), [], {"number": 9}, ROOT)
    assert built["failing_areas"] == [area]
    assert built["failure_artifacts"] == ["ga-failure-web-chromium-1"]
    assert report.is_red(built)
    md = report.markdown(built)
    assert f"Failing areas: {area}." in md and "`ga-failure-web-chromium-1`" in md


def test_a_green_night_is_green_and_reads_both_lanes(tmp_path: Path) -> None:
    built = report.build(_night(tmp_path), [], {"number": 1}, ROOT)
    assert built["failing_areas"] == [] and not report.is_red(built)
    assert built["lanes"]["electron"]["passed"] == 1
    assert built["lanes"]["web-chromium"]["passed"] == len(specs.AREAS)
    ids = [t["id"] for t in built["tests"]]
    assert "electron:apps/desktop/e2e/shell-smoke.spec.ts::shell scenario @plan-X" not in ids
    assert "electron:apps/desktop/e2e/shell-smoke.spec.ts::shell scenario" in ids


def test_non_pack_tests_are_ignored_and_axe_findings_count_once(tmp_path: Path) -> None:
    _results(
        tmp_path,
        "web-chromium",
        2,
        {
            "a.spec.ts": [
                _spec("plain", "unexpected", []),
                _spec("t", "expected", ["ga-regression", "ga-area-admin"], axe=2),
            ]
        },
    )
    built = report.build(report.load_results(tmp_path / "results"), [], {}, ROOT)
    assert built["summary"]["passed"] == 1 and built["summary"]["failed"] == 0
    assert (
        built["areas"]["admin"]["axe_p2"] == 2
    )  # test and result annotations are one finding each


def test_over_budget_wall_clock_is_red(tmp_path: Path) -> None:
    tests = _night(tmp_path)
    ok = report.build(tests, [], {}, ROOT, "2026-11-01T03:41:00+00:00", "2026-11-01T04:26:00+00:00")
    late = report.build(
        tests, [], {}, ROOT, "2026-11-01T03:41:00+00:00", "2026-11-01T04:26:01+00:00"
    )
    assert ok["budget"] == {"seconds": 2700, "wall_clock_seconds": 2700, "within": True}
    assert late["budget"]["within"] is False and report.is_red(late)
    assert "OVER BUDGET" in report.markdown(late)


def _history(number: int, outcome: str, test_id: str) -> dict[str, Any]:
    return {
        "run": {"number": number},
        "summary": {"passed": 1},
        "tests": [{"id": test_id, "outcome": outcome}],
    }


def test_a_test_flipping_across_three_nights_is_flagged_with_its_rate_and_owner(
    tmp_path: Path,
) -> None:
    _results(
        tmp_path,
        "web-chromium",
        1,
        {"a.spec.ts": [_pack("admin"), _pack("rules", extra=("owner-ann",))]},
    )
    tests = report.load_results(tmp_path / "results")
    admin, rules = (t.id for t in tests)
    history = [
        _history(3, "failed", admin),
        _history(2, "passed", admin),
        _history(4, "flaky", rules),
    ]
    built = report.build(tests, history, {"number": 5}, ROOT)
    rates = {f["id"]: f for f in built["flakes"]}
    # admin over nights 3, 4 (absent), 5: failed then passed is one flip in two runs.
    assert rates[admin]["rate"] == 0.5 and rates[admin]["owner_source"] == "CODEOWNERS"
    assert rates[admin]["owner"].startswith("@")
    assert rates[rules] == {"id": rules, "rate": 0.5, "owner": "ann", "owner_source": "tag"}
    assert [r["run"] for r in built["trend"]] == [2, 3, 4, 5]


def test_a_steady_test_has_no_flake_rate(tmp_path: Path) -> None:
    tests = _night(tmp_path)
    history = [_history(n, "passed", tests[0].id) for n in (1, 2, 3)]
    assert report.build(tests, history, {}, ROOT)["flakes"] == []


def test_codeowners_last_match_wins() -> None:
    rules = [("*", ["@owner"]), ("/apps/web/", ["@frontend"]), ("/apps/web/e2e/*.ts", ["@qa"])]
    assert report.owner_of("apps/web/e2e/a.ts", rules) == "@qa"
    assert report.owner_of("apps/web/src/a.ts", rules) == "@frontend"
    assert report.owner_of("tools/x.py", rules) == "@owner"
    assert report.owner_of("x", []) == "unowned"


def test_the_report_is_a_pure_function_of_its_inputs(tmp_path: Path) -> None:
    out = []
    for n in (1, 2):
        _night(tmp_path / str(n), failing="replay")
        args = [
            str(tmp_path / str(n) / "results"),
            "--out",
            str(tmp_path / f"out{n}"),
            "--run-number",
            "7",
        ]
        assert report.main(args) == 0
        out.append({f.name: f.read_bytes() for f in sorted((tmp_path / f"out{n}").iterdir())})
    assert out[0] == out[1]
    assert set(out[0]) == {
        "ga-report.json",
        "ga-report.md",
        "ga-regression.prom",
        "ga-durations.json",
    }


def test_cli_fails_on_red_and_writes_metrics_and_durations(tmp_path: Path) -> None:
    _night(tmp_path, failing="admin")
    history = tmp_path / "history" / "123"
    history.mkdir(parents=True)
    (history / "ga-report.json").write_text(
        json.dumps(_history(6, "passed", "x")), encoding="utf-8"
    )
    args = [
        str(tmp_path / "results"),
        "--out",
        str(tmp_path / "out"),
        "--history",
        str(tmp_path / "history"),
    ]
    assert report.main([*args, "--fail-on-red"]) == 1
    prom = (tmp_path / "out" / "ga-regression.prom").read_text(encoding="utf-8")
    assert 'ga_regression_fail_total{area="admin"} 1' in prom
    assert 'ga_regression_pass_total{area="replay"} 1' in prom
    assert (
        "ga_regression_duration_seconds{spec=" in prom and "ga_regression_flake_rate{spec=" in prom
    )
    durations = json.loads((tmp_path / "out" / "ga-durations.json").read_text(encoding="utf-8"))
    assert durations["electron"] == {"e2e/shell-smoke.spec.ts": 1.0}
    assert set(durations) == set(specs.APPS)
    saved = json.loads((tmp_path / "out" / "ga-report.json").read_text(encoding="utf-8"))
    assert [r["run"] for r in saved["trend"]] == [6, 0]


def test_unknown_result_folders_and_non_report_json_are_skipped(tmp_path: Path) -> None:
    (tmp_path / "results" / "other-artifact").mkdir(parents=True)
    (tmp_path / "results" / "ga-results-web-chromium-1").mkdir()
    (tmp_path / "results" / "ga-results-web-chromium-1" / "x.json").write_text(
        "[]", encoding="utf-8"
    )
    assert report.load_results(tmp_path / "results") == []


def test_a_green_night_after_a_flip_is_amber_and_fails_the_flake_gate(tmp_path: Path) -> None:
    # The pack runs with zero retries (#1335 ruling): a flake on the night is a failure (RED), and
    # a test that failed last night and passes tonight is the AMBER flake gate.
    _results(tmp_path, "web-chromium", 1, {"a.spec.ts": [_pack("admin"), _pack("rules")]})
    tests = report.load_results(tmp_path / "results")
    built = report.build(tests, [_history(4, "failed", tests[1].id)], {"url": "u"}, ROOT)
    assert built["summary"]["flaky"] == 0
    assert not report.is_red(built) and report.is_amber(built)
    assert report.status(built) == "AMBER"
    md = report.markdown(built)
    assert "## GA regression pack: AMBER" in md and "flipped between failed and passed" in md


def test_a_pass_on_a_retry_given_by_hand_still_reads_amber_never_green(tmp_path: Path) -> None:
    _results(
        tmp_path,
        "web-chromium",
        1,
        {"a.spec.ts": [_pack("admin"), _pack("rules", "flaky")]},
    )
    built = report.build(report.load_results(tmp_path / "results"), [], {"url": "u"}, ROOT)
    assert not report.is_red(built) and report.status(built) == "AMBER"
    args = [str(tmp_path / "results"), "--out", str(tmp_path / "out")]
    assert report.main([*args, "--fail-on-red"]) == 0  # red alone lets a retried pass through
    assert report.main([*args, "--fail-on-red", "--fail-on-amber"]) == 1


def test_a_steady_green_night_is_not_amber(tmp_path: Path) -> None:
    built = report.build(_night(tmp_path), [], {}, ROOT)
    assert report.status(built) == "green"
    args = [str(tmp_path / "results"), "--out", str(tmp_path / "out")]
    assert report.main([*args, "--fail-on-red", "--fail-on-amber"]) == 0


def test_fixme_stubs_are_counted_apart_from_skips_and_failures_link_the_artefacts(
    tmp_path: Path,
) -> None:
    stub = _pack("admin", "skipped")
    stub["tests"][0]["annotations"] = [{"type": "fixme"}]
    _results(
        tmp_path,
        "web-chromium",
        2,
        {"a.spec.ts": [stub, _pack("admin", "skipped"), _pack("rules", "unexpected")]},
    )
    built = report.build(
        report.load_results(tmp_path / "results"), [], {"url": "https://ci/run/7"}, ROOT
    )
    assert built["areas"]["admin"]["skipped"] == 2 and built["areas"]["admin"]["fixme"] == 1
    assert built["summary"]["fixme"] == 1
    md = report.markdown(built)
    assert "| admin | 0 | 0 | 0 | 2 | 1 | 0 |" in md
    assert "1 of them carried `test.fixme` stubs" in md
    assert "[this run's artefacts](https://ci/run/7#artifacts)" in md


def test_the_durations_proposal_skips_carried_stub_files(tmp_path: Path) -> None:
    stub = _pack("admin", "skipped")
    stub["tests"][0]["annotations"] = [{"type": "fixme"}]
    _results(tmp_path, "web-chromium", 1, {"stubs.spec.ts": [stub], "a.spec.ts": [_pack("rules")]})
    built = report.build(report.load_results(tmp_path / "results"), [], {}, ROOT)
    assert report.durations(built)["web-chromium"] == {"e2e/a.spec.ts": 1.0}
