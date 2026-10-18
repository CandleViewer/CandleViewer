"""`validate.py --check` (#3362): validate.py is the backlog twins' formatter, and CI checks it.
Runs the real validate.py on a tmp copy of the real twins; the plan docs are only read."""

import importlib.util
import json
import re
import shutil
from collections.abc import Callable
from pathlib import Path

import pytest

_BACKLOG = Path(__file__).resolve().parents[2] / "docs/plan/backlog"
_ARRAY = re.compile(r'^( *)("[^"\n]*": )\[\n((?:\1  "[^"\n]*",?\n)+)\1\](,?)$', re.M)


def _prettier_e17(backlog: Path) -> None:
    """Prettier's layout (printWidth 100: a string array that fits goes on one line, plus a final
    newline); byte-identical to prettier 3.9.9 on all 50 twins when written."""

    def fold(m: re.Match[str]) -> str:
        line = f"{m[1]}{m[2]}[{', '.join(s.strip(' ,') for s in m[3].splitlines())}]{m[4]}"
        return line if len(line) <= 100 else m[0]

    twin = backlog / "E17.json"
    twin.write_text(_ARRAY.sub(fold, twin.read_text(encoding="utf-8")) + "\n", encoding="utf-8")


def _edit_e17(backlog: Path) -> None:
    """A one-string twin edit the AGENTS.md §3a way: load, modify, json.dump(indent=2)."""
    data = json.loads((backlog / "E17.json").read_text(encoding="utf-8"))
    data[0]["title"] += " (edited)"
    with (backlog / "E17.json").open("w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)


def _validate(backlog: Path, *argv: str) -> int:
    spec = importlib.util.spec_from_file_location("validate", _BACKLOG / "_tools/validate.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)  # fresh per run: empty global error lists
    spec.loader.exec_module(mod)
    mod.BACKLOG = str(backlog)
    before = {p.name: p.read_bytes() for p in backlog.iterdir()}
    code: int = mod.main(list(argv))
    assert "--check" not in argv or before == {p.name: p.read_bytes() for p in backlog.iterdir()}
    return code


@pytest.fixture
def backlog(tmp_path: Path) -> Path:
    for twin in [*_BACKLOG.glob("E[0-9][0-9].json"), _BACKLOG / "all-tickets.json"]:
        shutil.copyfile(twin, tmp_path / twin.name)
    return tmp_path


def test_validate_check_python_edit_then_validate_passes(
    backlog: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _edit_e17(backlog)
    codes = (_validate(backlog), _validate(backlog, "--check"))  # 1st rewrites all-tickets.json
    assert "TWIN-FORMAT" not in capsys.readouterr().out  # the formatter contract, checked first
    assert codes == (0, 0)  # any other error is backlog health, not the twin layout


@pytest.mark.parametrize(("edit", "twin"), [(_prettier_e17, "E17"), (_edit_e17, "all-tickets")])
def test_validate_check_prettier_or_stale_twin_fails_naming_validate_py(
    backlog: Path, capsys: pytest.CaptureFixture[str], edit: Callable[[Path], None], twin: str
) -> None:
    edit(backlog)
    assert _validate(backlog, "--check") == 1
    out = capsys.readouterr().out
    assert f"TWIN-FORMAT {twin}.json: " in out and "validate.py is the formatter" in out
