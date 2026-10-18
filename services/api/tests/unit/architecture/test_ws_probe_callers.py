"""SR-E27-05: the scheduled self-check never opens a private WS (#836 slice 2b5).

Only `testApiKey` (slice 2b6) may run the adapter's private-WS `auth` probe. Its module and the
adapter method that runs it share one name, `key_ws_probe`, and the probe's class is `KeyWsProbe`,
so a text scan finds every import, call, attribute or string that names either, and a second
probe built elsewhere with a budget of its own. Besides the adapter, only the test's wiring names
it, as the flow's WebSocket port; the self-check's own modules, and the pipeline it runs, may never
be added.
"""

from __future__ import annotations

import re
from pathlib import Path

import candleviewer
import cvdev

ROOTS = (Path(candleviewer.__file__).resolve().parent, Path(cvdev.__file__).resolve().parent)
NAME = re.compile(r"\b(key_ws_probe|KeyWsProbe)\b")
#: Where the probe may be named: its module, the adapter that holds it and `testApiKey`'s wiring.
ALLOWED = frozenset(
    {
        "candleviewer/exchange/bybit/key_ws_probe.py",
        "candleviewer/exchange/bybit/service.py",
        "candleviewer/key_test_wiring.py",
    }
)
#: The scheduled self-check: the job, the verification pipeline it runs, its wiring and the
#: module that starts it.
SELF_CHECK = frozenset(
    {
        "candleviewer/accounts/selfcheck.py",
        "candleviewer/accounts/verification.py",
        "candleviewer/accounts/service.py",
        "candleviewer/key_selfcheck_wiring.py",
    }
)


def _naming() -> set[str]:
    return {
        path.relative_to(root.parent).as_posix()
        for root in ROOTS
        for path in root.rglob("*.py")
        if NAME.search(path.read_text(encoding="utf-8"))
    }


def test_only_the_adapter_names_the_private_ws_probe() -> None:
    """The scan sees the adapter's own use, and nothing outside `ALLOWED`."""
    found = _naming()
    assert "candleviewer/exchange/bybit/service.py" in found
    assert found <= ALLOWED


def test_the_scheduled_self_check_may_never_be_allowed_to_name_it() -> None:
    assert not ALLOWED & SELF_CHECK
    assert all((ROOTS[0].parent / path).is_file() for path in SELF_CHECK)  # real files
