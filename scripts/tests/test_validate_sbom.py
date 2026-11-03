"""Unit tests for tools/ci/validate_sbom.py (SR-133, CI-IMG-005)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.ci.validate_sbom import main, validate

VALID_SBOM = {
    "bomFormat": "CycloneDX",
    "specVersion": "1.5",
    "components": [{"type": "library", "name": "fastapi", "version": "0.115.0"}],
}


def test_validate_accepts_well_formed_document() -> None:
    assert validate(VALID_SBOM) == []


def test_validate_rejects_missing_top_level_field() -> None:
    doc = {k: v for k, v in VALID_SBOM.items() if k != "components"}
    problems = validate(doc)
    assert any("missing required field" in p for p in problems)


def test_validate_rejects_wrong_bom_format() -> None:
    doc = {**VALID_SBOM, "bomFormat": "SPDX"}
    problems = validate(doc)
    assert any("bomFormat" in p for p in problems)


def test_validate_rejects_non_1x_spec_version() -> None:
    doc = {**VALID_SBOM, "specVersion": "2.0"}
    problems = validate(doc)
    assert any("specVersion" in p for p in problems)


def test_validate_rejects_component_missing_name() -> None:
    doc = {**VALID_SBOM, "components": [{"type": "library"}]}
    problems = validate(doc)
    assert any("name" in p for p in problems)


def test_main_exits_0_for_valid_sbom(tmp_path: Path) -> None:
    p = tmp_path / "sbom.json"
    p.write_text(json.dumps(VALID_SBOM), encoding="utf-8")
    assert main(["--sbom", str(p)]) == 0


def test_main_exits_1_for_invalid_sbom(tmp_path: Path) -> None:
    p = tmp_path / "sbom.json"
    p.write_text(json.dumps({"bomFormat": "CycloneDX"}), encoding="utf-8")
    assert main(["--sbom", str(p)]) == 1


def test_main_exits_2_for_missing_file(tmp_path: Path) -> None:
    assert main(["--sbom", str(tmp_path / "nope.json")]) == 2


def test_main_exits_2_for_invalid_json(tmp_path: Path) -> None:
    p = tmp_path / "sbom.json"
    p.write_text("{not json", encoding="utf-8")
    assert main(["--sbom", str(p)]) == 2


# #3099 (SR-133): the release run's three SBOMs fail as CI-REL-006, naming the artefact.
@pytest.mark.parametrize(
    ("text", "finding"),
    [
        (None, "SBOM file not found"),
        ("", "not valid JSON"),
        ("{not json", "not valid JSON"),
        ("[]", "root is not a JSON object"),
        ('{"bomFormat": "CycloneDX", "specVersion": "1.5", "components": []}', "empty"),
        ('{"bomFormat": "SPDX", "specVersion": "1.5", "components": []}', "bomFormat"),
    ],
    ids=["missing", "empty-file", "not-json", "not-object", "no-component", "invalid"],
)
def test_release_artefact_sbom_fails_ci_rel_006_naming_the_artefact(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], text: str | None, finding: str
) -> None:
    sbom = tmp_path / "sbom-web.cdx.json"
    if text is not None:
        sbom.write_text(text, encoding="utf-8")
    assert main(["--sbom", str(sbom), "--artefact", "web"]) == 1
    err = capsys.readouterr().err
    assert err.startswith("CI-REL-006: web SBOM (") and finding in err


def test_release_artefact_sbom_with_components_passes(tmp_path: Path) -> None:
    sbom = tmp_path / "sbom-api.cdx.json"
    sbom.write_text(json.dumps(VALID_SBOM), encoding="utf-8")
    assert main(["--sbom", str(sbom), "--artefact", "api"]) == 0


def test_image_sbom_without_components_still_passes_ci_img_005(tmp_path: Path) -> None:
    # main.yml's call is unchanged: the empty refusal is the release run's (CI-REL-006) only.
    sbom = tmp_path / "sbom.json"
    sbom.write_text(json.dumps({**VALID_SBOM, "components": []}), encoding="utf-8")
    assert main(["--sbom", str(sbom)]) == 0
