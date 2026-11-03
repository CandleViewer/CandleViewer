"""E42-S03 (SCR-124): the web's view-as request guard keeps this module's lists (C-2.6, C-4.14).

While a session holds a view-as context, `apps/web/src/lib/http/viewAsGuard.ts` answers locally the
requests the server's guard would refuse, and passes the viewer's own operations and the protective
writes untouched. Its three lists must be `view_as_policy.py`'s, or a protective write the server
passes would be held back in the browser. Both lanes pin them: the web suite from its side
(`apps/web/test/lib/http/viewAsGuard.test.ts`) and this test from this one, so a change to the
policy alone, which runs no web lane, fails here until the client follows.

The client's literals are read as text and the read fails closed: a missing file, a missing literal,
one that is not wholly entries and comments, or one followed by more than its closing `;` fails,
naming both files. A commented-out entry does not count.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path

import pytest

from candleviewer.api.view_as_policy import OWN_OPERATIONS, PROTECTIVE_WRITES, REFUSED_READS

_GUARD = "apps/web/src/lib/http/viewAsGuard.ts"
_POLICY = "services/api/candleviewer/api/view_as_policy.py"
_REPO = Path(__file__).resolve().parents[5]

#: One `["METHOD", "/template"]` pair of the client's `OWN_OPERATIONS`.
_PAIR = re.compile(r'\[\s*"([A-Z]+)"\s*,\s*"([^"]+)"\s*\]')
#: One `operationId: ["METHOD", "/template"]` entry of a client record.
_BY_ID = re.compile(r'(\w+)\s*:\s*\[\s*"([A-Z]+)"\s*,\s*"([^"]+)"\s*\]')
_COMMENT = re.compile(r"/\*.*?\*/|//[^\n]*", re.S)
_CLOSERS = {"[": "]", "{": "}"}


class ClientListError(AssertionError):
    """The client's lists cannot be read in whole: the pin fails closed."""


def _guard_text(path: Path | None = None) -> str:
    try:
        return (path or _REPO / _GUARD).read_text(encoding="utf-8")
    except OSError as exc:
        raise ClientListError(f"{_POLICY}'s lists are pinned to {_GUARD}, unread: {exc}") from exc


def _literal(text: str, name: str, opener: str) -> str:
    """The body of `export const NAME…= [ … ];` (or `{ … };`), and nothing else after it."""
    head = re.search(rf"^export const {name}\b[^=\n]*= \{opener}", text, re.M)
    if head is None:
        raise ClientListError(f"{_GUARD} has no {name} literal for {_POLICY} to pin")
    start, depth = head.end() - 1, 0
    for i in range(start, len(text)):
        depth += {opener: 1, _CLOSERS[opener]: -1}.get(text[i], 0)
        if depth == 0:
            if not re.match(r"\s*;[ \t]*(?://[^\n]*)?(?:\n|$)", text[i + 1 :]):
                raise ClientListError(f"{_GUARD}'s {name} is followed by more than its ';'")
            return text[start + 1 : i]
    raise ClientListError(f"{_GUARD}'s {name} literal never closes")


def _entries(body: str, entry: re.Pattern[str], name: str) -> list[tuple[str, ...]]:
    """Every entry in `body` once comments are gone, failing unless entries make up the whole."""
    code = _COMMENT.sub("", body)
    found = [match.groups() for match in entry.finditer(code)]
    rest = re.sub(r"[\s,]", "", entry.sub("", code))
    if not found or rest:
        raise ClientListError(f"{_GUARD}'s {name} could not be read in whole: {rest!r}")
    return found


def _own(text: str) -> list[str]:
    body = _literal(text, "OWN_OPERATIONS", "[")
    return [f"{method} {path}" for method, path in _entries(body, _PAIR, "OWN_OPERATIONS")]


def _by_id(text: str, name: str) -> dict[str, tuple[str, str]]:
    found = _entries(_literal(text, name, "{"), _BY_ID, name)
    pairs = {op_id: (method, path) for op_id, method, path in found}
    if len(pairs) != len(found):
        raise ClientListError(f"{_GUARD}'s {name} names an operation twice")
    return pairs


def _server(policy: Mapping[str, tuple[tuple[str, str], str]]) -> dict[str, tuple[str, str]]:
    return {op_id: operation for op_id, (operation, _ticket) in policy.items()}


def test_web_guard_own_operations_are_the_policy_pairs() -> None:
    client = _own(_guard_text())
    assert len(set(client)) == len(client), f"{_GUARD} lists an own operation twice"
    server = sorted(f"{method} {path}" for method, path in OWN_OPERATIONS)
    assert sorted(client) == server, f"{_GUARD} OWN_OPERATIONS vs {_POLICY}"


def test_web_guard_protective_writes_are_the_policy_operations() -> None:
    client = _by_id(_guard_text(), "PROTECTIVE_WRITES")
    assert client == _server(PROTECTIVE_WRITES), f"{_GUARD} PROTECTIVE_WRITES vs {_POLICY}"


def test_web_guard_refused_reads_are_the_policy_operations() -> None:
    client = _by_id(_guard_text(), "REFUSED_READS")
    assert client == _server(REFUSED_READS), f"{_GUARD} REFUSED_READS vs {_POLICY}"


_OWN_TEXT = 'export const OWN_OPERATIONS: readonly X[] = [\n  ["POST", "/auth/lock"],\n];\n'


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("export const OTHER = [];\n", "has no OWN_OPERATIONS"),
        ('export const OWN_OPERATIONS = [\n  ["POST", "/auth/lock"],\n', "never closes"),
        (_OWN_TEXT.replace("];", "].concat(MORE);"), "more than its"),
        (_OWN_TEXT.replace('["POST"', '...MORE, ["POST"'), "could not be read in whole"),
        (_OWN_TEXT.replace('  ["POST", "/auth/lock"],', '  // ["POST", "/auth/lock"],'), "whole"),
    ],
)
def test_web_guard_read_unreadable_literal_fails_closed(text: str, message: str) -> None:
    with pytest.raises(ClientListError, match=message):
        _own(text)


def test_web_guard_read_missing_file_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(ClientListError, match="unread"):
        _guard_text(tmp_path / "viewAsGuard.ts")


def test_web_guard_read_commented_entry_does_not_count() -> None:
    text = _OWN_TEXT.replace("];", '  // ["POST", "/auth/unlock"],\n];')
    assert _own(text) == ["POST /auth/lock"]
