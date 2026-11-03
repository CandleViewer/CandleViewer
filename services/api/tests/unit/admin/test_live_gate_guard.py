"""E42-Q06 (C7): the live gate's second key, guarded from the server side.

A live order needs two keys at once: the process setting `CV_TRADING_LIVE_ENABLED` and the
`trading.live_enabled` flag (`TradingSwitchesBinding`, rulings Q4 and Q6). The flag's API path is
the one stated exception until E44-T04 binds its evidence (the E42 deferred-Must record), so this
file pins the other key from E42's side: it is off unless the environment turns it on, only the
composition root names it, the OMS's switches take it as their first key, and they refuse a live
order while either key is off. It also pins the modules whose code names the flag's key, which
backs the `cv-admin-no-live-enable-py` rule: a key held under another name is out of a pattern's
sight, so a new module naming it needs this list, and Security's review, to change. Both scans read
code that spells a name, with its constant strings folded (a concatenation, an f-string, a join,
bytes). The static checks cover code that spells the key or the setting, literally or in the
folded forms listed. Code that does not spell them is outside them: a key or name computed at run
time, or the flag's view written through the runtime. There, the guarantee is C7's second key: the
setting is off by default and named only by the composition root, so the flag alone admits no live
order. The flag's own class (no grace, a fresh `live_enablement` step-up) is pinned by
`test_dangerous_route_registry.py`.
"""

from __future__ import annotations

import ast
import re
import warnings
from pathlib import Path
from uuid import UUID

import pytest

from candleviewer.admin.flags.catalogue import FLAGS
from candleviewer.admin.flags.registry import LIVE_ENABLED, Category
from candleviewer.domain.order_entry import OrderEntryRefusal
from candleviewer.domain.primitives import AccountId
from candleviewer.oms.errors import TradingDisabled
from candleviewer.oms_wiring import InterimKillSwitch, TradingSwitchesBinding
from candleviewer.settings import Settings

PACKAGE = Path(__file__).resolve().parents[3] / "candleviewer"
#: The modules naming the setting, in any case and anywhere in the text: the setting itself and the
#: composition root that hands it to the switches. No other module reads or writes it, so no
#: request can turn the second key on.
SETTING_MODULES = ["app.py", "oms_wiring.py", "settings.py", "trade_groups_wiring.py"]
SETTING = re.compile(r"trading_live_enabled", re.IGNORECASE)
#: The modules whose code names the flag's key: the catalogue, its package, the flag wiring and
#: the generated API models (a field's description).
KEY_MODULES = [
    "admin/flags/__init__.py", "admin/flags/catalogue.py", "admin/flags/registry.py",
    "api/_generated/openapi_models.py", "flags_wiring.py",
]  # fmt: skip
#: The key's last part as a word in any case, which also meets the constant's name `LIVE_ENABLED`;
#: the setting's name (`trading_live_enabled`) and other words ending in it are not the key.
KEY = re.compile(r"(?<![a-z0-9_])live_enabled", re.IGNORECASE)
#: What builds the switches or the readiness the OMS and the trade groups read (the two keys).
BUILDERS = frozenset({"TradingSwitchesBinding", "GateReadiness"})
ACCOUNT = AccountId(UUID(int=7))


def _folded(node: ast.AST) -> str | None:
    """The text of a constant string expression: a literal, bytes, a concatenation, an f-string
    of constants or a constant separator's join of constants; None for anything else."""
    match node:
        case ast.Constant(value=str(text)):
            return text
        case ast.Constant(value=bytes(data)):
            return data.decode("utf-8", "replace")
        case ast.BinOp(left=left, op=ast.Add(), right=right):
            parts = [left, right]
        case ast.JoinedStr(values=values):
            parts = list(values)
        case ast.FormattedValue(value=value):
            parts = [value]
        case ast.Call(
            func=ast.Attribute(value=glue, attr="join"),
            args=[ast.Tuple(elts=items) | ast.List(elts=items)],
        ):
            parts = [part for item in items for part in (glue, item)][1:]
        case _:
            return None
    texts = [_folded(part) for part in parts]
    return None if None in texts else "".join(text or "" for text in texts)


