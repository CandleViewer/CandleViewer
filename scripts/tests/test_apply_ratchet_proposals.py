"""Unit tests for tools/ci/apply_ratchet_proposals.py (E03-T04)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.ci import apply_ratchet_proposals
from tools.ci.apply_ratchet_proposals import apply_proposals, main


def _baselines(tmp_path: Path, packages: dict[str, dict[str, object]]) -> Path:
    path = tmp_path / "coverage-baselines.json"
    path.write_text(
        json.dumps({"tolerance_pp": 0.5, "packages": packages}), encoding="utf-8"
    )
    return path


def test_apply_proposals_raises_baseline(tmp_path: Path) -> None:
    baselines = _baselines(
        tmp_path,
        {
            "packages/protocol": {
                "floor": 85.0,
                "baseline": 88.0,
                "artifact": "a",
                "report_format": "lcov",
            }
        },
    )
    changes = apply_proposals({"packages/protocol": 89.4}, baselines)
    assert changes == ["packages/protocol: 88.0% -> 89.4%"]

    updated = json.loads(baselines.read_text(encoding="utf-8"))
    assert updated["packages"]["packages/protocol"]["baseline"] == 89.4


def test_apply_proposals_ignores_lower_or_equal_values(tmp_path: Path) -> None:
    baselines = _baselines(
        tmp_path,
        {
            "packages/ui": {
                "floor": 80.0,
                "baseline": 91.0,
                "artifact": "a",
                "report_format": "lcov",
            }
        },
    )
    changes = apply_proposals({"packages/ui": 90.0}, baselines)
    assert changes == []
    updated = json.loads(baselines.read_text(encoding="utf-8"))
    assert updated["packages"]["packages/ui"]["baseline"] == 91.0


def test_apply_proposals_ignores_unknown_package(tmp_path: Path) -> None:
    baselines = _baselines(tmp_path, {})
    assert apply_proposals({"does/not-exist": 99.0}, baselines) == []


def test_main_no_proposals_file_is_a_noop(tmp_path: Path, monkeypatch: object) -> None:
    baselines = _baselines(tmp_path, {})
    rc = main([str(tmp_path / "missing.json"), str(baselines)])
    assert rc == 0


def test_main_applies_and_writes_github_output(
    tmp_path: Path, monkeypatch: object
) -> None:
    baselines = _baselines(
        tmp_path,
        {
            "packages/protocol": {
                "floor": 85.0,
                "baseline": 88.0,
                "artifact": "a",
                "report_format": "lcov",
            }
        },
    )
    proposals = tmp_path / "proposals.json"
    proposals.write_text(json.dumps({"packages/protocol": 89.4}), encoding="utf-8")
    gh_output = tmp_path / "gh_output.txt"
    monkeypatch.setattr(
        "os.environ", {**__import__("os").environ, "GITHUB_OUTPUT": str(gh_output)}
    )

    rc = main([str(proposals), str(baselines)])
    assert rc == 0
    content = gh_output.read_text(encoding="utf-8")
    assert "changed=true" in content
    assert "packages/protocol" in content


def test_main_wrong_arg_count_returns_two() -> None:
    assert main([]) == 2


def _multiline_outputs(path: Path) -> list[tuple[str, str]]:
    """(delimiter, value) per `name<<delimiter` entry of a $GITHUB_OUTPUT file."""
    entries: list[tuple[str, str]] = []
    lines = iter(path.read_text(encoding="utf-8").splitlines())
    for line in lines:
        _, multiline, delimiter = line.partition("<<")
        if multiline:
            value = []
            for value_line in lines:
                if value_line == delimiter:
                    break
                value.append(value_line)
            entries.append((delimiter, "\n".join(value)))
    return entries


def test_each_multiline_output_has_a_fresh_delimiter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gh_output = tmp_path / "gh_output.txt"
    monkeypatch.setenv("GITHUB_OUTPUT", str(gh_output))
    value = "- packages/protocol: 88.0% -> 89.4%\n- packages/ui: 80.0% -> 81.0%"
    apply_ratchet_proposals._write_github_output("summary", value)
    apply_ratchet_proposals._write_github_output("summary", value)
    (first, first_value), (second, second_value) = _multiline_outputs(gh_output)
    assert first_value == second_value == value
    assert first != second and first not in value


# --- Untrusted input (#3508): the proposals document is untrusted input -----


@pytest.mark.parametrize(
    "text",
    [
        "{not json",
        '["packages/protocol", 89.4]',
        '{"packages/protocol": "89.4"}',
        '{"packages/protocol": true}',
        '{"packages/protocol": null}',
        '{"packages/protocol": NaN}',
        '{"packages/protocol": Infinity}',
        '{"packages/protocol": 150.0}',
        "[" * 60_000,
        "oversized",
        "too-many",
        "link",
    ],
    ids=lambda text: text if len(text) < 40 else "deeply-nested",
)
def test_main_refuses_an_untrusted_proposals_document(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], text: str
) -> None:
    pkg = {"floor": 85.0, "baseline": 88.0, "artifact": "a", "report_format": "lcov"}
    baselines = _baselines(tmp_path, {"packages/protocol": pkg})
    before = baselines.read_text(encoding="utf-8")
    proposals = tmp_path / "proposals.json"
    raise_one = json.dumps({"packages/protocol": 89.4})
    if text == "oversized":
        text = raise_one + " " * apply_ratchet_proposals.MAX_PROPOSALS_BYTES
    elif text == "too-many":
        names = [f"p{i}" for i in range(apply_ratchet_proposals.MAX_PROPOSALS)]
        text = json.dumps({**dict.fromkeys(names, 90.0), "packages/protocol": 89.4})
    if text == "link":
        proposals.symlink_to(tmp_path / "elsewhere.json")
        (tmp_path / "elsewhere.json").write_text(raise_one, encoding="utf-8")
    else:
        proposals.write_text(text, encoding="utf-8")

    assert main([str(proposals), str(baselines)]) == 1
    assert "CI-COV-004" in capsys.readouterr().err
    assert baselines.read_text(encoding="utf-8") == before
