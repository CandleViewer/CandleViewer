"""The shared M10 engine builder hides bound parameters from every exception it produces.

`DBAPIError.__str__` renders `[parameters: ...]` unless the engine was built with
`hide_parameters=True`, and bound values can be P1 columns such as `replay_sessions.bookmarks`
(21 §12). Every relational repository's engine comes from `_build_engine`, so this one flag keeps
those values out of any rendered exception chain (C-12.6).
"""

from __future__ import annotations

import traceback

from sqlalchemy.exc import DBAPIError

from candleviewer.storage.repositories.relational_sqlalchemy import _build_engine

_DSN = "postgresql+asyncpg://localhost/cv"  # no credentials; building an engine never connects
_NOTE = "SECRET-NOTE"  # stands in for a P1 `bookmarks` note


def test_the_shared_engine_builder_hides_bound_parameters() -> None:
    assert _build_engine(_DSN).sync_engine.hide_parameters is True


def test_a_database_error_built_with_the_engine_flag_renders_no_parameters() -> None:
    hide = _build_engine(_DSN).sync_engine.hide_parameters
    statement, params = "INSERT INTO t (bookmarks) VALUES ($1)", {"bookmarks": [{"n": _NOTE}]}
    shown = DBAPIError(statement, params, Exception("boom"))
    hidden = DBAPIError(statement, params, Exception("boom"), hide_parameters=hide)
    assert _NOTE in "".join(traceback.format_exception(shown))  # control: the default leaks
    assert _NOTE not in "".join(traceback.format_exception(hidden))
