"""Tests for scripts/check_secrets_hygiene.py (E43-T06)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import check_secrets_hygiene as h

REAL = "AbCdEfGhIjKlMnOpQrSt"  # 20 alnum chars, no dummy prefix (synthetic, test-only)


def _write(root: Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def test_fixture_with_real_looking_key_fails_and_names_file(tmp_path: Path) -> None:
    _write(tmp_path, "services/api/tests/fixtures/bybit/a.json", f'{{"api_key": "{REAL}"}}')
    errors = h.check_fixtures(tmp_path)
    assert len(errors) == 1
    assert "services/api/tests/fixtures/bybit/a.json" in errors[0]


def test_fixture_with_dummy_prefix_passes(tmp_path: Path) -> None:
    _write(tmp_path, "tests/fixtures/a.json", f'{{"api_key": "{h.DUMMY_PREFIX}{REAL}"}}')
    assert h.check_fixtures(tmp_path) == []


def test_fixture_signature_and_private_key_fail(tmp_path: Path) -> None:
    _write(tmp_path, "tests/fixtures/s.json", '{"sign": "' + "a" * 64 + '"}')
    _write(tmp_path, "tests/fixtures/k.txt", "-----BEGIN PRIVATE KEY-----")
    assert len(h.check_fixtures(tmp_path)) == 2


def test_repo_fixtures_are_clean() -> None:
    assert h.check_fixtures(Path(__file__).resolve().parents[2]) == []


def test_dev_env_ok_and_violations(tmp_path: Path) -> None:
    _write(tmp_path, ".gitignore", ".env\n.env.*\n")
    _write(tmp_path, ".env.example", "# c\nCV_ENV=demo\nBYBIT_API_SECRET=\n")
    assert h.check_dev_env(tmp_path) == []
    _write(tmp_path, ".env.example", f"BYBIT_API_SECRET={REAL}\n")
    assert any("non-empty" in e for e in h.check_dev_env(tmp_path))
    _write(tmp_path, ".gitignore", "node_modules\n")
    assert any(".gitignore" in e for e in h.check_dev_env(tmp_path))


def test_repo_dev_env_is_clean() -> None:
    assert h.check_dev_env(Path(__file__).resolve().parents[2]) == []


@pytest.mark.parametrize("line", ["run: set -x", "run: set -euxo pipefail", "run: printenv", "run: env | sort"])
def test_workflow_leaks_flagged(tmp_path: Path, line: str) -> None:
    _write(tmp_path, ".github/workflows/w.yml", f"jobs:\n  a:\n    steps:\n      - {line}\n")
    assert h.check_workflows(tmp_path)


def test_workflow_clean_and_allow_marker(tmp_path: Path) -> None:
    _write(tmp_path, ".github/workflows/w.yml", "      - run: set -euo pipefail\n      - run: env # x\n")
    assert h.check_workflows(tmp_path) == []
    _write(tmp_path, ".github/workflows/w.yml", "      - run: set -x # secrets-hygiene: allow\n")
    assert h.check_workflows(tmp_path) == []


def test_repo_workflows_report() -> None:
    # Informational guard: repository workflows must have no tracing/env dumps.
    assert h.check_workflows(Path(__file__).resolve().parents[2]) == []


def test_inventory_flags_prod_credentials_and_unprotected() -> None:
    errs = h.check_inventory(["BYBIT_LIVE_API_KEY", "PROD_KEK", "CODECOV_TOKEN", "AWS_SECRET_ACCESS_KEY"], {"RELEASE_SIGN": False})
    assert len(errs) == 4 + 0 or len(errs) == 4
    assert any("IR-02" in e for e in errs)
    assert h.check_inventory(["CODECOV_TOKEN"], {"X": True}) == []


def test_logs_scan_catches_leak_and_references_ir02(tmp_path: Path) -> None:
    (tmp_path / "job.log").write_text(f"X-BAPI-API-KEY: {REAL}\n", encoding="utf-8")
    (tmp_path / "ok.log").write_text("all good\n", encoding="utf-8")
    errs = h.check_logs([tmp_path])
    assert len(errs) == 1 and "job.log" in errs[0] and "IR-02" in errs[0]


def test_main_exit_codes(tmp_path: Path) -> None:
    _write(tmp_path, "tests/fixtures/a.json", f'{{"api_key": "{REAL}"}}')
    assert h.main(["fixtures", "--root", str(tmp_path)]) == 1
    assert h.main(["workflows", "--root", str(tmp_path)]) == 0


def test_leaky_job_output_fails_log_scan_and_ci_wires_it(tmp_path: Path) -> None:
    leaky = tmp_path / "job.log"
    leaky.write_text("X-BAPI-API-KEY: " + REAL + chr(10), encoding="utf-8")
    assert h.check_logs([leaky])
    wf = (Path(__file__).resolve().parents[2] / ".github/workflows/_job-security.yml").read_text(
        encoding="utf-8"
    )
    assert "check_secrets_hygiene.py logs" in wf
    assert "check_secrets_hygiene.py all" in wf


# E27-Q01 (#833): the bare key-shape rule over the accounts fault-injection pack. Tokens are
# built at run time, so no key-shaped literal sits in this file.
PACK = "packages/fixtures/accounts"


def _alnum(n: int) -> str:
    return "".join("aB3"[i % 3] for i in range(n))


def _capitals_then_small(capitals: int, n: int) -> str:
    return "Q" * capitals + "q" * (n - capitals)


@pytest.mark.parametrize(
    ("token", "shape"),
    [
        (_alnum(18), "api-key"),
        (_alnum(19), "api-key"),
        (_alnum(20), "api-key"),
        (_alnum(36), "api-secret"),
        ("".join("aB"[i % 2] for i in range(20)), "api-key"),
        (_capitals_then_small(h._MIXED_CASE_MIN, 18), "api-key"),
    ],
    ids=["18", "19", "20", "36", "letters_alternating", "letters_at_threshold"],
)
def test_bare_key_shape_in_the_accounts_pack_fails_without_echoing_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], token: str, shape: str
) -> None:
    _write(tmp_path, f"{PACK}/x/manifest.json", f'{{"description": "pasted {token} here"}}')
    errors = h.check_fixtures(tmp_path)
    assert errors == [
        (
            f"{PACK}/x/manifest.json: bare {shape}-shaped token ({len(token)} chars at offset 24);"
            " the token is never printed (E27-Q01)"
        )
    ]
    assert h.main(["fixtures", "--root", str(tmp_path)]) == 1
    assert token not in capsys.readouterr().err


@pytest.mark.parametrize(
    "text",
    [
        "00000000-0000-4000-8000-000000000001",  # a UUID
        "ab" * 32,  # a sha256 digest
        "1792141200000",  # epoch milliseconds
        "1700000000123456789",  # epoch nanoseconds, digits only
        "fixture-withdraw_enabled-0003",  # a fixture key id
        "fixture-withdraw_enabled-secret-not-real",  # a fixture secret
        h.DUMMY_PREFIX + _alnum(18),  # a dummy-prefixed id
        _alnum(10) + "-" + _alnum(9),  # a hyphen-joined token
        "unifiedMarginStatus",  # camelCase field names
        "availableToWithdraw",
        "SubMemberTransferLis",  # PascalCase, four capitals
        _capitals_then_small(h._MIXED_CASE_MIN - 1, 18),
        _capitals_then_small(18 - h._MIXED_CASE_MIN + 1, 18),
        _alnum(17),
        _alnum(21),
        _alnum(35),
        _alnum(37),
    ],
)
def test_scan_key_shapes_passes_benign_tokens(text: str) -> None:
    assert h.scan_key_shapes(f'"{text}"') == []


def test_key_shape_rule_scans_every_pack_file_even_test_named_ones(tmp_path: Path) -> None:
    _write(tmp_path, f"{PACK}/test/test_x.txt", _alnum(20))
    _write(tmp_path, f"{PACK}/notes.bin", _alnum(36))
    assert len(h.check_fixtures(tmp_path)) == 2


def test_key_shape_rule_is_scoped_to_the_accounts_pack(tmp_path: Path) -> None:
    _write(tmp_path, "packages/fixtures/bybit/x.json", f'{{"note": "{_alnum(20)}"}}')
    assert h.check_fixtures(tmp_path) == []


def test_the_rule_matches_the_pack_checks_in_the_js_lane() -> None:
    """The JS twin (accounts-pack.mjs) must carry the same threshold."""
    js = (
        Path(__file__).resolve().parents[2] / "packages/fixtures/scripts/accounts-pack.mjs"
    ).read_text(encoding="utf-8")
    assert f"export const MIXED_CASE_MIN = {h._MIXED_CASE_MIN};" in js
    assert "const TOKEN = /[A-Za-z0-9_-]+/g;" in js
