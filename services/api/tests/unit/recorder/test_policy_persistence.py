"""#2188 S2b: the recording policy writes `recorded_symbols` first and memory second."""

from __future__ import annotations

import inspect

from candleviewer.recorder.policy import RecordedStore
from candleviewer.storage.repositories.recorder_sqlalchemy import SqlAlchemyRecorderRepository


def test_the_repository_has_every_port_method_with_its_parameters() -> None:
    for name, port_method in vars(RecordedStore).items():
        if callable(port_method) and not name.startswith("_"):
            ours = list(inspect.signature(port_method).parameters)
            theirs = list(inspect.signature(getattr(SqlAlchemyRecorderRepository, name)).parameters)
            assert ours == theirs, name  # M10's repository is what gets injected