def _sources(package: Path) -> dict[str, tuple[str, list[ast.AST], list[str]]]:
    """Each module of `package`, relative to it: its text, its nodes and its constant string
    expressions that are code, not prose (a bare string statement, a docstring, is left out)."""
    found: dict[str, tuple[str, list[ast.AST], list[str]]] = {}
    with warnings.catch_warnings():  # a module's own invalid escape is not this scan's concern
        warnings.simplefilter("ignore", SyntaxWarning)
        for path in package.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            nodes = list(ast.walk(ast.parse(text)))
            prose = {
                id(node.value)
                for node in nodes
                if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
            }
            strings = [_folded(node) for node in nodes if id(node) not in prose]
            found[path.relative_to(package).as_posix()] = (
                text, nodes, [string for string in strings if string is not None],
            )  # fmt: skip
    return found


def setting_readers(package: Path) -> list[str]:
    """Each module of `package` that names the setting in any case, in its text or in a constant
    string its code folds to, relative to `package`."""
    return sorted(
        name
        for name, (text, _, strings) in _sources(package).items()
        if SETTING.search(text) or any(map(SETTING.search, strings))
    )


def _names_the_key(node: ast.AST) -> bool:
    """The constant by name, through a module or in an import."""
    match node:
        case ast.Name(id=name) | ast.Attribute(attr=name) | ast.alias(name=name):
            return name == "LIVE_ENABLED"
    return False


def key_namers(package: Path) -> list[str]:
    """Each module of `package` whose code names the flag's key, by the constant or in a constant
    string that folds to a text holding `live_enabled` as a word, relative to `package`."""
    return sorted(
        name
        for name, (_, nodes, strings) in _sources(package).items()
        if any(map(_names_the_key, nodes)) or any(map(KEY.search, strings))
    )


def test_the_setting_is_off_unless_the_environment_turns_it_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("CV_TRADING_LIVE_ENABLED", raising=False)
    monkeypatch.chdir(tmp_path)  # and no `.env` to read it from
    assert Settings.model_fields["trading_live_enabled"].default is False
    assert Settings().trading_live_enabled is False


def test_the_catalogue_declares_the_live_flag_off_and_evidence_bound() -> None:
    (spec,) = [s for s in FLAGS if s.key == LIVE_ENABLED == "trading.live_enabled"]
    assert (spec.default, spec.fail_closed_value, spec.requires_evidence) == (False, False, True)
    assert spec.gates == Category.LIVE_GATE and not spec.overridable


def test_only_the_composition_root_names_the_setting() -> None:
    assert setting_readers(PACKAGE) == SETTING_MODULES


def test_the_scan_names_each_module_that_reads_or_writes_the_setting(tmp_path: Path) -> None:
    """The positive control: a handler's read, a socket's and an auth module's, an admin
    module's environment write, a top-level wiring module and three split spellings are each
    named."""
    for tree in ("api/routes", "ws", "auth", "admin"):
        (tmp_path / tree).mkdir(parents=True)
    (tmp_path / "api" / "routes" / "live.py").write_text("on = cfg.trading_live_enabled\n", "utf-8")
    (tmp_path / "ws" / "live.py").write_text("on = cfg.trading_live_enabled\n", "utf-8")
    (tmp_path / "auth" / "live.py").write_text("on = cfg.trading_live_enabled\n", "utf-8")
    (tmp_path / "admin" / "env.py").write_text('environ["CV_TRADING_LIVE_ENABLED"] = "1"', "utf-8")
    (tmp_path / "admin_wiring.py").write_text("on = cfg.trading_live_enabled\n", "utf-8")
    (tmp_path / "api" / "split.py").write_text('setattr(c, "trading_live_" "enabled", 1)', "utf-8")
    (tmp_path / "ws" / "env.py").write_text('env["CV_TRADING_" + "LIVE_ENABLED"] = "1"', "utf-8")
    (tmp_path / "auth" / "dotenv.py").write_text("w(f\"CV_{'TRADING_LIVE'}_ENABLED=1\")", "utf-8")
    (tmp_path / "quiet.py").write_text("on = cfg.trading_enabled\n", "utf-8")
    assert setting_readers(tmp_path) == [
        "admin/env.py", "admin_wiring.py", "api/routes/live.py", "api/split.py", "auth/dotenv.py",
        "auth/live.py", "ws/env.py", "ws/live.py",
    ]  # fmt: skip


