"""Unit tests for tools/ci/resolve_image_digests.py (#1857). Fake registry; no network."""

from __future__ import annotations

import sys
import urllib.error
from collections.abc import Callable
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.ci.resolve_image_digests import is_placeholder, main, split_repo, with_retry

REAL = "sha256:" + "0123456789abcdef" * 2 + "fedcba9876543210" * 2
REAL2 = "sha256:a1b2c3d4e5f60718293a4b5c6d7e8f901f2e3d4c5b6a798897a6b5c4d3e2f101"
PLACEHOLDER = "sha256:" + "ab12cd34" * 8
PG = ("postgres", "16.4", REAL2)
LEDGER = "infra/images/PINS.md"
COMPOSE = "infra/compose/docker-compose.yml"


class FakeRegistry:
    def __init__(self, tags: dict[tuple[str, str], str]) -> None:
        self.tags = tags

    def digest(self, repo: str, tag: str) -> str | None:
        return self.tags.get((repo, tag))

    def exists(self, repo: str, digest: str) -> bool:
        return digest in self.tags.values()


class DownRegistry(FakeRegistry):
    """A registry that cannot be reached."""

    def exists(self, repo: str, digest: str) -> bool:
        raise urllib.error.URLError("registry unreachable")


def _ledger(root: Path, *rows: tuple[str, str, str]) -> None:
    """Write PINS.md: header on line 3, rows from line 5, then a blank and the count line."""
    f = root / LEDGER
    f.parent.mkdir(parents=True, exist_ok=True)
    head = "| Image | Tag | Digest | Registry |\n| --- | --- | --- | --- |\n"
    table = "".join(f"| {i} | {t} | {d} | Docker Hub |\n" for i, t, d in rows)
    count = f"All {len(rows)} pins are verified.\n"
    f.write_text(f"# Pins\n\n{head}{table}\n{count}", encoding="utf-8")


def _tree(tmp_path: Path, digest: str, row: tuple[str, str, str] | None = None) -> Path:
    """One compose pin (line 3) and a ledger row for it (``row`` plants a drifted one)."""
    (tmp_path / "infra" / "compose").mkdir(parents=True)
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    f = tmp_path / "infra" / "compose" / "docker-compose.yml"
    f.write_text(
        f"services:\n  db:\n    image: postgres:16.4@{digest}\n", encoding="utf-8"
    )
    _ledger(tmp_path, row or ("postgres", "16.4", digest))
    return f


