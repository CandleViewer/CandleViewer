"""Meta-tests for tools/a11y/redact.py (E47-Q04): seeded secrets are stripped, rule data is kept.

Every secret below is assembled at run time from fragments, so no source line matches a gitleaks rule.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.a11y import redact

KEY = "fake" + "Key" + "9" * 12 + "ABCD"  # 20 alphanumerics
HEX_SIG = "ab12" * 16
CVS = "cv" + "s_" + "A1" * 22  # 44 chars after the prefix
CVR = "cv" + "r_" + "b2-_" * 11
CVI = "cv" + "i_" + "C3" * 22 + "-"  # ends in `-`: a closing \b would miss it
RECOVERY = "ABCDE" + "-" + "FGHIJ"
RECOVERY2 = "KLMNP" + "-" + "QRSTU"
TOTP_SECRET = "JBSWY3DP" + "EHPK3PXP"
TOTP_SPACED = "JBSW Y3DP EHPK 3PXP"
SESSION = "s3ss10n" + "id" * 6
EMAIL = "trader.one" + "@" + "example.com"
TOTP = "493" + "027"
PASSWORD = "hunter" + "2hunter2"


def _gone(out: str, *secrets: str) -> None:
    for s in secrets:
        assert s not in out, f"{s!r} survived in {out!r}"


@pytest.mark.parametrize(
    ("text", "secret"),
    [
        (f'"api_key": "{KEY}"', KEY),
        (f'"apiSecret":"{KEY}"', KEY),
        (f"apiKey={KEY}", KEY),
        (f'textbox "API key": "{KEY}"', KEY),
        (f'<input aria-label="API key" value="{KEY}">', KEY),
        (f'<input aria-label="API secret" value="{KEY}">', KEY),
        (f'textbox "API secret": "{KEY}"', KEY),
        (f'"api key": "{KEY}"', KEY),
        (f'{{"sign": "{HEX_SIG}"}}', HEX_SIG),
        (f'"signature": "{HEX_SIG}"', HEX_SIG),
        (f"X-BAPI-SIGN: {HEX_SIG}", HEX_SIG),
        (f"x-bapi-api-key={KEY}", KEY),
        (f"token {CVS}", CVS),
        (f"x_{CVS}", CVS),  # `_` is a word char: a leading \b would miss it
        (f"id={CVR}", CVR),
        (f"invite {CVI}", CVI),
        (f"recovery codes: {RECOVERY}, {RECOVERY2}", RECOVERY2),
        (f"Recovery_codes = [{RECOVERY}]", RECOVERY),
        (f"save {RECOVERY} now", RECOVERY),
        (f"totp_secret={TOTP_SECRET}", TOTP_SECRET),
        (f"TOTP secret: {TOTP_SPACED}", "Y3DP"),
        (f"Setup key {TOTP_SPACED}", "EHPK"),
        (f"otpauth://totp/CV:me?secret={TOTP_SECRET}&issuer=CV", TOTP_SECRET),
        (f"manual entry: {TOTP_SPACED}", "3PXP"),
        (f"/cb?session={SESSION}&x=1", SESSION),
        (f"/cb?x=1&sid={SESSION}", SESSION),
        (f"/p;jsessionid={SESSION}", SESSION),
        (f"/r?token={SESSION}", SESSION),
        (f"/r?access_token={SESSION}", SESSION),
        (f"Bearer {'x' * 8}{SESSION}", SESSION),
        (f"mail {EMAIL} now", EMAIL),
        (f'<label>Authentication code</label><input id="c" value="{TOTP}">', TOTP),
        (f"Enter the code {TOTP[:3]} {TOTP[3:]}", TOTP[3:]),
        (f'<input aria-label="Authentication code" value="{TOTP}">', TOTP),
        (f'<input autocomplete="one-time-code" value="{TOTP}">', TOTP),
        (f'<input name="otp" value="{TOTP}">', TOTP),
        (f'<input value="{TOTP}" name="totp">', TOTP),
        (f'<input type="password" value="{PASSWORD}">', PASSWORD),
        (f"password: {PASSWORD}", PASSWORD),
    ],
)
def test_each_probe_shape_is_stripped(text: str, secret: str) -> None:
    _gone(redact.redact_text(text), secret)


def test_redact_json_strips_values_and_keys() -> None:
    doc = {
        EMAIL: "key is an address",
        CVS: {"nested": 1},
        "x-bapi-sign": HEX_SIG,
        "sign": "short",
        "recovery_codes": [RECOVERY, RECOVERY2],
        "password": PASSWORD,
        "token": [SESSION],
        "html": f'<input name="otp" value="{TOTP}">',
        "note": KEY[:4] + "0" + KEY[5:],  # a whole value that looks like a key
        "id": "color-contrast",
        "impact": "serious",
        "target": ["#login > input"],
    }
    out = redact.redact_json(doc)
    flat = json.dumps(out)
    _gone(flat, EMAIL, CVS, HEX_SIG, "short", RECOVERY, RECOVERY2, PASSWORD, SESSION, TOTP)
    assert out["id"] == "color-contrast" and out["target"] == ["#login > input"]  # type: ignore[index]


def test_json_key_with_a_space_redacts_its_value() -> None:
    out = redact.redact_json({"API key": KEY, "API secret": KEY})
    _gone(json.dumps(out), KEY)


def test_two_keys_that_redact_alike_both_survive() -> None:
    out = redact.redact_json({"a" + "@x.io": 1, "b" + "@x.io": 2})
    assert sorted(out.values()) == [1, 2]  # type: ignore[union-attr]


def test_rule_ids_codes_scores_and_ordinary_text_survive() -> None:
    for text in (
        '{"code": "WCAG2AA.Principle1.Guideline1_4.1_4_3.G18", "id": "color-contrast", "score": 0.97}',
        "HTTP code 404",
        '<button class="buy">Buy 100.50</button>',
        "textbox 'Quantity' value 0.005",
    ):
        assert redact.redact_text(text) == text


def test_redact_dir_rewrites_every_text_file_and_reports_the_changed_ones(tmp_path: Path) -> None:
    (tmp_path / "axe.json").write_text(json.dumps({"html": f'<input name="otp" value="{TOTP}">'}), encoding="utf-8")
    (tmp_path / "trees").mkdir()
    (tmp_path / "trees" / "login.txt").write_text(f"textbox {EMAIL}\n", encoding="utf-8")
    (tmp_path / "page.html").write_text(f'<input name="totp" value="{TOTP}">', encoding="utf-8")
    (tmp_path / "keep.json").write_text('{"scores": {"SCR-001": 0.98}}', encoding="utf-8")
    changed = redact.redact_dir(tmp_path)
    assert len(changed) == 3 and not any("keep.json" in c for c in changed)
    for f in tmp_path.rglob("*"):
        if f.is_file():
            _gone(f.read_text(encoding="utf-8"), EMAIL, TOTP)
    assert json.loads((tmp_path / "keep.json").read_text())["scores"]["SCR-001"] == 0.98


@pytest.mark.parametrize("name", ["shot.png", "trace.zip", "noext", "video.webm"])
def test_unknown_suffix_fails_instead_of_uploading_unread(tmp_path: Path, name: str) -> None:
    (tmp_path / "ok.json").write_text("{}", encoding="utf-8")
    (tmp_path / name).write_bytes(b"\x89PNG")
    with pytest.raises(redact.UnreadableReport, match="A11Y-INFRA"):
        redact.redact_dir(tmp_path)
    assert redact.main([str(tmp_path)]) == 3


def test_non_utf8_text_file_fails(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_bytes(b"\xff\xfe\x00bad")
    assert redact.main([str(tmp_path)]) == 3


def test_symlink_in_the_report_dir_fails(tmp_path: Path) -> None:
    (tmp_path / "t.txt").write_text("x", encoding="utf-8")
    (tmp_path / "link.json").symlink_to(tmp_path / "t.txt")
    assert redact.main([str(tmp_path)]) == 3


def test_cli_directory_mode_and_stdin_filter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert redact.main([str(tmp_path / "absent")]) == 3
    (tmp_path / "a.json").write_text(json.dumps({"e": EMAIL}), encoding="utf-8")
    assert redact.main([str(tmp_path)]) == 0
    assert EMAIL not in (tmp_path / "a.json").read_text()
    import io

    monkeypatch.setattr(sys, "stdin", io.StringIO(f"A11Y-G001 node=#u value {EMAIL}\n"))
    assert redact.main(["-"]) == 0
    assert EMAIL not in capsys.readouterr().out


def test_pa11y_output_context_and_message_are_redacted(tmp_path: Path) -> None:
    out = {
        "results": {
            "http://127.0.0.1:4173/login": [
                {
                    "code": "WCAG2AA.Principle3.Guideline3_3.3_3_2.H44",
                    "type": "error",
                    "message": f"Label missing for {EMAIL}",
                    "context": f'<input aria-label="API key" value="{KEY}"><input name="otp" value="{TOTP}">',
                    "selector": "#api",
                }
            ]
        }
    }
    (tmp_path / "pa11y.json").write_text(json.dumps(out), encoding="utf-8")
    assert redact.main([str(tmp_path)]) == 0
    body = (tmp_path / "pa11y.json").read_text(encoding="utf-8")
    _gone(body, EMAIL, KEY, TOTP)
    assert "WCAG2AA.Principle3" in body and "#api" in body
