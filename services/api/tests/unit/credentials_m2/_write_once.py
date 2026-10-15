"""The `api_keys` write-once vocabulary (#2336): the frozen columns and a reader for the SQL that
writes them.

`PROTECTED_COLUMNS` become write-once under the Security sign-off on #835 (deviation 2): after
INSERT a credential id is never re-sealed, so each ciphertext stays bound to one (credential, key
version) pair. They are the sealed columns, the identity columns and the cipher id, plus
`key_id_last4`: `store()` derives that display tail from the plaintext key id at INSERT, so a
changed tail would mean a re-sealed key id.

`writes_to` reads which statements of an SQL string write one table. It tokenises (comments and
literals skipped, quoted identifiers unquoted, words lower-cased) instead of matching regexes on the
raw text. A SET list ends at the first top-level `FROM`, `WHERE`, `RETURNING` (`IS DISTINCT FROM`
excepted) or `;`, and an assignment at the next top-level comma; `(...)` and `[...]` nest. So
`coalesce(a, b)`, `ARRAY[a, b]`, a subquery, a CASE expression (its WHEN, THEN and ELSE are not
clause words) and a literal cannot end a SET list early, hide a later assignment or invent a target.
The reader covers the PostgreSQL subset this codebase writes and is not hardened against deliberate
obfuscation. It raises `ValueError`, so a guard built on it fails closed, on a string it cannot
read: an unterminated quote, a `$` outside a literal (a dollar-quoted body is not read: reading it
as code lets a literal fake a clause word, skipping it as text lets a DO block hide a write) and an
`UPDATE` of the table whose SET list it cannot find.
"""

from __future__ import annotations

import re
from typing import Final, NamedTuple

PROTECTED_COLUMNS: Final = frozenset(
    {
        "id",
        "exchange_account_id",
        "key_id_enc",
        "key_id_last4",
        "secret_enc",
        "enc_nonce",
        "enc_alg",
    }
)
#: Parameter names under which a port method would carry sealed bytes or the cipher identity.
CIPHERTEXT_PARAMS: Final = frozenset({"key_id_enc", "secret_enc", "enc_nonce", "enc_alg"})

_SET_END: Final = frozenset({"from", "where", "returning"})
#: A single character the tokenizer cannot place, and why that makes the string unreadable.
_UNREADABLE: Final = {
    "'": "unterminated quote in SQL",
    '"': "unterminated quote in SQL",
    "$": "dollar quoting not supported",
}
_TOKEN: Final = re.compile(
    "|".join(
        [
            r"(?P<skip>\s+|--[^\n]*|/\*.*?\*/)",  # whitespace and comments
            r"(?P<s>[eE]'(?:[^'\\]|\\.|'')*'|'(?:[^']|'')*')",  # string literal
            r'(?P<q>"(?:[^"]|"")*")',  # quoted identifier
            r"(?P<w>[A-Za-z_][\w$]*)",  # keyword or bare identifier
            r"(?P<p>.)",  # any other single character
        ]
    ),
    re.DOTALL,
)


class Tok(NamedTuple):
    kind: str  # "w" bare word, "q" quoted identifier, "s" string literal, "p" one other character
    text: str  # lower-cased for "w" and "q"


class SqlWrite(NamedTuple):
    kind: str  # "insert", "update", "upsert" (INSERT ... ON CONFLICT DO UPDATE) or "merge"
    targets: frozenset[str]  # columns assigned by the SET list of an "update" or "upsert"


def _tokens(sql: str) -> list[Tok]:
    toks: list[Tok] = []
    for m in _TOKEN.finditer(sql):
        kind, text = m.lastgroup or "p", m.group()
        if kind == "skip":
            continue
        if kind == "p" and text in _UNREADABLE:
            raise ValueError(_UNREADABLE[text])
        if kind == "q":
            text = text[1:-1].replace('""', '"')
        toks.append(Tok(kind, text.lower() if kind in ("w", "q") else text))
    return toks


def _word(toks: list[Tok], i: int) -> str:
    """The lower-cased bare word at `i`; empty when `i` is out of range or not a bare word."""
    return toks[i].text if 0 <= i < len(toks) and toks[i].kind == "w" else ""


_OPEN: Final = (Tok("p", "("), Tok("p", "["))
_CLOSE: Final = (Tok("p", ")"), Tok("p", "]"))


def _nesting(tok: Tok) -> int:
    """+1 for `(` or `[`, -1 for `)` or `]`, else 0."""
    return (tok in _OPEN) - (tok in _CLOSE)


def _relation(toks: list[Tok], i: int) -> tuple[str, int]:
    """The table name at `i` (last part of `schema.table`) and the index just after it."""
    if _word(toks, i) == "only":
        i += 1
    name, i = (toks[i].text if i < len(toks) else ""), i + 1
    while i + 1 < len(toks) and toks[i] == Tok("p", "."):
        name, i = toks[i + 1].text, i + 2
    return name, i


def _set_targets(toks: list[Tok], i: int) -> frozenset[str]:
    """Columns assigned by the SET list at `i`: the names left of each top-level `=`, outside any
    `[...]` subscript. A `(...)` or `[...]` nests, so a comma or clause word inside an expression
    (`coalesce(a, b)`, `ARRAY[a, b]`, a subquery) never ends or starts an assignment."""
    targets: set[str] = set()
    depth, subscript, assigned = 0, 0, False  # `assigned`: this assignment's `=` has been passed
    for k in range(i, len(toks)):
        tok = toks[k]
        depth += _nesting(tok)
        subscript += (tok == Tok("p", "[")) - (tok == Tok("p", "]"))
        if depth < 0 or (depth == 0 and tok == Tok("p", ";")):
            break  # the statement ends, or a CTE closes around it
        if depth == 0 and _word(toks, k) in _SET_END and _word(toks, k - 1) != "distinct":
            break
        if depth == 0 and tok == Tok("p", ","):
            assigned = False
        elif depth == 0 and tok == Tok("p", "="):
            assigned = True
        elif not assigned and not subscript and tok.kind in ("w", "q"):
            targets.add(tok.text)
    return frozenset(targets)


def writes_to(sql: str, table: str = "api_keys") -> list[SqlWrite]:
    """Every statement in `sql` that inserts into, updates, upserts into or merges into `table`.
    Raises `ValueError` for SQL it cannot read, and for an UPDATE of `table` with no SET list."""
    toks, writes, inserted = _tokens(sql), [], ""
    for i in range(len(toks)):
        word = _word(toks, i)
        if word in ("insert", "merge") and _word(toks, i + 1) == "into":
            name, _ = _relation(toks, i + 2)
            inserted = name if word == "insert" else inserted
            if name == table:
                writes.append(SqlWrite(word, frozenset()))
        elif word == "update" and _word(toks, i - 1) == "do":
            if inserted == table and _word(toks, i + 1) == "set":
                writes.append(SqlWrite("upsert", _set_targets(toks, i + 2)))
        elif word == "update" and _word(toks, i - 1) != "then":  # `then` is MERGE, noted above
            name, j = _relation(toks, i + 1)
            if toks[j : j + 1] == [Tok("p", "*")]:
                j += 1  # `table *`: the table and its children
            if _word(toks, j) == "as":
                j += 1
            if j < len(toks) and toks[j].kind in ("w", "q") and _word(toks, j) != "set":
                j += 1  # table alias
            if name == table:
                if _word(toks, j) != "set":
                    raise ValueError(f"no SET list found for the {table} UPDATE")
                writes.append(SqlWrite("update", _set_targets(toks, j + 1)))
    return writes