def _check(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> tuple[int, str]:
    """``--check`` with a registry that knows every digest, so only the ledger can fail."""
    reg = FakeRegistry({("postgres", "16.4"): REAL2, ("redis", "7"): REAL})
    rc = main(["--check", "--root", str(tmp_path)], reg)
    return rc, capsys.readouterr().err


def test_is_placeholder_flags_fabricated_patterns() -> None:
    assert is_placeholder("0" * 64)
    assert is_placeholder("ab12cd34" * 8)
    assert is_placeholder("c0ffee" + "deadbeef" + "1234567890abcdef" * 3 + "12")
    assert not is_placeholder(REAL2.removeprefix("sha256:"))


def test_split_repo_defaults() -> None:
    assert split_repo("postgres") == ("registry-1.docker.io", "library/postgres")
    assert split_repo("grafana/grafana") == ("registry-1.docker.io", "grafana/grafana")
    assert split_repo("ghcr.io/zaproxy/zaproxy") == ("ghcr.io", "zaproxy/zaproxy")


def test_check_fails_on_placeholder(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _tree(tmp_path, PLACEHOLDER)
    rc = main(["--check", "--root", str(tmp_path)], FakeRegistry({}))
    assert rc == 1
    assert "placeholder" in capsys.readouterr().err


def test_check_fails_on_unknown_digest(tmp_path: Path) -> None:
    _tree(tmp_path, REAL2)
    assert main(["--check", "--root", str(tmp_path)], FakeRegistry({})) == 1


def test_check_passes_on_known_digest(tmp_path: Path) -> None:
    _tree(tmp_path, REAL2)
    reg = FakeRegistry({("postgres", "16.4"): REAL2})
    assert main(["--check", "--root", str(tmp_path)], reg) == 0


def test_resolve_rewrites_placeholder_in_place(tmp_path: Path) -> None:
    f = _tree(tmp_path, PLACEHOLDER)
    reg = FakeRegistry({("postgres", "16.4"): REAL2})
    assert main(["--root", str(tmp_path)], reg) == 0
    assert f.read_text(encoding="utf-8").strip().endswith(f"postgres:16.4@{REAL2}")
    _ledger(tmp_path, PG)  # the refresh recipe: copy the resolved digest into PINS.md
    assert main(["--check", "--root", str(tmp_path)], reg) == 0


def test_resolve_leaves_unpublished_tag_untouched(tmp_path: Path) -> None:
    f = _tree(tmp_path, PLACEHOLDER)
    before = f.read_text(encoding="utf-8")
    assert main(["--root", str(tmp_path)], FakeRegistry({})) == 0
    assert f.read_text(encoding="utf-8") == before


def test_resolve_keeps_real_pin_even_if_tag_moved(tmp_path: Path) -> None:
    f = _tree(tmp_path, REAL2)
    reg = FakeRegistry({("postgres", "16.4"): REAL, ("postgres", "old"): REAL2})
    main(["--root", str(tmp_path)], reg)
    assert REAL2 in f.read_text(encoding="utf-8")


def test_ledger_matching_every_source_pin_passes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    f = _tree(tmp_path, REAL2)
    db2 = f"  db2:\n    image: postgres:16.4@{REAL2}\n"
    f.write_text(f.read_text(encoding="utf-8") + db2, encoding="utf-8")
    wf = tmp_path / ".github" / "workflows" / "ci.yml"
    wf.write_text(f"jobs:\n  x:\n    container: redis@{REAL}\n", encoding="utf-8")
    _ledger(tmp_path, PG, ("redis", "", REAL))
    assert _check(tmp_path, capsys) == (0, "")


@pytest.mark.parametrize(
    ("row", "kind"),
    [
        (("postgres", "16.4", REAL), "digest drift"),
        (("postgres", "16.5", REAL2), "tag drift"),
        (("postgres", "16.5", REAL), "tag and digest drift"),
    ],
)
def test_ledger_drifted_row_fails_naming_both_sides(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    row: tuple[str, str, str],
    kind: str,
) -> None:
    _tree(tmp_path, REAL2, row)
    rc, err = _check(tmp_path, capsys)
    assert rc == 1
    assert f"CI-IMG-007 {LEDGER}:5 {row[0]}:{row[1]}@{row[2]}: {kind};" in err
    assert f"; {COMPOSE}:3 pins postgres:16.4@{REAL2}" in err
    assert err.count("CI-IMG-") == 1


def test_ledger_source_pin_without_row_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _tree(tmp_path, REAL2)
    wf = tmp_path / ".github" / "workflows" / "ci.yml"
    wf.write_text(f"jobs:\n  x:\n    container: redis:7@{REAL}\n", encoding="utf-8")
    rc, err = _check(tmp_path, capsys)
    assert rc == 1
    assert (
        f"CI-IMG-007 .github/workflows/ci.yml:3 redis:7@{REAL}: no row in the table at {LEDGER}:3"
        in err
    )


def test_ledger_row_without_source_pin_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _tree(tmp_path, REAL2)
    _ledger(tmp_path, PG, ("redis", "7", REAL))
    rc, err = _check(tmp_path, capsys)
    assert rc == 1
    assert f"CI-IMG-007 {LEDGER}:6 redis:7@{REAL}: matches no source pin" in err


def test_ledger_duplicate_row_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _tree(tmp_path, REAL2)
    _ledger(tmp_path, PG, PG)
    rc, err = _check(tmp_path, capsys)
    assert rc == 1
    assert (
        f"CI-IMG-007 {LEDGER}:6 postgres:16.4@{REAL2}: duplicate of {LEDGER}:5" in err
    )


@pytest.mark.parametrize(
    ("line", "want"),
    [
        (
            "All 2 pins are verified.",
            f"{LEDGER}:7: says All 2 pins; the table at {LEDGER}:3 lists 1",
        ),
        ("Every pin is verified.", f"{LEDGER}: no 'All N pins' count line"),
    ],
)
def test_ledger_count_line_must_count_the_rows(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], line: str, want: str
) -> None:
    _tree(tmp_path, REAL2)
    f = tmp_path / LEDGER
    text = f.read_text(encoding="utf-8")
    f.write_text(text.replace("All 1 pins are verified.", line), encoding="utf-8")
    rc, err = _check(tmp_path, capsys)
    assert rc == 1
    assert f"CI-IMG-008 {want}" in err


@pytest.mark.parametrize(
    "mutate",
    [
        lambda s: s.replace("| Digest |", "| Hash |"),
        lambda s: s.replace(f"{REAL2} |", f"{REAL2[:-1]} |"),
        lambda s: s.replace("| Docker Hub |", "|"),
        lambda s: s.replace("| --- | --- | --- | --- |\n", ""),
        lambda s: "# Pins\n\nAll 0 pins are verified.\n",
        None,
    ],
    ids=[
        "no-digest-column",
        "short-digest",
        "short-row",
        "no-separator",
        "no-table",
        "no-file",
    ],
)
def test_ledger_unreadable_table_fails_closed(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    mutate: Callable[[str], str] | None,
) -> None:
    _tree(tmp_path, REAL2)
    f = tmp_path / LEDGER
    if mutate is None:
        f.unlink()
    else:
        f.write_text(mutate(f.read_text(encoding="utf-8")), encoding="utf-8")
    rc, err = _check(tmp_path, capsys)
    assert rc == 1
    assert f"CI-IMG-009 {LEDGER}" in err


def test_ledger_errors_print_before_the_registry_part_runs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _tree(tmp_path, REAL2, ("postgres", "16.4", REAL))
    with pytest.raises(urllib.error.URLError):
        main(["--check", "--root", str(tmp_path)], DownRegistry({}))
    assert f"CI-IMG-007 {LEDGER}:5 " in capsys.readouterr().err


def test_offline_check_compares_the_ledger_without_the_registry(tmp_path: Path) -> None:
    _tree(tmp_path, REAL2)
    argv = ["--check", "--offline", "--root", str(tmp_path)]
    assert main(argv, DownRegistry({})) == 0
    _ledger(tmp_path, ("postgres", "16.4", REAL))
    assert main(argv, DownRegistry({})) == 1


def test_offline_without_check_is_a_usage_error(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        main(["--offline", "--root", str(tmp_path)], DownRegistry({}))


def _http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("https://r/v2", code, "x", None, None)  # type: ignore[arg-type]  # fake hdrs


def _flaky(codes: list[int]) -> tuple[list[int], object]:
    calls: list[int] = []

    def fn() -> str:
        calls.append(1)
        if len(calls) <= len(codes):
            raise _http_error(codes[len(calls) - 1])
        return "ok"

    return calls, fn


@pytest.mark.parametrize("code", [429, 500, 503])
def test_with_retry_recovers_after_transient_error(code: int) -> None:
    calls, fn = _flaky([code, code])
    sleeps: list[float] = []
    assert with_retry(fn, sleep=sleeps.append) == "ok"  # type: ignore[arg-type]
    assert len(calls) == 3
    assert sleeps == [1.0, 2.0]


def test_with_retry_gives_up_after_three_attempts() -> None:
    calls, fn = _flaky([503, 503, 503, 503])
    with pytest.raises(urllib.error.HTTPError):
        with_retry(fn, sleep=lambda _s: None)  # type: ignore[arg-type]
    assert len(calls) == 3


def test_with_retry_does_not_retry_client_errors() -> None:
    calls, fn = _flaky([404])
    with pytest.raises(urllib.error.HTTPError):
        with_retry(fn, sleep=lambda _s: None)  # type: ignore[arg-type]
    assert len(calls) == 1
