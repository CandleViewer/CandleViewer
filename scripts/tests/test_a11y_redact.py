"""Meta-tests for tools/a11y/redact.py (E47-Q04): seeded secrets are stripped, rule data is kept."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.a11y import redact

API_KEY = "sk-" + "live_Zq8Vn3xT5bRw2LmYp9Kd"
EMAIL = "trader.one@example.com"
TOTP = "493027"


def _report() -> dict:
    return {
        "screens": {
            "R-001": {
                "violations": [
                    {
                        "id": "label",
                        "impact": "critical",
                        "nodes": [
                            {
                                "target": ["#username"],
                                "html": f'<input id="username" value="{EMAIL}"><input name="otp" value="{TOTP}">'
                                f'<input name="apiKey" value="{API_KEY}">',
                                "failureSummary": f"Fix any of: label missing for {EMAIL}",
                            }
                        ],
                    }
                ]
            }
        }
    }


def test_redact_json_strips_seeded_secrets_and_keeps_shape() -> None:
    out = json.dumps(redact.redact_json(_report()))
    for secret in (API_KEY, EMAIL, TOTP):
        assert secret not in out
    node = redact.redact_json(_report())["screens"]["R-001"]["violations"][0]  # type: ignore[index]
    assert node["id"] == "label" and node["nodes"][0]["target"] == ["#username"]


def test_redact_dir_rewrites_json_txt_and_html_in_place(tmp_path: Path) -> None:
    (tmp_path / "axe.json").write_text(json.dumps(_report()), encoding="utf-8")
    (tmp_path / "trees").mkdir()
    (tmp_path / "trees" / "login.txt").write_text(f"textbox {EMAIL}\n", encoding="utf-8")
    (tmp_path / "page.html").write_text(f'<input name="totp" value="{TOTP}">', encoding="utf-8")
    (tmp_path / "keep.json").write_text('{"scores": {"SCR-001": 0.98}}', encoding="utf-8")
    changed = redact.redact_dir(tmp_path)
    assert len(changed) == 3 and not any("keep.json" in c for c in changed)
    for f in tmp_path.rglob("*"):
        if f.is_file():
            body = f.read_text(encoding="utf-8")
            assert not any(s in body for s in (API_KEY, EMAIL, TOTP)), f
    assert json.loads((tmp_path / "keep.json").read_text())["scores"]["SCR-001"] == 0.98


def test_rule_ids_codes_and_scores_survive() -> None:
    text = '{"code": "WCAG2AA.Principle1.Guideline1_4.1_4_3.G18", "id": "color-contrast", "score": 0.97}'
    assert redact.redact_text(text) == text


def test_cli_needs_a_directory(tmp_path: Path) -> None:
    assert redact.main([str(tmp_path / "absent")]) == 3
    (tmp_path / "a.json").write_text(json.dumps({"e": EMAIL}), encoding="utf-8")
    assert redact.main([str(tmp_path)]) == 0
    assert EMAIL not in (tmp_path / "a.json").read_text()
