"""#2188 S3d (S3a lens SEC-1): no env is defaulted in the recorder's session path, and its startup,
gap and counter writes reach only their own env's sessions (C-2.11, #2726's class)."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path
from types import ModuleType

import pytest

from candleviewer.recorder import policy, sessions, writer
from candleviewer.recorder.sessions import SessionConfig, SessionManager
from candleviewer.recorder.writer import writer_config_from_settings
from candleviewer.settings import Environment, Settings
from candleviewer.storage.repositories import recorder_sqlalchemy
from tests.unit.recorder._fakes import FakeAudit
from tests.unit.recorder._session_fakes import DEMO, LIVE, MemRecorderStore, UsClock
from tests.unit.recorder._writer_helpers import make_writer, trade
from tests.unit.recorder.test_sessions import T0, _crashed


def _defaulted_envs(tree: ast.AST) -> list[int]:
    """The lines of each `env` parameter or class field that has a default: the AST sees the
    private callables, the Protocol members and the dataclass fields too."""
    found: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda):
            a = node.args
            positional = [*a.posonlyargs, *a.args]
            defaulted = positional[len(positional) - len(a.defaults) :]
            defaulted += [k for k, d in zip(a.kwonlyargs, a.kw_defaults, strict=True) if d]
            found += [arg.lineno for arg in defaulted if arg.arg == "env"]
        elif isinstance(node, ast.AnnAssign) and getattr(node.target, "id", "") == "env":
            found += [] if node.value is None else [node.lineno]
    return found


def test_the_scan_finds_a_default_env_to_begin_with() -> None:
    seeded = "def f(a, env=1): ...\ndef g(*, env=1): ...\nclass C:\n env: int = 1"
    assert len(_defaulted_envs(ast.parse(seeded))) == 3
    assert _defaulted_envs(ast.parse("def f(env, a=1): ...\nclass C:\n env: int")) == []


@pytest.mark.parametrize("module", [sessions, policy, recorder_sqlalchemy, writer])
def test_no_env_in_the_session_path_has_a_default(module: ModuleType) -> None:
    assert _defaulted_envs(ast.parse(Path(inspect.getfile(module)).read_text())) == []


def test_a_session_config_cannot_be_built_without_an_env() -> None:
    with pytest.raises(TypeError, match="env"):
        SessionConfig()  # type: ignore[call-arg]  # the default is gone


def test_a_manager_cannot_be_built_without_a_config() -> None:
    with pytest.raises(TypeError, match="config"):
        SessionManager(MemRecorderStore(), now_us=UsClock(T0), audit=FakeAudit())  # type: ignore[call-arg]  # likewise


def test_a_manager_built_with_a_config_of_none_is_refused_naming_the_reason() -> None:
    """Like `audit=None`: refused when built, not later at the first `self._cfg.env`."""
    with pytest.raises(ValueError, match=r"needs a config.*C-2\.11"):
        SessionManager(MemRecorderStore(), now_us=UsClock(T0), audit=FakeAudit(), config=None)  # type: ignore[arg-type]  # a runtime None


@pytest.mark.parametrize(("mine", "other"), [(LIVE, DEMO), (DEMO, LIVE)])
async def test_a_startup_closes_its_own_envs_open_sessions_and_leaves_the_others(
    mine: SessionConfig, other: SessionConfig
) -> None:
    """SEC-1: crash recovery read the open sessions of every env, so a demo process closed and
    audited a live one, and gapped it for an outage that never happened."""
    store, audit = MemRecorderStore(), FakeAudit()
    await _crashed(store, mine)
    await _crashed(store, other)  # the same symbol, recorded in the other env too
    restart = SessionManager(store, now_us=UsClock(T0 + 9), audit=audit, config=mine)
    assert await restart.recover_on_startup(T0 + 9) == 1
    assert {s["env"]: s["ended_at"] is not None for s in store.sessions.values()} == {
        mine.env: True,
        other.env: False,
    }
    assert audit.envs() == [("recorder.stop", mine.env)]
    own = next(sid for sid, s in store.sessions.items() if s["env"] == mine.env)
    assert {g["session_id"] for g in store.gaps} == {own}


@pytest.mark.parametrize("environment", list(Environment))
def test_the_production_writer_config_takes_the_settings_env(environment: Environment) -> None:
    settings = Settings().model_copy(update={"environment": environment})  # only the env is read
    assert writer_config_from_settings(settings).env == environment.value


async def test_the_writer_names_its_env_on_its_gap_and_counter_writes(tmp_path: Path) -> None:
    w, _sink, store, *_ = await make_writer(tmp_path, env="demo")
    await w.on_trade(trade(1))  # a counter delta
    w._gaps[("BTCUSDT", "trades")] = [T0, T0 + 1_000]  # a dropped window
    await w.flush_gaps()
    await w.flush_counters()
    assert store.envs == ["demo", "demo"]  # one write each