def test_only_the_flag_catalogue_and_its_wiring_name_the_flags_key() -> None:
    assert key_namers(PACKAGE) == KEY_MODULES


def test_the_key_scan_names_each_spelling_but_not_prose(tmp_path: Path) -> None:
    """The positive control: an aliased import, a qualified constant in a container, the
    constant's name as a string and the key folded from a split literal, bytes, an f-string or a
    join are each named; a docstring, a comment, the setting and other words ending in the key's
    last part are not."""
    files = {
        "alias.py": "from candleviewer.admin.flags import LIVE_ENABLED as GATE\n",
        "box.py": "KEYS = (registry.LIVE_ENABLED,)\n",
        "by_name.py": 'KEY = getattr(registry, "LIVE_" "ENABLED")\n',
        "split.py": 'put("trading.live" + "_enabled", on)\n',
        "bytes.py": 'KEY = b"trading.live_enabled".decode()\n',
        "fstring.py": "KEY = f\"trading.{'live'}_enabled\"\n",
        "join.py": 'KEY = ".".join(("trading", "_".join(["live", "enabled"])))\n',
        "prose.py": '"""The `trading.live_enabled` flag."""\n# trading.live_enabled\n',
        "others.py": 'ON = ("CV_TRADING_LIVE_ENABLED", "audit_live_enabled")\n',
    }
    for name, text in files.items():
        (tmp_path / name).write_text(text, "utf-8")
    assert key_namers(tmp_path) == [
        "alias.py", "box.py", "by_name.py", "bytes.py", "fstring.py", "join.py", "split.py",
    ]  # fmt: skip


def _builder_keys(package: Path) -> list[tuple[str, ast.expr | None]]:
    """Each call building the switches or the readiness, with what it passes as `live_enabled`."""
    found: list[tuple[str, ast.expr | None]] = []
    for path in sorted(package.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        if not any(f"{name}(" in text for name in BUILDERS):
            continue
        for node in ast.walk(ast.parse(text)):
            func = node.func if isinstance(node, ast.Call) else None
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
            if isinstance(node, ast.Call) and name in BUILDERS:
                keys = [k.value for k in node.keywords if k.arg == "live_enabled"]
                found.append((path.name, keys[0] if keys else None))
    return found


def test_every_builder_takes_the_setting_as_its_first_key() -> None:
    """The composition root passes the setting, never a constant or the flag, as `live_enabled`
    wherever it builds the OMS's switches or the trade groups' readiness."""
    found = _builder_keys(PACKAGE)
    assert {path for path, _ in found} >= {"oms_wiring.py", "app.py"}
    for path, key in found:
        assert isinstance(key, ast.Attribute) and key.attr == "trading_live_enabled", path


class _Admits:
    """The order-entry gate admitting every account, so only the live keys can refuse."""

    def refusal(self, account_id: UUID) -> OrderEntryRefusal | None:
        return None


def _switches(*, setting: bool, flag: bool) -> TradingSwitchesBinding:
    return TradingSwitchesBinding(
        live_enabled=setting, live_flag=lambda: flag, kill_switch=InterimKillSwitch(),
        gate=_Admits(), fenced=lambda: False,
    )  # fmt: skip


@pytest.mark.parametrize(("setting", "flag"), [(False, True), (True, False)])
def test_a_live_order_is_refused_while_either_key_is_off(setting: bool, flag: bool) -> None:
    """The second key: the flag on is not enough while the setting is off, nor the reverse."""
    refused = _switches(setting=setting, flag=flag).refusal(ACCOUNT, "live")
    assert type(refused) is TradingDisabled


def test_a_live_order_passes_the_keys_only_with_both_on() -> None:
    """The control for the case above: with both keys on, nothing else here refuses."""
    assert _switches(setting=True, flag=True).refusal(ACCOUNT, "live") is None
