"""Unit tests for tools/ci/collect_licenses.py (E03-T07)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.ci.collect_licenses import from_license_checker, from_pip_licenses, main


def test_from_pip_licenses_normalises_rows() -> None:
    rows = [{"Name": "requests", "Version": "2.31.0", "License": "Apache-2.0"}]
    out = from_pip_licenses(rows)
    assert out == [{"package": "requests", "version": "2.31.0", "license": "Apache-2.0"}]


def test_from_license_checker_normalises_scoped_package_at_version() -> None:
    doc = {"@candleviewer/ui@1.0.0": {"licenses": "MIT"}}
    out = from_license_checker(doc)
    assert out == [{"package": "@candleviewer/ui", "version": "1.0.0", "license": "MIT"}]


def test_from_license_checker_handles_list_of_licenses() -> None:
    doc = {"dual-lib@2.0.0": {"licenses": ["MIT", "Apache-2.0"]}}
    out = from_license_checker(doc)
    assert out[0]["license"] == "MIT"


def test_main_combines_both_sources(tmp_path: Path) -> None:
    pip_path = tmp_path / "pip.json"
    pip_path.write_text(
        json.dumps([{"Name": "black", "Version": "24.0", "License": "MIT"}]), encoding="utf-8"
    )
    npm_path = tmp_path / "npm.json"
    npm_path.write_text(json.dumps({"left-pad@1.0.0": {"licenses": "WTFPL"}}), encoding="utf-8")
    out_path = tmp_path / "combined.json"

    rc = main(
        [
            "--pip-licenses",
            str(pip_path),
            "--license-checker",
            str(npm_path),
            "--out",
            str(out_path),
        ]
    )
    assert rc == 0
    combined = json.loads(out_path.read_text(encoding="utf-8"))
    assert len(combined) == 2
    assert {"package": "black", "version": "24.0", "license": "MIT"} in combined


def test_main_with_only_pip_source(tmp_path: Path) -> None:
    pip_path = tmp_path / "pip.json"
    pip_path.write_text(json.dumps([]), encoding="utf-8")
    out_path = tmp_path / "combined.json"
    rc = main(["--pip-licenses", str(pip_path), "--out", str(out_path)])
    assert rc == 0
    assert json.loads(out_path.read_text(encoding="utf-8")) == []


def test_normalise_license_strips_spdx_parentheses_and_prefers_allowlisted() -> None:
    from tools.ci.collect_licenses import normalise_license

    assert normalise_license("(MIT OR CC0-1.0)") == "MIT"
    assert normalise_license("(WTFPL OR MIT)") == "MIT"
    assert normalise_license("WTFPL OR ISC") == "ISC"
    assert normalise_license("WTFPL") == "WTFPL"


def test_dev_dependency_with_disallowed_licence_reaches_the_gate(tmp_path: Path) -> None:
    """pnpm output without --prod lists dev deps; a disallowed one must fail the gate."""
    from datetime import date

    from tools.ci.collect_licenses import from_pnpm_licenses
    from tools.ci.security_gate import evaluate_licenses

    doc = {
        "MIT": [{"name": "prod-lib", "versions": ["1.0.0"]}],
        "LGPL-3.0-only": [{"name": "dev-only-tool", "versions": ["2.0.0"]}],
    }
    allowlist = json.loads(
        (Path(__file__).resolve().parents[2] / "tools/ci/licenses-allowlist.json").read_text()
    )
    result = evaluate_licenses(
        _findings(from_pnpm_licenses(doc)),
        allowlist,
        [],
        run_date=date(2026, 11, 3),
    )
    text = " ".join(result.messages)
    assert "dev-only-tool" in text and "LGPL-3.0-only" in text
    assert "prod-lib" not in text


def _findings(rows: list[dict[str, str]]) -> list:
    from tools.ci.security_gate import LicenseFinding

    return [LicenseFinding(r["package"], r["version"], r["license"]) for r in rows]


def test_security_workflow_collects_dev_and_prod_dependencies() -> None:
    wf = (Path(__file__).resolve().parents[2] / ".github/workflows/_job-security.yml").read_text()
    lines = [ln.strip() for ln in wf.splitlines() if not ln.strip().startswith("#")]
    cmds = [ln for ln in lines if "pnpm licenses list" in ln]
    assert [("--prod" in c) for c in cmds] == [False, True]
    gates = [ln for ln in lines if "--tool license-scan" in ln]
    assert [("--no-dev-only-exceptions" in g) for g in gates] == [False, True]


@pytest.mark.parametrize(
    ("raw", "spdx"),
    [
        ("ISC License (ISCL)", "ISC"),
        ("Mozilla Public License 2.0 (MPL 2.0)", "MPL-2.0"),
        ("The Unlicense (Unlicense)", "Unlicense"),
        ("CC0 1.0 Universal (CC0 1.0) Public Domain Dedication", "CC0-1.0"),
        ("GNU General Public License v3 (GPLv3)", "GPL-3.0-only"),
        ("GNU General Public License v2 (GPLv2)", "GPL-2.0-only"),
        ("GNU Lesser General Public License v3 (LGPLv3)", "LGPL-3.0-only"),
        ("GNU Lesser General Public License v2 or later (LGPLv2+)", "LGPL-2.1-or-later"),
        ("ISC License (ISCL); MIT License", "ISC"),
        ("(ISC License (ISCL))", "ISC"),
    ],
)
def test_parenthesised_alias_is_looked_up_before_parentheses_are_stripped(
    raw: str, spdx: str
) -> None:
    from tools.ci.collect_licenses import normalise_license

    assert normalise_license(raw) == spdx


def test_classifier_named_lgpl_reaches_the_lgpl_approval_path() -> None:
    from datetime import date

    from tools.ci.collect_licenses import from_pip_licenses
    from tools.ci.security_gate import evaluate_licenses

    rows = from_pip_licenses(
        [
            {
                "Name": "lgpl-lib",
                "Version": "1.0",
                "License": "GNU Lesser General Public License v3 (LGPLv3)",
            }
        ]
    )
    allowlist = json.loads(
        (Path(__file__).resolve().parents[2] / "tools/ci/licenses-allowlist.json").read_text()
    )
    result = evaluate_licenses(_findings(rows), allowlist, [], run_date=date(2026, 11, 3))
    assert result.blocked and result.code == "CI-SEC-003"


def test_parenthesised_conjunction_with_a_prohibited_part_stays_blocked() -> None:
    from datetime import date

    from tools.ci.collect_licenses import normalise_license
    from tools.ci.security_gate import evaluate_licenses

    assert normalise_license("(MIT AND GPL-3.0)") == "MIT AND GPL-3.0"
    allowlist = json.loads(
        (Path(__file__).resolve().parents[2] / "tools/ci/licenses-allowlist.json").read_text()
    )
    rows = [{"package": "x", "version": "1", "license": normalise_license("(MIT AND GPL-3.0)")}]
    result = evaluate_licenses(_findings(rows), allowlist, [], run_date=date(2026, 11, 3))
    assert result.blocked


def test_production_scan_ignores_dev_only_exceptions() -> None:
    from datetime import date

    from tools.ci.security_gate import LicenseFinding, evaluate_licenses

    allowlist = json.loads(
        (Path(__file__).resolve().parents[2] / "tools/ci/licenses-allowlist.json").read_text()
    )
    finding = LicenseFinding("caniuse-lite", "1.0.30001812", "CC-BY-4.0")
    run = date(2026, 11, 3)
    assert not evaluate_licenses([finding], allowlist, [], run_date=run).blocked
    prod = evaluate_licenses([finding], allowlist, [], run_date=run, dev_only_exceptions=False)
    assert prod.blocked and prod.code == "CI-SEC-002"


def test_cli_no_dev_only_exceptions_flag(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from tools.ci.security_gate import main as gate_main

    report = tmp_path / "licenses.json"
    report.write_text(
        json.dumps(
            [{"package": "caniuse-lite", "version": "1.0.30001812", "license": "CC-BY-4.0"}]
        ),
        encoding="utf-8",
    )
    base = ["--tool", "license-scan", "--report", str(report), "--run-date", "2026-11-03"]
    assert gate_main(base) == 0
    assert "security_gate[license-scan]: OK" in capsys.readouterr().out
    assert gate_main([*base, "--no-dev-only-exceptions"]) == 1
    captured = capsys.readouterr()
    assert "BLOCKED (CI-SEC-002)" in captured.out + captured.err
