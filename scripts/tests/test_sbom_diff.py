"""Unit tests for tools/ci/sbom_diff.py (SR-135)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.ci.sbom_diff import _component_keys, main, render_diff

SBOM_A = {
    "components": [
        {"name": "fastapi", "version": "0.115.0"},
        {"name": "pydantic", "version": "2.9.0"},
    ]
}
SBOM_B = {
    "components": [
        {"name": "fastapi", "version": "0.115.0"},
        {"name": "httpx", "version": "0.27.0"},
    ]
}


def test_component_keys_formats_name_at_version() -> None:
    assert _component_keys(SBOM_A) == {"fastapi@0.115.0", "pydantic@2.9.0"}


def test_render_diff_with_no_previous_lists_everything_as_new() -> None:
    out = render_diff(SBOM_A, None)
    assert "No previous" in out
    assert "fastapi@0.115.0" in out
    assert "pydantic@2.9.0" in out


def test_render_diff_reports_added_and_removed() -> None:
    out = render_diff(SBOM_B, SBOM_A)
    assert "Added" in out
    assert "httpx@0.27.0" in out
    assert "Removed" in out
    assert "pydantic@2.9.0" in out
    # unchanged component must not appear in either added/removed list
    assert "+ `fastapi@0.115.0`" not in out
    assert "- `fastapi@0.115.0`" not in out


def test_render_diff_no_changes_reports_no_component_changes() -> None:
    out = render_diff(SBOM_A, SBOM_A)
    assert "No component changes" in out


# #3099 (SR-133, BQ-16): the release run diffs each SBOM against the previous release's file.
def _write(path: Path, doc: object) -> Path:
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


def test_main_previous_file_reports_added_and_removed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    current = _write(tmp_path / "sbom-api.cdx.json", SBOM_B)
    previous = _write(tmp_path / "prev.json", SBOM_A)
    heading = "### SBOM diff: api vs v0.1.0 (SR-133)"
    args = ["--current", str(current), "--previous", str(previous), "--heading", heading]
    assert main(args) == 0
    out = capsys.readouterr().out
    assert out.startswith(heading + "\n")
    assert "+ `httpx@0.27.0`" in out and "- `pydantic@2.9.0`" in out


def test_main_missing_previous_file_is_the_first_release(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    current = _write(tmp_path / "sbom-web.cdx.json", SBOM_A)
    assert main(["--current", str(current), "--previous", str(tmp_path / "absent.json")]) == 0
    out = capsys.readouterr().out
    assert "First release, no baseline" in out and "all 2 components listed as new" in out
    assert "+ `fastapi@0.115.0`" in out


@pytest.mark.parametrize("text", ["{not json", "[]", ""])
def test_main_unreadable_previous_file_says_so_and_lists_everything(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], text: str
) -> None:
    current = _write(tmp_path / "sbom-web.cdx.json", SBOM_A)
    previous = tmp_path / "prev.json"
    previous.write_text(text, encoding="utf-8")
    assert main(["--current", str(current), "--previous", str(previous)]) == 0
    out = capsys.readouterr().out
    assert "`prev.json` is unreadable, no baseline" in out and "pydantic@2.9.0" in out


def test_main_baselines_are_exclusive_and_the_digest_needs_an_image(tmp_path: Path) -> None:
    current = _write(tmp_path / "c.json", SBOM_A)
    with pytest.raises(SystemExit):
        main(["--current", str(current), "--previous", "p.json", "--previous-digest", "none"])
    with pytest.raises(SystemExit):
        main(["--current", str(current), "--previous-digest", "none"])
    with pytest.raises(SystemExit):
        main(["--current", str(current)])


def test_main_digest_mode_keeps_the_image_heading(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    current = _write(tmp_path / "c.json", SBOM_A)
    assert main(["--current", str(current), "--previous-digest", "none", "--image", "r/i"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("### SBOM diff vs previous `:dev` image (SR-135)")
    assert "No previous `:dev` attestation" in out
