#!/usr/bin/env python3
"""E03-T10: Alembic migration job checks — single-head, drift, expand/contract
lint, and `IF NOT EXISTS` ban.

`docs/plan/21-database-schema.md` §9 ("Single linear history on `main`", no
`IF NOT EXISTS` in migrations — Alembic owns state) and ADR-0013 rule 9
("Migrations ... must be backward-compatible for one release (expand/
contract), so a rollback never requires a down-migration") are the two
normative sources; this module is the mechanical enforcement of both plus
the security-sensitive-table carve-out from `02-definition-of-ready-done.md`
§4.1 (envelope encryption preserved on `api_keys`-touching migrations).

Error codes (ticket "Technical notes / design"):
    CI-MIG-001  multiple Alembic heads
    CI-MIG-002  schema drift between `models.py` and the migration chain
    CI-MIG-003  destructive operation without a `# cv:contract-phase:` annotation,
                or any statement or operation that mutates an append-only audit
                table or neuters its guards (C-5.7; `check_audit_table_integrity`)
    CI-MIG-004  upgrade-path (previous release) failure
    CI-MIG-005  `IF NOT EXISTS` used in a migration file
    CI-MIG-006  security-sensitive table touched (a `WARN` for the reviewer; never
                fails the job)

Stdlib only for the lint (`--check-if-not-exists`, `--check-destructive`);
the `alembic heads` / `alembic check` / `upgrade head` steps in
`.github/workflows/_job-migrations.yml` shell out to Alembic directly and
this module only assembles their exit codes into named error codes for the
job summary. No network access; no DB required for the static checks.
"""

from __future__ import annotations

import argparse
import ast
import codecs
import functools
import hashlib
import importlib.util
import io
import itertools
import re
import string
import sys
import tokenize
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

# Destructive operations that need an explicit `# cv:contract-phase: <release>`
# justification per ADR-0013 rule 9 / expand-contract discipline.
_DESTRUCTIVE_OP_RE = re.compile(
    r"\bop\.(drop_column|drop_table|drop_index|drop_constraint)\s*\("
)
# `add_column` with `nullable=False` and no `server_default=` is destructive
# for existing rows (breaks expand/contract) unless annotated.
_ADD_COLUMN_RE = re.compile(r"\bop\.add_column\s*\(")
_NULLABLE_FALSE_RE = re.compile(r"nullable\s*=\s*False")
_SERVER_DEFAULT_RE = re.compile(r"server_default\s*=")
_ALTER_COLUMN_TYPE_RE = re.compile(r"\bop\.alter_column\s*\([^)]*type_\s*=")
_CONTRACT_PHASE_RE = re.compile(r"#\s*cv:contract-phase:\s*\S+")
_IF_NOT_EXISTS_RE = re.compile(r"\bIF\s+NOT\s+EXISTS\b", re.IGNORECASE)
# `CREATE EXTENSION IF NOT EXISTS` is exempt: extensions are cluster-level
# objects Alembic does not own (no downgrade drops them — other databases may
# depend on them) and the idempotent form is the documented Postgres idiom.
# The ban (21-database-schema.md §9) targets tables/indexes/columns, whose
# state Alembic *does* own.
_CREATE_EXTENSION_RE = re.compile(
    r"\bCREATE\s+EXTENSION\s+IF\s+NOT\s+EXISTS\b", re.IGNORECASE
)

# Tables that must never be a destructive-op target, contract-phase
# annotation or not (append-only audit, per ticket "Security notes").
# Names confirmed against `docs/plan/21-database-schema.md` §3.10
# (`audit_log`, `audit_checkpoints` — no `audit_entries` table exists).
_FORBIDDEN_DESTRUCTIVE_TABLES = frozenset({"audit_log", "audit_checkpoints"})

# An optional schema and quotes before a table name, for the dynamic-target
# check below. The static check reads statements (`_audit_mutations`), not
# patterns. `GRANT ALL` implicitly includes UPDATE/DELETE/TRUNCATE; a grant
# list may name a mutating verb alongside harmless privileges.
_TABLE_QUALIFIER = r"(?:\"?\w+\"?\.)?\"?'?"

# Sentinel substituted for an f-string placeholder whose value could not be
# resolved to a string constant at lint time. Never matches a real table name
# (NUL cannot appear in Python source), so it only trips the dedicated
# dynamic-table check below and never the static per-table patterns. A target
# counts when its name holds the sentinel anywhere: after literal characters
# (`audit_{suffix}`), quoted or qualified, as well as alone (#4032).
_UNRESOLVED_PLACEHOLDER = "\x00"
_DYNAMIC_MUTATION_RE = re.compile(
    rf"\b(?:DELETE\s+FROM|UPDATE|DROP\s+TABLE|TRUNCATE(?:\s+TABLE)?|ALTER\s+TABLE)"
    rf"\s+{_TABLE_QUALIFIER}\w*{re.escape(_UNRESOLVED_PLACEHOLDER)}"
    rf"|\bGRANT\s+(?:ALL(?:\s+PRIVILEGES)?|[A-Za-z, ]*?\b(?:UPDATE|DELETE|TRUNCATE)\b[A-Za-z, ]*?)"
    rf"\s+ON\s+{_TABLE_QUALIFIER}\w*{re.escape(_UNRESOLVED_PLACEHOLDER)}",
    re.IGNORECASE,
)


# There is deliberately no escape hatch for audit-table mutations: C-5.7
# forbids UPDATE/DELETE/DROP/TRUNCATE/ALTER/mutating GRANT on an audit table
# unconditionally, so no annotation (however spelled) may suppress a genuine
# finding. A previous `# cv:audit-exempt:` marker was removed because it was
# indistinguishable, at review time, from a bypass of a real mutation — see
# PR #1518 review history.


def _resolve_simple_name_constants(tree: ast.AST) -> dict[str, str]:
    """Map a name to the string constant it is bound to (`tbl = "audit_log"`), so a
    placeholder or an argument that is just a `Name` can be read as that constant. A name
    is resolved only when every binding of it in the file gives it that one constant (an
    assignment, a loop, `with` or `except` target, a parameter, an import, a definition,
    a `del`): which of two values a statement sees depends on the order the code runs in,
    so such a name reads as unresolved, and an unresolved name where a table goes is
    refused. A star import may bind any name: in a file that has one, none resolves."""
    # The `Name` targets of an assignment of a string constant, by node.
    constants: dict[int, str] = {}
    for node in ast.walk(tree):
        if (
            isinstance(node, (ast.Assign, ast.AnnAssign))
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name):
                    constants[id(target)] = node.value.value
    values: dict[str, set[str | None]] = {}
    for node in ast.walk(tree):
        bound: list[tuple[str, str | None]] = []
        if isinstance(node, ast.Name) and not isinstance(node.ctx, ast.Load):
            bound = [(node.id, constants.get(id(node)))]
        elif isinstance(node, ast.arg):
            bound = [(node.arg, None)]
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            bound = [((a.asname or a.name).split(".")[0], None) for a in node.names]
        elif isinstance(
            node,
            (
                ast.FunctionDef,
                ast.AsyncFunctionDef,
                ast.ClassDef,
                ast.ExceptHandler,
                ast.MatchAs,
                ast.MatchStar,
            ),
        ) and (name := node.name):
            bound = [(name, None)]
        elif isinstance(node, ast.MatchMapping) and node.rest:
            bound = [(node.rest, None)]
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            bound = [(name, None) for name in node.names]
        for name, value in bound:
            values.setdefault(name, set()).add(value)
    if "*" in values:  # `from m import *`
        return {}
    resolved: dict[str, str] = {}
    for name, bound_to in values.items():
        (value,) = bound_to if len(bound_to) == 1 else (None,)
        if value is not None:
            resolved[name] = value
    return resolved


def _iter_string_literals(
    path: Path, source: str, skip_docstrings: bool = False
) -> list[tuple[int, str, bool]]:
    """Every string literal in the migration file, via the AST (so f-string
    parts and implicit concatenation are covered, not just single-line
    `op.execute("...")` calls). Returns `(1-based lineno of the literal's
    first line, normalised text, had_unresolved_interpolation)` triples.

    F-string interpolations that reference a simple `Name` bound to a string
    constant elsewhere in the module (`tbl = "audit_log"; f"...{tbl}..."`)
    are substituted with that value. Any other interpolation (attribute
    access, call, unresolved name, f-string format spec, etc.) is replaced
    with `_UNRESOLVED_PLACEHOLDER` and the triple's third element is `True`,
    so a dynamic table name in an audit-sensitive statement still trips a
    dedicated fail-closed finding even though the real name is unknown.

    `skip_docstrings` leaves out a string used as a statement (a module, class
    or function docstring): it is documentation and never executes."""
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        return []
    name_constants = _resolve_simple_name_constants(tree)
    docstrings: set[int] = set()
    if skip_docstrings:
        docstrings = {
            id(node.value)
            for node in ast.walk(tree)
            if isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        }
    literals: list[tuple[int, str, bool]] = []
    for node in ast.walk(tree):
        if id(node) in docstrings:
            continue
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            literals.append((node.lineno, node.value, False))
        elif isinstance(node, ast.JoinedStr):
            parts: list[str] = []
            unresolved = False
            for part in node.values:
                if isinstance(part, ast.Constant) and isinstance(part.value, str):
                    parts.append(part.value)
                elif isinstance(part, ast.FormattedValue):
                    resolved = None
                    if isinstance(part.value, ast.Name):
                        resolved = name_constants.get(part.value.id)
                    if resolved is not None:
                        parts.append(resolved)
                    else:
                        parts.append(_UNRESOLVED_PLACEHOLDER)
                        unresolved = True
            text = "".join(parts)
            if text:
                literals.append((node.lineno, text, unresolved))
        elif isinstance(node, ast.expr) and (
            built := _built_string(node, name_constants)
        ):
            literals.append((node.lineno, *built))
    return literals


def _fragments(tree: ast.AST) -> set[tuple[int, str]]:
    """`(line, text)` of each string literal that is a piece of a bigger string: an
    f-string's text, an operand of `+`, a `%` or `.format` template, a `.join`
    separator or item. The bigger string is read whole (`_iter_string_literals`)."""
    pieces: list[ast.AST] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            pieces += node.values
        elif isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Mod)):
            pieces += [node.left, node.right]
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in {"format", "join"}
        ):
            pieces.append(node.func.value)
            for arg in node.args:
                pieces += arg.elts if isinstance(arg, (ast.List, ast.Tuple)) else [arg]
    return {
        (piece.lineno, piece.value)
        for piece in pieces
        if isinstance(piece, ast.Constant) and isinstance(piece.value, str)
    }


# A `%` conversion in a template (`"DELETE FROM %s" % table`).
_PERCENT_RE = re.compile(
    r"%(?:\((?P<key>[^)]*)\))?[-#0 +]*(?:\*|\d+)?(?:\.(?:\*|\d+))?[hlL]?"
    r"(?P<conversion>[diouxXeEfFgGcrsa%])"
)


def _part(node: ast.AST | None, names: dict[str, str]) -> tuple[str, bool]:
    """The text an operand of a built string gives, and whether it is unresolved: a
    constant, a name bound to a string constant, or a string built from them."""
    if isinstance(node, ast.Constant) and isinstance(node.value, (str, int, float)):
        return str(node.value), False
    if isinstance(node, ast.Name) and node.id in names:
        return names[node.id], False
    built = _built_string(node, names) if node is not None else None
    return built if built is not None else (_UNRESOLVED_PLACEHOLDER, True)


def _built_string(node: ast.AST, names: dict[str, str]) -> tuple[str, bool] | None:
    """The string `node` builds from a string literal (or a name bound to one) with
    `+`, `%`, `.format(...)` or `.join([...])`, read as an f-string is (#4032): a part
    that is not a literal or a name bound to one reads as `_UNRESOLVED_PLACEHOLDER`.
    None when `node` builds no string from a literal."""
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = _part(node.left, names), _part(node.right, names)
        if left[1] and right[1]:
            return None  # nothing literal in it
        return left[0] + right[0], left[1] or right[1]
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod):
        template, unresolved = _part(node.left, names)
        if unresolved:
            return None
        return _percent(template, node.right, names)
    if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
        return None
    receiver, method = _part(node.func.value, names), node.func.attr
    if receiver[1] or method not in {"format", "join"}:
        return None
    if method == "format":
        return _formatted(receiver[0], node, names)
    items = node.args[0] if len(node.args) == 1 and not node.keywords else None
    if not isinstance(items, (ast.List, ast.Tuple, ast.Set)):
        return _UNRESOLVED_PLACEHOLDER, True
    parts = [_part(item, names) for item in items.elts]
    return receiver[0].join(text for text, _ in parts), any(gap for _, gap in parts)


def _percent(
    template: str, values: ast.expr, names: dict[str, str]
) -> tuple[str, bool]:
    """`template % values`, each conversion filled by `_part`."""
    keyed: dict[object, ast.expr | None] = {}
    if isinstance(values, ast.Dict):
        keyed = {
            key.value: value
            for key, value in zip(values.keys, values.values, strict=True)
            if isinstance(key, ast.Constant)
        }
    listed = list(values.elts) if isinstance(values, ast.Tuple) else [values]
    unresolved, position = False, 0

    def fill(match: re.Match[str]) -> str:
        nonlocal unresolved, position
        if match["conversion"] == "%":
            return "%"
        if match["key"] is not None:
            node = keyed.get(match["key"])
        else:
            node = listed[position] if position < len(listed) else None
            position += 1
        text, gap = _part(node, names)
        unresolved |= gap
        return text

    return _PERCENT_RE.sub(fill, template), unresolved


def _formatted(
    template: str, call: ast.Call, names: dict[str, str]
) -> tuple[str, bool]:
    """`template.format(...)` with the call's arguments, each field filled by
    `_part`; a field that reads an attribute or an index of one is unresolved."""
    try:
        fields = list(string.Formatter().parse(template))
    except ValueError:  # Python refuses it before any SQL runs
        return template, False
    out: list[str] = []
    unresolved, automatic = False, 0
    keywords = {keyword.arg: keyword.value for keyword in call.keywords if keyword.arg}
    for text, field, _, _ in fields:
        out.append(text)
        if field is None:
            continue
        node: ast.expr | None = None
        if field == "":
            if automatic < len(call.args):
                node = call.args[automatic]
            automatic += 1
        elif field.isdigit():
            if int(field) < len(call.args):
                node = call.args[int(field)]
        elif field.isidentifier():
            node = keywords.get(field)
        filled, gap = _part(node, names)
        out.append(filled)
        unresolved |= gap
    return "".join(out), unresolved


def _normalise_sql(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


# CI-MIG-006 reads a revision for the identifiers it names, not for substrings:
# `orders`, `positions`, `executions` and `backups` are also plain words, and a
# table that only a comment or a message mentions is not touched. One scan, left
# to right, consumes whole whatever is not an identifier (comments, `'...'`
# literals) before it takes a name, so a `--` inside a literal or an apostrophe
# inside a comment can neither hide nor swallow a statement. A name is then
# either unquoted (Postgres folds it to lower case) or double-quoted (case kept,
# `""` is one `"`); in `public.orders`, `"public"."orders"` and `orders.id` each
# part is a name. A `$tag$ ... $tag$` body (a `DO` block, a trigger function) is
# code: it is consumed whole, so an apostrophe in it cannot pair with a quote
# outside it, and scanned on its own.
_SQL_TOKEN_RE = re.compile(
    r"--[^\n\r]*"  # line comment: Postgres ends it at a line feed or a return
    r"|/\*.*?\*/"  # block comment
    r"|(?P<estring>[eE]'(?:[^'\\]|\\.|'')*')"  # E'..': backslash escapes
    r"|(?P<string>'(?:[^']|'')*')"  # '..': a doubled quote is one quote
    r'|"(?P<quoted>(?:[^"]|"")+)"'  # "..": a quoted identifier
    r"|\$(?P<tag>(?:[^\W\d]\w*)?)\$(?P<body>.*?)\$(?P=tag)\$"  # $tag$..$tag$
    r"|\$(?:[^\W\d]\w*)?\$"  # a $tag$ delimiter with no partner
    r"|(?P<word>\w[\w$]*)",  # unquoted identifier, keyword or number
    re.DOTALL,
)

# A `'...'` literal is a value unless it is SQL, so its text is read only when it
# is dynamic SQL (it opens with one of `SQL_COMMANDS`, as in the `EXECUTE 'REVOKE
# DELETE ON t FROM cv_app'` these revisions write their grants as) or a bare,
# possibly qualified name (`'orders'::regclass`, the quoted form this rule has
# always matched). A `COMMENT ... IS` text, a `RAISE` message or a seed value such
# as 'orders:read' is prose and is skipped, unless it opens with a command word,
# when it is read as SQL (an extra flag, never a missed one); `$$` text is always
# read as code.
SQL_COMMANDS = (
    "ALTER", "ANALYZE", "BEGIN", "CALL", "CLUSTER", "COMMENT", "COPY", "CREATE",
    "DECLARE", "DELETE", "DO", "DROP", "EXECUTE", "GRANT", "INSERT", "LOCK", "MERGE",
    "REFRESH", "REINDEX", "REVOKE", "SELECT", "SET", "TABLE", "TRUNCATE", "UPDATE",
    "VACUUM", "WITH",
)  # fmt: skip
_SQL_COMMAND_RE = re.compile(r"\s*(?:" + "|".join(SQL_COMMANDS) + r")\b", re.IGNORECASE)
_WORD_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_$]*")
_BARE_NAME_RE = re.compile(r'\s*[\w".]+\s*')


def _sql_identifiers(sql: str) -> set[str]:
    """Every name `sql` uses as an identifier, as Postgres reads it: an unquoted
    name folded to lower case, a double-quoted one exactly (`"ORDERS"` is not
    `orders`). Fail-closed: a column or alias that shares a table's name is read
    as the table, since no grammar is parsed."""
    names: set[str] = set()
    for token in _SQL_TOKEN_RE.finditer(sql):
        quoted, word, body = token["quoted"], token["word"], token["body"]
        literal = token["string"] or token["estring"]
        if body is not None:
            names |= _sql_identifiers(body)
        elif quoted is not None:
            names.add(quoted.replace('""', '"'))
        elif word is not None:
            names.add(word.lower())
        elif literal is not None:
            text = _literal_text(literal)
            if _BARE_NAME_RE.fullmatch(text) or _SQL_COMMAND_RE.match(text):
                names |= _sql_identifiers(text)
    return names


# An `E'...'` literal's backslash escapes (Postgres' string constants with C-style
# escapes): `\xhh`, `\ooo`, `\uXXXX`, `\UXXXXXXXX`, the letter escapes, and a
# backslash before any other character, which stands for it.
_ESCAPE_RE = re.compile(
    r"\\(?:x[0-9A-Fa-f]{1,2}|[0-7]{1,3}|u[0-9A-Fa-f]{4}|U[0-9A-Fa-f]{8}|.)|''",
    re.DOTALL,
)
_LETTER_ESCAPES = {"b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t"}


def _unescape(match: re.Match[str]) -> str:
    escape = match[0]
    if escape == "''":
        return "'"
    body = escape[1:]
    if body[0] in "xuU" and len(body) > 1:
        return chr(min(int(body[1:], 16), 0x10FFFF))
    if body[0] in "01234567":
        return chr(int(body, 8))
    return _LETTER_ESCAPES.get(body, body)


def _literal_text(literal: str) -> str:
    """The text of a `'...'` literal (a doubled quote is one quote) or of an `E'...'`
    literal, its escapes decoded (#4032)."""
    if literal[0] in "eE":
        return _ESCAPE_RE.sub(_unescape, literal[2:-1])
    return literal[1:-1].replace("''", "'")


def _sql_split(sql: str) -> list[str]:
    """`sql` split into statements at each `;` outside a comment, a quote and a `$$`
    body; a blank line never splits one."""
    cuts: list[int] = []
    pos = 0
    for token in _SQL_TOKEN_RE.finditer(sql):
        cuts += [
            pos + i for i, char in enumerate(sql[pos : token.start()]) if char == ";"
        ]
        pos = token.end()
    cuts += [pos + i for i, char in enumerate(sql[pos:]) if char == ";"]
    bounds = [-1, *cuts, len(sql)]
    parts = (sql[start + 1 : end] for start, end in itertools.pairwise(bounds))
    return [part for part in parts if part.strip()]


# A `'...'` literal is SQL wherever it opens with one of `SQL_COMMANDS`, and always
# right after these words: `EXECUTE '...'`, `DO '...'` and `format('...', ...)` run
# it whatever it opens with (a `;`, a comment, a label).
_RUNS_ITS_LITERAL = frozenset({"EXECUTE", "DO", "FORMAT"})
# A literal that `||` continues is a piece of a bigger string (`'UPDATE' || ' t'`).
_CONTINUED_RE = re.compile(r"(?:\s|--[^\n\r]*|/\*.*?\*/)*\|\|", re.DOTALL)


def _nested_sql(statement: str) -> list[str]:
    """The SQL inside `statement`: each `$$` body; each `'...'` literal right after
    `EXECUTE`, `DO` (`DO LANGUAGE <name>` too) or `format(`, and each other that opens
    with one of `SQL_COMMANDS`; and each `"..."` token whose text opens with one, as a
    body in another language writes its SQL (`spi_exec_query("DELETE ...")`). A
    literal `||` continues ends in a space: what follows its last word may be that
    word's target."""
    nested: list[str] = []
    recent: list[str] = []  # the last three words, upper-cased
    for token in _SQL_TOKEN_RE.finditer(statement):
        literal = token["string"] or token["estring"]
        if token["word"] is not None:
            recent = [*recent[-2:], token["word"].upper()]
        elif token["body"] is not None:
            nested.append(token["body"])
        elif literal is not None:
            text = _literal_text(literal)
            runs = recent[-1:] and recent[-1] in _RUNS_ITS_LITERAL
            if (
                runs
                or recent[-3:-1] == ["DO", "LANGUAGE"]
                or _SQL_COMMAND_RE.match(text)
            ):
                continued = _CONTINUED_RE.match(statement, token.end()) is not None
                nested.append(text + " " if continued else text)
        elif token["quoted"] is not None:
            text = token["quoted"].replace('""', '"')
            if _SQL_COMMAND_RE.match(text):
                nested.append(text)
    return nested


def _nested_comment(statement: str) -> bool:
    """Whether a block comment in `statement` opens another: Postgres nests them, the
    reader ends each at its first `*/`, so what follows is unreadable (#4032)."""
    return any(
        token[0].startswith("/*") and "/*" in token[0][2:]
        for token in _SQL_TOKEN_RE.finditer(statement)
    )


def _unicode_escaped(statement: str) -> bool:
    """Whether `statement` spells a name or a string with Unicode escapes (`U&"..."`,
    `U&'...'`), which the rule cannot read (#4032)."""
    return any(
        token["word"] in {"U", "u"}
        and statement[token.end() : token.end() + 2] in {'&"', "&'"}
        for token in _SQL_TOKEN_RE.finditer(statement)
    )


#: The body languages the rule reads; a body in any other is read as words.
_SQL_LANGUAGES = frozenset({"sql", "plpgsql"})


def _foreign_language(statement: str) -> bool:
    """Whether `statement` declares a body language the rule does not read as SQL
    (`LANGUAGE plperl`, `plpython3u`, ...), or names its language unreadably."""
    tokens = [
        t for t in _SQL_TOKEN_RE.finditer(statement) if t[0][:2] not in {"--", "/*"}
    ]
    for i, this in enumerate(tokens):
        if (this["word"] or "").upper() != "LANGUAGE":
            continue
        if i + 1 == len(tokens):
            return True  # no language named: the code builds it at run time
        after = tokens[i + 1]
        literal = after["string"] or after["estring"]
        if after["word"] is not None:
            name = after["word"]
        elif after["quoted"] is not None:
            name = after["quoted"]
        elif literal is not None:
            name = _literal_text(literal)
        else:
            return True
        if name.lower() not in _SQL_LANGUAGES:
            return True
    return False


# A statement mutates when its first word does, or when a `GRANT` hands out a
# mutating privilege; fail-closed for the forms that hide the verb further in: a
# data-modifying `WITH`, an `EXPLAIN ANALYZE`, which runs its statement, a prepared
# statement, a `COPY` of a `RETURNING` query, a table created `AS` a writing query,
# and an upsert's `DO UPDATE`. A trigger
# or a rule mutates the table it is on: it can drop or rewrite each row written
# after it, and `TRIGGER` is the privilege to add one.
_MUTATING = frozenset({"DELETE", "UPDATE", "TRUNCATE", "DROP", "ALTER", "MERGE"})
_CARRIERS = frozenset({"WITH", "EXPLAIN", "PREPARE", "COPY"})
# A plpgsql or SQL-standard body, or a rule, starts a statement after these words
# without a `;` before it: `BEGIN DELETE ...`, `IF c THEN DELETE ...`, `LOOP UPDATE
# ...`, `FOR r IN DELETE ... RETURNING ...`, `RETURN QUERY DELETE ...`, `BEGIN ATOMIC
# DELETE ...`, `DO ALSO DELETE ...`. So the chunk's first word is not its only verb.
_BLOCK_OPENERS = frozenset(
    {"BEGIN", "THEN", "ELSE", "LOOP", "IN", "QUERY", "ATOMIC", "ALSO", "INSTEAD"}
)
_MUTATING_GRANTS = frozenset({"UPDATE", "DELETE", "TRUNCATE", "ALL", "TRIGGER"})
#: A role attribute that reaches the audit tables past their grants: a superuser passes
#: every privilege check, and a role-creating role creates roles, and before PostgreSQL 16
#: could grant itself into any other. Refused either way (fail-closed).
_HANDING_ATTRIBUTES = frozenset({"SUPERUSER", "CREATEROLE"})
_DML = frozenset({"DELETE", "UPDATE", "MERGE", "TRUNCATE"})
_EVERY_TABLE = ["ALL", "TABLES", "IN", "SCHEMA"]  # `GRANT ... ON ALL TABLES IN SCHEMA`
# A chunk's code tokens: a quoted name, a word, or one other character (punctuation,
# a placeholder's `%` or `$`, an unresolved f-string field), read in `_code_text`.
_CODE_TOKEN_RE = re.compile(r'"(?:[^"]|"")+"|\w[\w$]*|\S')
# The verbs whose target follows them (`DELETE FROM <t>`), after `ONLY`, `TABLE` or
# `IF EXISTS` (`_SLOT_WORDS`). A routine's DDL names its routine after its kind, a
# grant or a trigger its table after `ON`, a rule after `TO` (`_open_target`).
_TARGET_VERBS = (
    ["DELETE", "FROM"],
    ["UPDATE"],
    ["TRUNCATE"],
    ["DROP", "TABLE"],
    ["ALTER", "TABLE"],
    ["MERGE", "INTO"],
)
_SLOT_WORDS = frozenset({"ONLY", "TABLE", "IF", "EXISTS"})
# A placeholder in dynamic SQL: its target is an argument, read where it is passed.
_PLACEHOLDER_RE = re.compile(r"%[IsL]|\$\d+")
# The tokens a placeholder opens with: a format conversion, a parameter, a Python
# field the rule cannot resolve (`_UNRESOLVED_PLACEHOLDER`).
_PLACEHOLDER_MARKS = frozenset({"%", "$", _UNRESOLVED_PLACEHOLDER})
_SETS = frozenset({"SET", "RESET"})
#: A setting set under a name the rule cannot read: a placeholder (`%I`, `$1`, a
#: `str.format` field), a Python value it cannot resolve (`_UNRESOLVED_PLACEHOLDER`),
#: or a name its fragment ends on, which the code may go on to build. The placeholder
#: may follow literal characters (`session_{}`). A routine's own `SET` clause counts
#: too: its body runs under it.
_DYNAMIC_SETTING_RE = re.compile(
    r"\s*(?:SET(?:\s+(?:SESSION|LOCAL))?|(?:ALTER\s+(?:ROLE|USER|DATABASE|SYSTEM"
    r"|FUNCTION|PROCEDURE|ROUTINE)|CREATE\s+(?:OR\s+REPLACE\s+)?(?:FUNCTION|PROCEDURE))"
    r"\b.*?\bSET)\s+[\w.\"]*(?:[%$\x00{]|\s*\Z)",
    re.IGNORECASE | re.DOTALL,
)
#: The revision that creates the audit tables and their guard functions (21 §3.10).
#: It is exempt for three statement kinds, wherever they stand in it: `CREATE TRIGGER`
#: on the audit tables; `DROP TABLE` and `DROP TRIGGER` on them, which its downgrade
#: runs behind its refusal to drop a table that holds a row; and the guard functions'
#: DDL. No other revision may do any of them. It is merged and pinned by the
#: migrations lockfile (C-5.4).
_AUDIT_OWNER_REVISION = "0003_audit_log"
#: The functions the audit tables' append-only triggers and hash chain run: replacing,
#: altering or dropping one neuters them without naming a table. `audit_field` encodes
#: each field `audit_chain` hashes.
_AUDIT_FUNCTIONS = frozenset(
    {"forbid_mutation", "audit_refuse_truncate", "audit_chain", "audit_field"}
)
#: What `audit_chain` and `audit_field` call by an unqualified name, resolved through
#: the inserting session's `search_path`: another routine of that name, in a schema
#: searched first or with a closer signature, forges or breaks the chain.
_CHAIN_CALLEES = frozenset(
    {
        "digest",
        "encode",
        "hashtext",
        "length",
        "pg_advisory_xact_lock",
        "repeat",
        "to_char",
    }
)
_ROUTINE_KINDS = frozenset({"FUNCTION", "PROCEDURE", "ROUTINE", "AGGREGATE"})
# The name a `CREATE FUNCTION` (or procedure, or aggregate) gives its routine: the
# last part of a possibly qualified name, before its arguments, in `_code_text`.
_ROUTINE_NAME_RE = re.compile(
    r"\b(?:FUNCTION|PROCEDURE|AGGREGATE)\s+"
    r'(?:(?:"(?:[^"]|"")+"|\w+)\s*\.\s*)*("(?:[^"]|"")+"|\w+)\s*\(',
    re.IGNORECASE,
)
#: The revision that replaces `audit_chain()` (#889 S3, SR-E42-10): its row id drawn
#: under the chain's lock, and its own `search_path`. It is exempt only while it holds
#: nothing but a docstring, its imports (`_CHAIN_HARDENING_IMPORTS`), its identifiers
#: and an `upgrade()` and a `downgrade()` that each run one `op.execute` of a string
#: literal whose text, stripped, hashes to its pin: the reviewed function text and its
#: exact restore, nothing else (`_chain_hardening_deviations`). Anything else makes it
#: an ordinary revision. The migrations lockfile pins its bytes once it is merged.
_CHAIN_HARDENING_REVISION = "0045_audit_chain_hardening"
_CHAIN_HARDENING_SHA256 = {
    # 0003's `audit_chain()`, as `CREATE OR REPLACE`, with `SET search_path =
    # pg_catalog, public, pg_temp` and `NEW.id := nextval('audit_log_id_seq')` after
    # the lock.
    "upgrade": "bd698deea45af9e443d9baeabd238b9bdb87d374744da7e836e394318fa4d411",
    # 0003's `audit_chain()` byte for byte, as `CREATE OR REPLACE`.
    "downgrade": "356bec08de239a8c97b7727c5dd50658c419991e71bf6f9b2c6a17eb137b3b20",
}
_CHAIN_HARDENING_IMPORTS = frozenset(
    {("__future__", "annotations"), ("collections.abc", "Sequence"), ("alembic", "op")}
)
_REVISION_IDENTIFIERS = frozenset(
    {"revision", "down_revision", "branch_labels", "depends_on"}
)
# What an annotation of a revision identifier may hold (`str | Sequence[str] | None`):
# names, subscripts, unions and constants, nothing that runs code on import.
_ANNOTATION_NODES = (
    ast.Name,
    ast.Subscript,
    ast.BinOp,
    ast.BitOr,
    ast.Constant,
    ast.Tuple,
    ast.Load,
)


def _created_at(words: list[str], at: int) -> int | None:
    """Where the kind of object the clause at `at` creates stands (`CREATE [OR
    REPLACE] [CONSTRAINT] <kind>`), or None."""
    if words[at : at + 1] != ["CREATE"]:
        return None
    kind = at + 3 if words[at + 1 : at + 3] == ["OR", "REPLACE"] else at + 1
    if words[kind : kind + 1] == ["CONSTRAINT"]:
        kind += 1
    return kind if kind < len(words) else None


def _creates(words: list[str], at: int = 0) -> str | None:
    """The kind of object the clause at `at` creates (`TRIGGER`, `RULE`, ...)."""
    kind = _created_at(words, at)
    return None if kind is None else words[kind]


def _creates_view(words: list[str], at: int) -> bool:
    """Whether the clause at `at` creates a view, `CREATE [OR REPLACE] [TEMP]
    [RECURSIVE] VIEW` (a materialized one is never updatable)."""
    kind = _created_at(words, at)
    while kind is not None and words[kind] in {"TEMP", "TEMPORARY", "RECURSIVE"}:
        kind = kind + 1 if kind + 1 < len(words) else None
    return kind is not None and words[kind] == "VIEW"


def _creates_table(words: list[str], at: int) -> bool:
    """Whether the clause at `at` creates a table (`CREATE [TEMP | UNLOGGED | ...]
    TABLE`): one created `AS` a query carries that query's writes."""
    kind = _created_at(words, at)
    while kind is not None and words[kind] in {
        "TEMP",
        "TEMPORARY",
        "UNLOGGED",
        "GLOBAL",
        "LOCAL",
    }:
        kind = kind + 1 if kind + 1 < len(words) else None
    return kind is not None and words[kind] == "TABLE"


def _security_invoker(words: list[str]) -> bool:
    """Whether a view's options set `security_invoker` (bare, or to a true value): a
    grant on it then reaches its tables only with the grantee's own privileges."""
    for i, word in enumerate(words):
        if word == "SECURITY_INVOKER":
            return words[i + 1 : i + 2] != ["="] or words[i + 2 : i + 3] in (
                ["TRUE"],
                ["ON"],
                ["1"],
                ["YES"],
            )
    return False


def _suffix(size: int, hit: Callable[[int], bool]) -> list[bool]:
    """For each position up to `size`, whether `hit` holds at it or after it."""
    flags = [False] * (size + 1)
    for i in range(size - 1, -1, -1):
        flags[i] = flags[i + 1] or hit(i)
    return flags


def _next(words: list[str], word: str) -> list[int]:
    """For each position, the first `word` at it or after it (`len(words)`: none)."""
    found = [len(words)] * (len(words) + 1)
    for i in range(len(words) - 1, -1, -1):
        found[i] = i if words[i] == word else found[i + 1]
    return found


def _clause_starts(words: list[str]) -> Iterator[int]:
    """Where the statements of a `;`-chunk start: at its first token, after each
    block opener (`_BLOCK_OPENERS`), and after the `FOR` of a cursor (`OPEN <name>
    FOR`, `<name> CURSOR FOR`), whose query a body runs with no `;` before it."""
    if words:
        yield 0
    cursor = False
    for i, word in enumerate(words[:-1]):
        if word in _BLOCK_OPENERS or (word == "FOR" and cursor):
            yield i + 1
        if word in {"OPEN", "CURSOR"}:
            cursor = True
        elif word == "FOR":
            cursor = False


class _Chunk:
    """A `;`-chunk's code tokens (`_CODE_TOKEN_RE`) and what its clauses ask of the
    rest of it, each read once, so a chunk of many block openers is read in linear
    time and memory (#4032). A clause runs from its start (`_clause_starts`) to the
    chunk's end."""

    def __init__(self, statement: str) -> None:
        found = list(_CODE_TOKEN_RE.finditer(_code_text(statement)))
        self.tokens: list[str] = [token[0] for token in found]
        # Whether each token runs straight on into the next, with no space between.
        self.glued = [a.end() == b.start() for a, b in itertools.pairwise(found)]
        self.glued.append(False)
        self.words = words = [token.upper() for token in self.tokens]
        size = len(words)
        self.names = _head_identifiers(statement)
        # A statement that ends in whitespace may be a piece of a bigger one, whose
        # last verb's target follows it (`'UPDATE ' || t`).
        self.open_end = statement[-1:].isspace()
        self.next_on, self.next_to = _next(words, "ON"), _next(words, "TO")
        self.next_grant = _next(words, "GRANT")
        self.set_after = _suffix(size, lambda i: words[i] in _SETS)
        self.add_after = _suffix(size, lambda i: words[i] == "ADD")
        self.membership_after = _suffix(
            size, lambda i: words[i] in {"ROLE", "GROUP", *_HANDING_ATTRIBUTES}
        )
        self.attribute_after = _suffix(size, lambda i: words[i] in _HANDING_ATTRIBUTES)
        self.replication_role = any(
            name.lower() == "session_replication_role" for name in self.names
        )
        self.dml_after = _suffix(size, lambda i: words[i] in _DML)
        self.upsert_after = _suffix(
            size, lambda i: words[i : i + 2] == ["DO", "UPDATE"]
        )
        self.cascade_after = _suffix(size, lambda i: words[i] == "CASCADE")
        self.reset_all_after = _suffix(
            size, lambda i: words[i : i + 2] == ["RESET", "ALL"]
        )
        self.cte_after = (
            _suffix(  # `AS WITH ...`, `AS (WITH ...)`: a CTE that may write
                size,
                lambda i: words[i] == "AS"
                and (
                    words[i + 1 : i + 2] == ["WITH"]
                    or words[i + 1 : i + 3] == ["(", "WITH"]
                ),
            )
        )
        self.every_table_after = _suffix(
            size, lambda i: words[i : i + 4] == _EVERY_TABLE
        )
        # From each position to the next `ON`: whether a mutating privilege is granted.
        self.granting = [False] * (size + 1)
        for i in range(size - 1, -1, -1):
            self.granting[i] = words[i] != "ON" and (
                words[i] in _MUTATING_GRANTS or self.granting[i + 1]
            )
        self.starts = list(_clause_starts(words))


def _mutates(chunk: _Chunk, at: int) -> bool:
    """Whether the clause at `at` mutates (`_MUTATING`)."""
    words = chunk.words
    first = words[at]
    if first in _MUTATING or _creates(words, at) in {"TRIGGER", "RULE"}:
        return True
    if first == "GRANT":
        return chunk.granting[at + 1]
    if first in _CARRIERS or (_creates_table(words, at) and chunk.cte_after[at]):
        return chunk.dml_after[at]
    if first == "INSERT":
        return chunk.upsert_after[at]
    return False


def _head_identifiers(statement: str) -> set[str]:
    """The names `statement` itself uses, outside its quotes and `$$` bodies."""
    names: set[str] = set()
    for token in _SQL_TOKEN_RE.finditer(statement):
        if token["word"] is not None:
            names.add(token["word"].lower())
        elif token["quoted"] is not None:
            names.add(token["quoted"].replace('""', '"'))
    return names


def _routine_kind(words: list[str], at: int) -> int | None:
    """The position of the routine kind (`FUNCTION`, ...) when the clause at `at`
    defines, replaces, alters or drops a routine (a function, a procedure or an
    aggregate), else None."""
    if _creates(words, at) in _ROUTINE_KINDS:
        return _created_at(words, at)
    if (
        words[at] in {"ALTER", "DROP"}
        and words[at + 1 : at + 2]
        and (words[at + 1] in _ROUTINE_KINDS)
    ):
        return at + 1
    return None


def _code_text(statement: str) -> str:
    """`statement` with its comments, `'...'` literals and `$$` bodies blanked: its
    keywords, names and punctuation."""
    return _SQL_TOKEN_RE.sub(
        lambda token: token[0] if token["word"] or token["quoted"] else " ", statement
    )


@functools.lru_cache(maxsize=1)  # each clause of one statement asks again
def _routine_names(statement: str) -> frozenset[str]:
    """The names the routines `statement` creates are given (`_ROUTINE_NAME_RE`)."""
    names: set[str] = set()
    for match in _ROUTINE_NAME_RE.finditer(_code_text(statement)):
        name = match[1]
        names.add(name[1:-1].replace('""', '"') if name[0] == '"' else name.lower())
    return frozenset(names)


def _redefined_functions(chunk: _Chunk, at: int) -> set[str]:
    """The guard functions the clause at `at` defines, replaces, alters or drops, of
    the names its statement uses (`_head_identifiers`)."""
    if _routine_kind(chunk.words, at) is None:
        return set()
    return chunk.names & _AUDIT_FUNCTIONS


def _shadowed_callees(chunk: _Chunk, at: int, statement: str) -> set[str]:
    """The chain's callees (`_CHAIN_CALLEES`) that the clause at `at` creates a routine
    as (read from the routine's own name, since a parameter may share a callee's
    name), or alters or drops (read from any name the clause uses: `RENAME TO`, a list
    of routines)."""
    if _routine_kind(chunk.words, at) is None:
        return set()
    if _creates(chunk.words, at) is not None:
        return set(_routine_names(statement)) & _CHAIN_CALLEES
    return chunk.names & _CHAIN_CALLEES


def _reach(chunk: _Chunk, at: int) -> str | None:
    """What the clause at `at` hands over, drops or redirects that holds the audit
    tables or what their guards run on, without naming a table, or None: a role's
    membership, or a superuser or role-creating attribute (`role`; whoever owns the
    audit tables can drop their triggers), a schema with everything in it, or its owner
    (`schema`), every object a role owns (`owned`), the extension `audit_chain` hashes
    with (`pgcrypto`), the `search_path` a role or a database resolves the chain's calls
    through (`search_path`), a mutating privilege every table created later gets by
    default (`default_privileges`), as a new audit table would, the setting that turns
    the tables' triggers off (`replication_role`), a setting set through `set_config()`
    (`set_config`), or an event trigger, which runs on later DDL (`event_trigger`)."""
    words, names = chunk.words, chunk.names
    head = words[at : at + 2]
    if (
        (head[:1] == ["GRANT"] and chunk.next_to[at] < chunk.next_on[at])
        or (head == ["ALTER", "GROUP"] and chunk.add_after[at])
        or (
            head[:1] == ["CREATE"]
            and head[1:2] in (["ROLE"], ["USER"], ["GROUP"])
            and chunk.membership_after[at + 2]  # `IN ROLE`, ...
        )
        or (
            head in (["ALTER", "ROLE"], ["ALTER", "USER"])
            and chunk.attribute_after[at + 2]
        )
    ):
        return "role"
    if head == ["ALTER", "SCHEMA"] or (
        head == ["DROP", "SCHEMA"] and chunk.cascade_after[at]
    ):
        return "schema"
    if head in (["DROP", "OWNED"], ["REASSIGN", "OWNED"]):
        return "owned"
    grant = chunk.next_grant[at]
    if (
        head == ["ALTER", "DEFAULT"]
        and grant < len(words)
        and chunk.granting[grant + 1]
        and words[chunk.next_on[grant] + 1 : chunk.next_on[grant] + 2] == ["TABLES"]
    ):
        return "default_privileges"
    if chunk.replication_role and (
        head[:1] in (["SET"], ["RESET"])
        or (head[:1] in (["ALTER"], ["CREATE"]) and chunk.set_after[at])
    ):
        return "replication_role"
    if "set_config" in names:
        return "set_config"
    if words[at : at + 3] in (
        ["CREATE", "EVENT", "TRIGGER"],
        ["ALTER", "EVENT", "TRIGGER"],
    ):
        return "event_trigger"
    if head in (["DROP", "EXTENSION"], ["ALTER", "EXTENSION"]) and "pgcrypto" in names:
        return "pgcrypto"
    settings = (["ALTER", "ROLE"], ["ALTER", "USER"], ["ALTER", "DATABASE"])
    if head in settings and ("search_path" in names or chunk.reset_all_after[at]):
        return "search_path"
    return None


def _named(chunk: _Chunk, at: int) -> bool:
    """Whether a name starts at token `at`, after `ONLY`, `TABLE` or `IF EXISTS`:
    one to three parts joined by `.`, each a quoted name or a word that is not a
    number. A part glued to a placeholder (`audit_%s`), or a quoted part holding one
    (`"audit_%s"`), is built at run time."""
    tokens = chunk.tokens
    while at < len(tokens) and tokens[at].upper() in _SLOT_WORDS:
        at += 1
    for _ in range(3):
        if at >= len(tokens) or not (tokens[at][0] in '"_' or tokens[at][0].isalpha()):
            return False
        if chunk.glued[at] and tokens[at + 1] in _PLACEHOLDER_MARKS:
            return False
        if tokens[at][0] == '"' and (
            _PLACEHOLDER_RE.search(tokens[at]) or _UNRESOLVED_PLACEHOLDER in tokens[at]
        ):
            return False
        if tokens[at + 1 : at + 2] != ["."]:
            return True
        at += 2
    return False


def _open_target(chunk: _Chunk, at: int) -> bool:
    """Whether the clause at `at` mutates a target its text does not name: the slot
    after its verb (`_TARGET_VERBS`, a routine's kind), or after the `ON` of a
    mutating grant or a trigger or the `TO` of a rule, holds a placeholder, a
    concatenation, an unresolved field or nothing (#4032)."""
    words, tokens, size = chunk.words, chunk.tokens, len(chunk.words)
    for verb in _TARGET_VERBS:
        if words[at : at + len(verb)] == verb:
            if at + len(verb) == size and len(verb) == 1 and not chunk.open_end:
                return False  # a verb on its own is a value: `TG_OP = 'UPDATE'`
            return not _named(chunk, at + len(verb))
    if (kind := _routine_kind(words, at)) is not None:
        return not _named(chunk, kind + 1)
    if _creates(words, at) == "RULE":
        slot = chunk.next_to[at]
    elif (
        (words[at] == "GRANT" and chunk.granting[at + 1])
        or _creates(words, at) == "TRIGGER"
        or words[at : at + 2] == ["DROP", "TRIGGER"]
    ):
        slot = chunk.next_on[at]
    else:
        return False
    return slot < size and not _named(chunk, slot + 1)


def _closing(tokens: list[str]) -> dict[int, int]:
    """Each `(` token's matching `)`, by position."""
    pairs: dict[int, int] = {}
    opened: list[int] = []
    for i, mark in enumerate(tokens):
        if mark == "(":
            opened.append(i)
        elif mark == ")" and opened:
            pairs[opened.pop()] = i
    return pairs


def _opaque_execute(chunk: _Chunk) -> bool:
    """Whether a body's `EXECUTE` runs SQL the rule cannot read (#4032): anything but
    one `'...'` literal or one `format('...', ...)`, then the statement's end,
    `USING`, `INTO` or `LOOP`. `EXECUTE FUNCTION` (a trigger's) runs no SQL text, and
    neither does the privilege a grant or a revoke names (`GRANT EXECUTE ON`,
    `GRANT USAGE, EXECUTE ON`)."""
    words, size = chunk.words, len(chunk.words)
    closing = _closing(chunk.tokens)
    for i, word in enumerate(words):
        if (
            word != "EXECUTE"
            or words[i + 1 : i + 2] in (["FUNCTION"], ["PROCEDURE"], ["ON"])
            or words[i - 1 : i] in (["GRANT"], ["REVOKE"], [","])
        ):
            continue
        after = i + 1  # past a literal: `_code_text` blanks it
        if words[after : after + 2] == ["FORMAT", "("]:
            if words[after + 2 : after + 3] not in ([","], [")"]):
                return True  # its template is not one literal
            after = closing.get(after + 1, size) + 1
        if after < size and words[after] not in {"USING", "INTO", "LOOP"}:
            return True
    return False


def _audit_mutations(
    sql: str,
    tables: frozenset[str],
    *,
    owner: bool,
    executable: bool = True,
    nested: bool = False,
) -> set[str]:
    """The audit tables a statement in `sql` mutates (or `*`: every table, by a
    schema-wide grant; `fn:<name>`: a guard function it redefines or drops;
    `callee:<name>`: a routine the hash chain calls, redefined, altered or dropped;
    `reach:<what>`: what `_reach` names, `reach:view`, a view over an audit table that
    runs with its owner's privileges, or `reach:set_config`, a setting under a computed
    name; `dynamic`: a mutation whose target is named only at run time; `unicode`: a
    name or a string spelled with Unicode escapes). A
    statement counts when a clause of it mutates (`_clause_starts`, `_mutates`: a
    body, a cursor or a rule starts one mid-statement) and it names an audit table as
    an identifier (`_sql_identifiers`, fail-closed: a subquery's table counts too), or
    when SQL nested in it mutates a placeholder's target and the statement names an
    audit table (`EXECUTE format('DELETE FROM %I', ...)`), or when it declares a body
    in a language the rule does not read and names one. Nested SQL is read the same
    way, where a statement that opens with a placeholder (the verb passed in) or an
    `EXECUTE` the rule cannot read (`_opaque_execute`) is `dynamic` too. `executable`
    is false for a docstring, prose that never runs, and for a piece of a bigger
    string: its open targets and languages are not read. In the owner revision, its
    triggers on the audit tables, its drops of the tables and of their triggers, and
    the guard functions' DDL are not findings."""
    hits: set[str] = set()
    for statement in _sql_split(sql):
        chunk = _Chunk(statement)
        words = chunk.words
        passed_in = False  # nested SQL mutates a target this statement may pass in
        open_target = False
        for text in _nested_sql(statement):
            found = _audit_mutations(
                text, tables, owner=owner, executable=executable, nested=True
            )
            open_target |= "dynamic" in found
            hits |= found - {"dynamic"}
            if not found and _PLACEHOLDER_RE.search(text):
                inner = _Chunk(text)
                passed_in |= bool(inner.starts) and _mutates(inner, inner.starts[0])
        if _unicode_escaped(statement):
            hits.add("unicode")
        if executable and _DYNAMIC_SETTING_RE.match(_code_text(statement)):
            hits.add("reach:set_config")
        if _nested_comment(statement):
            hits.add("comment")
        if nested and executable:
            verb_passed_in = any(chunk.tokens[at] == "%" for at in chunk.starts)
            open_target |= verb_passed_in or _opaque_execute(chunk)
        for at in chunk.starts:
            if not owner:
                hits |= {f"fn:{name}" for name in _redefined_functions(chunk, at)}
            hits |= {
                f"callee:{name}" for name in _shadowed_callees(chunk, at, statement)
            }
            if (reach := _reach(chunk, at)) is not None:
                hits.add(f"reach:{reach}")
            open_target |= executable and _open_target(chunk, at)
        view = any(_creates_view(words, at) for at in chunk.starts)
        if (
            view
            and not _security_invoker(words)
            and _sql_identifiers(statement) & tables
        ):
            hits.add("reach:view")
        if (
            any(
                words[at : at + 2] in (["ALTER", "VIEW"], ["ALTER", "TABLE"])
                for at in chunk.starts
            )
            and "SECURITY_INVOKER" in words
            and ("RESET" in words or not _security_invoker(words))
        ):
            hits.add("reach:view_owner")
        # A verb Python computes (`f"{verb} FROM audit_log"`) may be any verb: what the
        # statement names counts as mutated.
        computed_verb = executable and any(
            chunk.tokens[at] == _UNRESOLVED_PLACEHOLDER for at in chunk.starts
        )
        mutating = [at for at in chunk.starts if _mutates(chunk, at)]
        if any(words[at] == "GRANT" and chunk.every_table_after[at] for at in mutating):
            hits.add("*")
            continue
        if owner:
            mutating = [
                at
                for at in mutating
                if not (
                    words[at] == "DROP"
                    and words[at + 1 : at + 2] in (["TABLE"], ["TRIGGER"])
                )
                and words[at : at + 2] != ["CREATE", "TRIGGER"]
            ]
        foreign = (
            executable
            and (
                words[:1] == ["DO"]
                or any(_creates(words, at) in _ROUTINE_KINDS for at in chunk.starts)
            )
            and _foreign_language(statement)
        )
        if mutating or passed_in or open_target or foreign or computed_verb:
            named = _sql_identifiers(statement)
            hits |= named & tables
            if not owner and (passed_in or open_target or computed_verb):
                hits |= {f"fn:{name}" for name in named & _AUDIT_FUNCTIONS}
            if open_target and not named & (tables | _AUDIT_FUNCTIONS):
                hits.add("dynamic")
    return hits


def _revision_id(tree: ast.Module) -> str | None:
    """The module's `revision`, its Alembic id, read as Alembic and the migrations
    lockfile read it: the last module-level assignment wins. A value that is not a
    string constant reads as `None`, and an assignment in a function or class body
    is not the module's."""
    revision: str | None = None
    for node in tree.body:
        targets: list[ast.expr]
        if isinstance(node, ast.AnnAssign):
            targets, value = [node.target], node.value
        elif isinstance(node, ast.Assign):
            targets, value = list(node.targets), node.value
        else:
            continue
        if any(isinstance(t, ast.Name) and t.id == "revision" for t in targets):
            revision = None
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                revision = value.value
    return revision


def _is_docstring(node: ast.stmt) -> bool:
    return (
        isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    )


def _is_revision_identifier(node: ast.stmt) -> bool:
    """`revision = "..."`, `down_revision: str | None = None` and their kin: a constant
    given to one of Alembic's identifiers, under an annotation that runs no code."""
    targets: list[ast.expr]
    if isinstance(node, ast.AnnAssign):
        targets, value = [node.target], node.value
        if not all(isinstance(n, _ANNOTATION_NODES) for n in ast.walk(node.annotation)):
            return False
    elif isinstance(node, ast.Assign):
        targets, value = node.targets, node.value
    else:
        return False
    return (
        len(targets) == 1
        and isinstance(targets[0], ast.Name)
        and targets[0].id in _REVISION_IDENTIFIERS
        and isinstance(value, ast.Constant)
        and (value.value is None or isinstance(value.value, str))
    )


def _executed_literal(statement: ast.stmt) -> str | None:
    """The string literal of `op.execute("<literal>")`, else None."""
    if not (isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call)):
        return None
    call = statement.value
    if not (
        isinstance(call.func, ast.Attribute)
        and call.func.attr == "execute"
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id == "op"
        and len(call.args) == 1
        and not call.keywords
        and isinstance(call.args[0], ast.Constant)
        and isinstance(call.args[0].value, str)
    ):
        return None
    return call.args[0].value


def _chain_hardening_deviations(tree: ast.Module) -> list[int]:
    """The lines of whatever `_CHAIN_HARDENING_REVISION` holds besides a docstring, its
    imports, its identifiers and an `upgrade()` and a `downgrade()` that each run
    nothing but `op.execute` of the literal its pin (`_CHAIN_HARDENING_SHA256`) hashes;
    none when it holds nothing else. A function it lacks deviates at line 1."""
    lines: list[int] = []
    seen: set[str] = set()
    for index, node in enumerate(tree.body):
        if (
            isinstance(node, ast.FunctionDef)
            and node.name in _CHAIN_HARDENING_SHA256
            and node.name not in seen
        ):
            seen.add(node.name)
            arguments = node.args
            body = node.body[1:] if _is_docstring(node.body[0]) else node.body
            sql = _executed_literal(body[0]) if len(body) == 1 else None
            text = b"" if sql is None else sql.strip().encode("utf-8", "surrogatepass")
            pin = _CHAIN_HARDENING_SHA256[node.name]
            if (
                sql is None
                or hashlib.sha256(text).hexdigest() != pin
                or node.decorator_list
                or getattr(node, "type_params", [])
                or arguments.posonlyargs
                or arguments.args
                or arguments.vararg
                or arguments.kwonlyargs
                or arguments.kwarg
                or not (
                    node.returns is None
                    or (
                        isinstance(node.returns, ast.Constant)
                        and node.returns.value is None
                    )
                )
            ):
                lines.append(node.lineno)
        elif not (
            (index == 0 and _is_docstring(node))
            or _is_revision_identifier(node)
            or (
                isinstance(node, ast.ImportFrom)
                and node.level == 0
                and all(
                    alias.asname is None
                    and (node.module, alias.name) in _CHAIN_HARDENING_IMPORTS
                    for alias in node.names
                )
            )
        ):
            lines.append(node.lineno)
    if seen != _CHAIN_HARDENING_SHA256.keys():
        lines.append(1)
    return sorted(lines)


def _op_targets(
    tree: ast.AST, ops: frozenset[str], tables: frozenset[str]
) -> dict[int, str]:
    """`{line: audit table}` of each `op.<one of ops>(...)` call that names an audit
    table in any argument (a literal or a name bound to one), by the line the call
    starts on, so a name on a later line of the call still counts."""
    names = _resolve_simple_name_constants(tree)
    hits: dict[int, str] = {}
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in ops
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "op"
        ):
            continue
        for arg in [*node.args, *(keyword.value for keyword in node.keywords)]:
            if isinstance(arg, ast.Constant):
                value = arg.value
            else:
                value = names.get(arg.id) if isinstance(arg, ast.Name) else None
            if isinstance(value, str) and value in tables:
                hits.setdefault(node.lineno, value)
    return hits


#: Each Alembic operation that drops, renames or reshapes a table, by the position and
#: the keyword of its table argument (`drop_index` may name none: an index name is
#: unique in its schema).
_TABLE_ARGUMENT = {
    "drop_table": (0, "table_name"),
    "drop_column": (0, "table_name"),
    "drop_constraint": (1, "table_name"),
    "drop_index": (1, "table_name"),
    "rename_table": (0, "old_table_name"),
    "alter_column": (0, "table_name"),
    "add_column": (0, "table_name"),
    "batch_alter_table": (0, "table_name"),
}


def _op_names(tree: ast.AST) -> set[str]:
    """The names a revision binds Alembic's `op` to: `op`, an import alias (`from
    alembic import op as o`, `import alembic.op as o`) and a plain rebinding
    (`o = op`)."""
    names = {"op"}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "alembic":
            names |= {a.asname or a.name for a in node.names if a.name == "op"}
        elif isinstance(node, ast.Import):
            names |= {
                a.asname for a in node.names if a.name == "alembic.op" and a.asname
            }
    for _ in range(3):  # a rebinding of a rebinding
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and (
                (isinstance(node.value, ast.Name) and node.value.id in names)
                or _is_alembic_op(node.value)
            ):
                names |= {t.id for t in node.targets if isinstance(t, ast.Name)}
    return names


def _is_alembic_op(node: ast.AST) -> bool:
    """`alembic.op`."""
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "op"
        and isinstance(node.value, ast.Name)
        and node.value.id == "alembic"
    )


def _untracked_op(tree: ast.AST) -> list[int]:
    """The lines where `op` (any name bound to it, `alembic.op`) is used but called:
    an operation imported by name (`from alembic.op import drop_table`), held in a
    name or a collection, or handed on. The rule cannot follow what that calls."""
    names = _op_names(tree)
    followed: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute):
                followed.add(id(func.value))  # `op.<name>(...)`
            if (
                isinstance(func, ast.Call)
                and isinstance(func.func, ast.Name)
                and func.func.id == "getattr"
                and func.args
            ):
                followed.add(id(func.args[0]))  # `getattr(op, "<name>")(...)`
        elif isinstance(node, ast.Assign) and isinstance(node.value, ast.Name):
            followed.add(id(node.value))  # `o = op`, followed by `_op_names`
        elif isinstance(node, ast.Assign) and _is_alembic_op(node.value):
            followed.add(id(node.value))
    lines: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(
            "alembic.op"
        ):
            lines.append(node.lineno)
        elif id(node) in followed:
            continue
        elif isinstance(node, ast.Name) and node.id in names:
            if isinstance(node.ctx, ast.Load):
                lines.append(node.lineno)
        elif isinstance(node, ast.Attribute) and _is_alembic_op(node):
            lines.append(node.lineno)
    return lines


def _op_calls(tree: ast.AST) -> Iterator[tuple[ast.Call, str | None, bool]]:
    """Each call of an Alembic operation, its name (None when a `getattr` picks it at
    run time) and whether it is spelled `op.<name>(...)`: through an alias, `alembic.op`
    or `getattr(op, "<name>")` too."""
    names = _op_names(tree)

    def is_op(node: ast.AST) -> bool:
        if isinstance(node, ast.Name):
            return node.id in names
        return _is_alembic_op(node)

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and is_op(func.value):
            plain = isinstance(func.value, ast.Name) and func.value.id == "op"
            yield node, func.attr, plain
        elif (
            isinstance(func, ast.Call)
            and isinstance(func.func, ast.Name)
            and func.func.id == "getattr"
            and func.args
            and is_op(func.args[0])
        ):
            picked = func.args[1] if len(func.args) > 1 else None
            name = picked.value if isinstance(picked, ast.Constant) else None
            yield node, name if isinstance(name, str) else None, False


def _argument_value(node: ast.expr, names: dict[str, str]) -> str | None:
    """A literal string argument, or a name bound to one; None otherwise."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return names.get(node.id) if isinstance(node, ast.Name) else None


def _alembic_findings(
    tree: ast.AST, tables: frozenset[str], lines: list[str]
) -> dict[int, str]:
    """`{line: target}` of the Alembic operations that reach an audit table: a reshape
    (`rename_table`, `alter_column`, `add_column`, `batch_alter_table`) naming one, as
    its raw `ALTER TABLE` is, a drop naming one
    that `check_destructive_annotations`' line reader does not report (an alias,
    `getattr`, a wrapped call), an operation whose table argument is not a literal or
    a name bound to one, and one a `getattr` picks at run time (#4032)."""
    names = _resolve_simple_name_constants(tree)
    reshapes = {"rename_table", "alter_column", "batch_alter_table"}
    hits: dict[int, str] = {
        line: "an Alembic operation the rule cannot follow (imported by name, held "
        "in a name or a collection, or handed on)"
        for line in _untracked_op(tree)
    }
    for call, method, plain in _op_calls(tree):
        if method is None:
            hits.setdefault(call.lineno, "an Alembic operation picked at run time")
            continue
        if method not in _TABLE_ARGUMENT:
            continue
        arguments = [*call.args, *(keyword.value for keyword in call.keywords)]
        named = {
            value for arg in arguments if (value := _argument_value(arg, names))
        } & tables
        line = lines[call.lineno - 1] if call.lineno <= len(lines) else ""
        reported = bool(_DESTRUCTIVE_OP_RE.search(line)) and bool(
            (plain and named) or _table_mentioned(line, tables)
        )
        if named and (method in reshapes or not reported):
            hits.setdefault(call.lineno, f"append-only table '{min(named)}'")
            continue
        position, keyword = _TABLE_ARGUMENT[method]
        # The keyword, `**kw`, a starred list up to the slot, or the slot itself.
        given = [kw.value for kw in call.keywords if kw.arg in (keyword, None)]
        given += [arg for arg in call.args[:position] if isinstance(arg, ast.Starred)]
        if len(call.args) > position:
            given.append(call.args[position])
        if given:
            values = [_argument_value(arg, names) for arg in given]
            table = None if None in values else values[-1]
        elif method == "drop_index":
            continue
        else:
            table = None
        if table is None:
            hits.setdefault(call.lineno, "a table it names only at run time")
    return hits


def _core_table_name(node: ast.Call) -> ast.expr | None:
    """The name a Core `table(...)`/`Table(...)` call is given: its first argument, or
    `table()`'s `name=` keyword, or a `**kw` that may hold it."""
    if node.args:
        return node.args[0]
    return next((kw.value for kw in node.keywords if kw.arg in ("name", None)), None)


def _python_settings(tree: ast.AST) -> dict[int, str]:
    """`{line: reach}` of a setting Python sets past the SQL reader (#4032): a call of
    `set_config` (`sa.func.set_config(...)`), and a string that is the name of the
    setting that turns the tables' triggers off, wherever Python passes it."""
    hits: dict[int, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            callee = (
                func.attr
                if isinstance(func, ast.Attribute)
                else getattr(func, "id", "")
            )
            if str(callee).lower() == "set_config":
                hits.setdefault(node.lineno, "reach:set_config")
        elif (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and node.value.strip().strip('"').lower() == "session_replication_role"
        ):
            hits.setdefault(node.lineno, "reach:replication_role")
    return hits


#: A Core table whose name the rule cannot resolve: it may be an audit table.
_RUN_TIME_TABLE = "\x00"


def _core_mutations(tree: ast.AST, tables: frozenset[str]) -> dict[int, str]:
    """`{line: target}` of each SQLAlchemy Core statement on an audit table: a
    `delete`/`update` of a `table(...)`/`Table(...)` object on one (an alias of it, or
    `<metadata>.tables["<t>"]`, too), called on it (`sa.table("<t>").delete()`,
    through a name or not) or given to it (`sa.delete(t)`, under any import name); a
    `DropTable(...)` or a `.drop(...)` of one; and any `drop_all(...)` (#4032)."""
    names = _resolve_simple_name_constants(tree)
    imported = {"delete", "update", "DropTable", "table", "Table"}
    canonical = {name: name for name in imported}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(
            "sqlalchemy"
        ):
            canonical |= {
                alias.asname: alias.name
                for alias in node.names
                if alias.asname and alias.name in imported
            }
    for node in ast.walk(tree):  # `t = sa.table`: the name is the constructor
        if (
            isinstance(node, ast.Assign)
            and isinstance(node.value, ast.Attribute)
            and node.value.attr in {"table", "Table"}
        ):
            canonical |= {
                t.id: node.value.attr for t in node.targets if isinstance(t, ast.Name)
            }
    bound: dict[str, str] = {}

    def audit_table(node: ast.AST | None) -> str | None:
        if isinstance(node, ast.Name):
            return bound.get(node.id)
        if (
            isinstance(node, ast.Subscript)
            and isinstance(node.value, ast.Attribute)
            and node.value.attr == "tables"
        ):
            value = _argument_value(node.slice, names)
            return value if value in tables else None
        if not isinstance(node, ast.Call):
            return None
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr == "alias":
            return audit_table(func.value)
        if isinstance(func, ast.Name):  # an import alias, or a name bound to it
            callee: str | None = canonical.get(func.id, func.id)
        else:
            callee = func.attr if isinstance(func, ast.Attribute) else None
        if callee in {"table", "Table"} and (first := _core_table_name(node)):
            if not isinstance(first, ast.Constant) and not (
                isinstance(first, ast.Name) and first.id in names
            ):
                return _RUN_TIME_TABLE  # a rebound name, a parameter, a list, an expression
            value = _argument_value(first, names)
            return value if value in tables else None
        return None

    for _ in range(2):  # a name bound to an alias of a bound name
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and (table := audit_table(node.value)):
                bound |= {t.id: table for t in node.targets if isinstance(t, ast.Name)}

    hits: dict[int, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name):
            callee: str | None = canonical.get(func.id, func.id)
        else:
            callee = func.attr if isinstance(func, ast.Attribute) else None
        if callee == "drop_all":
            hits.setdefault(
                node.lineno, "every table a MetaData holds, the append-only ones too"
            )
            continue
        if callee not in {"delete", "update", "DropTable", "drop"}:
            continue
        on = func.value if isinstance(func, ast.Attribute) else None
        table = (audit_table(on) if on is not None else None) or next(
            (found for arg in node.args if (found := audit_table(arg))), None
        )
        if table is not None and (callee != "drop" or on is not None):
            hits.setdefault(
                node.lineno,
                (
                    "a table it names only at run time"
                    if table == _RUN_TIME_TABLE
                    else f"append-only table '{table}'"
                ),
            )
    return hits


# Populated from `tools/ci/security-sensitive-tables.txt` when present;
# migrations touching these need the `security-review` label (flagged, not
# blocked, by this tool — the label/reviewer gate is enforced elsewhere).
_DEFAULT_SECURITY_SENSITIVE_TABLES_PATH = Path(__file__).with_name(
    "security-sensitive-tables.txt"
)


@dataclass(frozen=True)
class LintFinding:
    code: str
    path: Path
    message: str

    def render(self) -> str:
        return f"{self.code}: {self.path}: {self.message}"


def _source_bytes(path: Path) -> bytes:
    """A revision's bytes with every line ending as LF, as the compiler reads them."""
    return path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def _read_revision(path: Path) -> str:
    """A revision's text as the import system reads it: its declared encoding, a byte-order
    mark that is not code, its line endings as LF."""
    return importlib.util.decode_source(_source_bytes(path))


def _tree_of(source: str | bytes) -> str | None:
    """The dump of the tree Python compiles from `source`, None where it compiles none or
    cannot dump it: `ast.dump` writes an integer constant in decimal, which Python refuses
    past `sys.get_int_max_str_digits()` digits (a long hex literal) with `ValueError`.
    """
    try:
        return ast.dump(ast.parse(source))
    except (SyntaxError, ValueError, RecursionError):
        return None


def _reads_as_utf8(path: Path) -> bool:
    """Whether the revision is UTF-8 source the lint reads as Python compiles it: the import
    system reads it as UTF-8 (no declaration, a byte-order mark, or UTF-8 declared under any
    of its names), all of it decodes, and the tree Python compiles from its bytes is the one
    parsed from the lint's text. An encoding Python cannot name reads as not."""
    try:
        encoding, _ = tokenize.detect_encoding(io.BytesIO(_source_bytes(path)).readline)
        if codecs.lookup(encoding).name not in {"utf-8", "utf-8-sig"}:
            return False
        text = _read_revision(path)  # the rules' own reader: one text for both
    except (SyntaxError, UnicodeDecodeError):
        return False
    return _tree_of(path.read_bytes()) == _tree_of(text)


def _read_sensitive_tables(path: Path) -> frozenset[str]:
    if not path.is_file():
        return frozenset()
    names = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            names.add(stripped)
    return frozenset(names)


def _line_has_contract_phase_nearby(
    lines: list[str], idx: int, window: int = 3
) -> bool:
    """A `# cv:contract-phase:` comment on the same line or within `window`
    lines above/below the offending call counts as justification — matches
    how engineers naturally annotate a multi-line `op.*(...)` call."""
    lo = max(0, idx - window)
    hi = min(len(lines), idx + window + 1)
    return any(_CONTRACT_PHASE_RE.search(lines[i]) for i in range(lo, hi))


def check_if_not_exists(paths: list[Path]) -> list[LintFinding]:
    findings: list[LintFinding] = []
    for path in paths:
        text = _read_revision(path)
        # At "\n" only, as the AST numbers lines: `splitlines()` also breaks at a form feed
        # and would number every later line one too far (#4032).
        for lineno, line in enumerate(text.split("\n"), start=1):
            if _IF_NOT_EXISTS_RE.search(line) and not _CREATE_EXTENSION_RE.search(line):
                findings.append(
                    LintFinding(
                        code="CI-MIG-005",
                        path=path,
                        message=(
                            f"line {lineno}: 'IF NOT EXISTS' is never used in "
                            "migrations — Alembic owns state (21-database-schema.md §9)"
                        ),
                    )
                )
    return findings


def _table_mentioned(line: str, tables: frozenset[str]) -> str | None:
    for table in tables:
        if re.search(rf"['\"]{re.escape(table)}['\"]", line):
            return table
    return None


def check_audit_table_integrity(
    paths: list[Path],
    forbidden_tables: frozenset[str] = _FORBIDDEN_DESTRUCTIVE_TABLES,
) -> list[LintFinding]:
    """C-5.7: audit tables are append-only — no `UPDATE`/`DELETE` grants, no
    dropping/mutating audit history, however the operation is spelled.

    Reads every string literal in the file (via `ast`, so multi-line
    `op.execute(\n "...")`, an indirected `SQL = "..."; op.execute(SQL)`, and
    f-string literal parts are all covered) as SQL statements, split at each `;`
    outside quotes, comments and `$$` bodies, never at a blank line. A statement
    that mutates and names an audit table as an identifier (quoted, qualified,
    after `ONLY`, second in a list) is a finding, and so is SQL nested in one: a
    `DO` body, `EXECUTE '...'`, or `format(...)` with the table as an argument
    (`_audit_mutations`). A mutating grant on `ALL TABLES IN SCHEMA` is always
    one, and so is a view over an audit table that does not run as its invoker, or
    any view switched to run as its owner. Alembic operations and SQLAlchemy Core
    statements are read from the AST (`_alembic_findings`, `_core_mutations`).

    There is no escape hatch: a genuine `CREATE TABLE`/`CREATE INDEX` on an
    audit table never mutates existing rows, so it is no mutation, but any
    mutation is always forbidden — no comment, marker or annotation of any kind
    suppresses a finding here. A trigger or a rule on an audit table is a mutation of
    it. Defining, replacing, altering or dropping one of the guard functions
    (`_AUDIT_FUNCTIONS`), or a routine named as a function the hash chain calls
    (`_CHAIN_CALLEES`), is a finding too, and so is a statement that reaches the
    tables or their guards without naming them (`_reach`). The one revision that
    creates the audit tables and those functions, `_AUDIT_OWNER_REVISION`
    (`0003_audit_log`), is exempt for three statement kinds, wherever they stand in
    it: `CREATE TRIGGER` on the audit tables, `DROP TABLE` and `DROP TRIGGER` on
    them, and the guard functions' DDL. It is the file of that name whose
    module-level `revision` says so, the file the migrations lockfile pins. Every
    other statement in it is checked. The revision that replaces
    `audit_chain()`, `_CHAIN_HARDENING_REVISION`, named as the owner is, is exempt
    while it holds nothing but the function text and the restore its pins hash
    (`_chain_hardening_deviations`); otherwise each line that deviates is a finding
    and the revision is read as any other. A revision is read as the import system
    reads it, and one the rule cannot read is refused (`_unreadable`): one that is not
    UTF-8 source read as Python compiles it (`_reads_as_utf8`), does not parse or nests
    too deeply. So is a statement it cannot read: a mutation whose target is named
    only at run time, a body's opaque `EXECUTE`, a block comment nested in another, a
    Unicode-escaped name and a body in another language that names an audit table
    (`_audit_mutations`). Strings built in Python are read whole (`_built_string`),
    and a verb Python computes counts what its statement names. `op` is followed
    through an alias, `alembic.op`, a rebinding and `getattr`; any other use of it is
    refused (`_untracked_op`)."""
    findings: list[LintFinding] = []
    for path in paths:
        try:
            findings.extend(_audit_findings(path, forbidden_tables))
        except RecursionError:  # refused alone: the other files' findings still print
            findings.append(_unreadable(path, "nests too deeply to read"))
    return findings


#: What a finding of `_audit_mutations` that names no table targets.
_REACHES = {
    "*": "every table of a schema, the append-only ones too",
    "reach:role": "a role's membership or a superuser or role-creating attribute, "
    "which hands over the privileges on the append-only tables",
    "reach:schema": "a schema, its owner or its objects, the append-only tables too",
    "reach:owned": "every object a role owns, the append-only tables too",
    "reach:pgcrypto": "the extension the audit hash chain hashes with",
    "reach:view_owner": "a view switched to read its tables with its owner's "
    "privileges, which a grant on it hands over",
    "reach:default_privileges": "a mutating privilege every table created later gets by "
    "default, a new append-only table too",
    "reach:replication_role": "the setting that turns the append-only tables' triggers "
    "off (session_replication_role)",
    "reach:set_config": "a setting set through set_config() or under a computed name, "
    "which the rule cannot read: it could turn the append-only tables' triggers off",
    "reach:event_trigger": "an event trigger, which runs on later DDL, the append-only "
    "tables' too",
    "reach:search_path": "the search_path a role or a database resolves the audit "
    "hash chain's calls through",
    "reach:view": "a view over an append-only table that runs with its owner's "
    "privileges, so a grant on it reaches the table: declare security_invoker",
    "dynamic": "a table it names only at run time (a placeholder, a concatenation, a "
    "computed verb or nothing where the name goes): write the statement whole, its "
    "verb and its table in one literal",
    "unicode": "a name or a string spelled with Unicode escapes (U&), which the rule "
    "cannot read: spell it plainly",
    "comment": "a block comment nested in another, which the rule cannot read: "
    "un-nest it",
}


def _unreadable(path: Path, why: str) -> LintFinding:
    """A revision the rule cannot read is refused (#4032): any statement in it could
    mutate an append-only table, and nothing else reads it in CI before Alembic."""
    return LintFinding(
        code="CI-MIG-003",
        path=path,
        message=(
            f"the revision {why}: refused, the audit-table rule cannot read it "
            "(C-5.7, ADR-0013 rule 9)"
        ),
    )


def _audit_findings(path: Path, forbidden_tables: frozenset[str]) -> list[LintFinding]:
    """CI-MIG-003's findings for one revision (`check_audit_table_integrity`)."""
    if not _reads_as_utf8(path):
        return [_unreadable(path, "does not read as UTF-8 source")]
    source = _read_revision(path)
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        return [_unreadable(path, "is not Python the rule can parse")]
    # The owner and the chain's hardening revision are the files the migrations
    # lockfile pins by name and bytes, and each says so as Alembic reads it: another
    # revision cannot claim their exemptions.
    revision = _revision_id(tree)
    owner = path.stem == _AUDIT_OWNER_REVISION and revision == _AUDIT_OWNER_REVISION
    findings: list[LintFinding] = []
    if path.stem == _CHAIN_HARDENING_REVISION == revision:
        deviations = _chain_hardening_deviations(tree)
        if not deviations:
            return []
        findings += [
            LintFinding(
                code="CI-MIG-003",
                path=path,
                message=(
                    f"line {line}: {_CHAIN_HARDENING_REVISION} may hold nothing but its "
                    "two pinned audit_chain() statements, so it is read as any revision "
                    "(C-5.7, ADR-0013 rule 9)"
                ),
            )
            for line in deviations
        ]

    # A docstring never runs, unless the revision reads one (`__doc__`, `getdoc`),
    # and a piece of a bigger string is read with it: their open targets and body
    # languages are not read on their own.
    docs_run = "__doc__" in source or "getdoc" in source
    prose = _fragments(tree) | {
        (node.lineno, node.value.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
        and not docs_run
    }
    for lineno, literal, unresolved in _iter_string_literals(path, source):
        statements = [_normalise_sql(s) for s in _sql_split(literal)]
        if unresolved and any(_DYNAMIC_MUTATION_RE.search(s) for s in statements):
            findings.append(
                LintFinding(
                    code="CI-MIG-003",
                    path=path,
                    message=(
                        f"line {lineno}: dynamic table name in an "
                        "audit-sensitive statement (mutation keyword "
                        "with an unresolved interpolated target) — "
                        "forbidden, resolve to a literal table name "
                        "or refactor (C-5.7, ADR-0013 rule 9)"
                    ),
                )
            )
            continue
        executable = (lineno, literal) not in prose
        hits = _audit_mutations(
            literal, forbidden_tables, owner=owner, executable=executable
        )
        for table in sorted(hits):
            if table in _REACHES:
                target = _REACHES[table]
            elif table.startswith("fn:"):
                target = f"the append-only guard function '{table[3:]}'"
            elif table.startswith("callee:"):
                target = f"the function '{table[7:]}' the audit hash chain calls"
            else:
                target = f"append-only table '{table}'"
            findings.append(
                LintFinding(
                    code="CI-MIG-003",
                    path=path,
                    message=(
                        f"line {lineno}: raw-SQL statement targets {target} — "
                        "forbidden regardless of annotation (C-5.7, ADR-0013 rule 9)"
                    ),
                )
            )

    operations = {
        **{line: _REACHES[reach] for line, reach in _python_settings(tree).items()},
        **_alembic_findings(tree, forbidden_tables, source.split("\n")),
        **_core_mutations(tree, forbidden_tables),
    }
    for line, target in sorted(operations.items()):
        findings.append(
            LintFinding(
                code="CI-MIG-003",
                path=path,
                message=(
                    f"line {line}: operation targets {target} — forbidden "
                    "regardless of annotation (C-5.7, ADR-0013 rule 9)"
                ),
            )
        )
    return list(dict.fromkeys(findings))  # a built string repeats its parts' findings


def check_destructive_annotations(
    paths: list[Path],
    forbidden_tables: frozenset[str] = _FORBIDDEN_DESTRUCTIVE_TABLES,
) -> list[LintFinding]:
    findings: list[LintFinding] = []
    drops = frozenset({"drop_column", "drop_table", "drop_index", "drop_constraint"})
    for path in paths:
        source = _read_revision(path)
        # Numbered as the AST numbers them: `splitlines()` would also split at a form feed
        # or a Unicode line separator, and pair each index with another line's call.
        lines = source.split("\n")
        try:  # the call's arguments, from the line it starts on, however it wraps
            audit_drops = _op_targets(ast.parse(source), drops, forbidden_tables)
        except (SyntaxError, RecursionError):  # the audit rule refuses such a revision
            audit_drops = {}
        for idx, line in enumerate(lines):
            is_destructive = bool(_DESTRUCTIVE_OP_RE.search(line))
            is_narrowing_type = bool(_ALTER_COLUMN_TYPE_RE.search(line))
            is_non_nullable_add = (
                bool(_ADD_COLUMN_RE.search(line))
                and _NULLABLE_FALSE_RE.search(line)
                and not _SERVER_DEFAULT_RE.search(line)
            )

            if not (is_destructive or is_narrowing_type or is_non_nullable_add):
                continue

            forbidden_hit = audit_drops.get(idx + 1) or _table_mentioned(
                line, forbidden_tables
            )
            if is_destructive and forbidden_hit is not None:
                findings.append(
                    LintFinding(
                        code="CI-MIG-003",
                        path=path,
                        message=(
                            f"line {idx + 1}: destructive op targets append-only "
                            f"table '{forbidden_hit}' — forbidden regardless of "
                            "annotation (ADR-0013 rule 9, security notes)"
                        ),
                    )
                )
                continue

            if not _line_has_contract_phase_nearby(lines, idx):
                findings.append(
                    LintFinding(
                        code="CI-MIG-003",
                        path=path,
                        message=(
                            f"line {idx + 1}: destructive/non-additive operation "
                            "with no '# cv:contract-phase: <release>' annotation "
                            "(ADR-0013 rule 9)"
                        ),
                    )
                )
    return findings


def check_security_sensitive(
    paths: list[Path],
    sensitive_tables: frozenset[str] | None = None,
) -> list[LintFinding]:
    """Non-blocking flag (CI-MIG-006, informational): migrations touching
    security-sensitive tables need mandatory Security review per
    `02-definition-of-ready-done.md` §4.1. Returned as findings with code
    'CI-MIG-006' so the caller can choose to warn rather than fail.

    A revision touches a table when a string literal in it names the table as
    an identifier (see `_sql_identifiers`): in raw SQL, unquoted, double-quoted
    or schema-qualified (`CREATE TABLE account_profiles`), or as an Alembic
    argument (`op.add_column("orders", ...)`). A docstring, a Python or SQL
    comment, and a name that only the text of a `'...'` literal mentions are
    prose, not a touch, unless the literal opens with an SQL command: then it
    is read as SQL, so such prose can add a flag, never hide one; `$$` text is
    always read as code. A revision Python cannot parse, or one nested too deeply
    to read, has every word read as a name (fail-closed). One finding per table
    per file, ordered by table.
    """
    tables = sensitive_tables
    if tables is None:
        tables = _read_sensitive_tables(_DEFAULT_SECURITY_SENSITIVE_TABLES_PATH)
    if not tables:
        return []
    findings: list[LintFinding] = []
    for path in paths:
        source = _read_revision(path)
        try:
            ast.parse(source, filename=str(path))
            names = set()
            literals = _iter_string_literals(path, source, skip_docstrings=True)
            for _, literal, _ in literals:
                names |= _sql_identifiers(literal)
        except (SyntaxError, RecursionError):
            # Not Python, or nested too deeply to read: every word, fail-closed.
            names = {word.lower() for word in _WORD_RE.findall(source)}
        for table in sorted(names & tables):
            findings.append(
                LintFinding(
                    code="CI-MIG-006",
                    path=path,
                    message=(
                        f"touches security-sensitive table '{table}' — "
                        "requires mandatory Security review (DoR §4.1)"
                    ),
                )
            )
    return findings


def check_versions_dir(versions_dir: Path) -> list[LintFinding]:
    """CI-MIG-003: the versions directory holds revisions' Python source only, since
    anything else may be loaded without being read: a file of another kind (a compiled
    module, a path file), a package's `__init__.py` or a module in a subdirectory.
    Bytecode caches (`__pycache__`) and the `.gitkeep` placeholder are not revisions."""
    findings: list[LintFinding] = []
    for path in sorted(versions_dir.rglob("*")):
        relative = path.relative_to(versions_dir)
        if "__pycache__" in relative.parts or not path.is_file():
            continue
        if path.name == ".gitkeep" or (
            path.suffix == ".py"
            and len(relative.parts) == 1
            and path.name != "__init__.py"  # `_iter_migration_files` skips it
        ):
            continue
        findings.append(
            LintFinding(
                code="CI-MIG-003",
                path=path,
                message=(
                    "not a revision's Python source in the versions directory: "
                    "refused, the audit-table rule cannot read it (C-5.7, ADR-0013 rule 9)"
                ),
            )
        )
    return findings


def _iter_migration_files(versions_dir: Path) -> list[Path]:
    return sorted(p for p in versions_dir.glob("*.py") if p.name != "__init__.py")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--versions-dir",
        type=Path,
        default=Path("candleviewer/migrations/versions"),
        help="Directory containing Alembic version files (default: %(default)s)",
    )
    args = parser.parse_args(argv)

    versions_dir: Path = args.versions_dir
    if not versions_dir.is_dir():
        print(f"CI-MIG-000: versions dir not found: {versions_dir}", file=sys.stderr)
        return 2

    paths = _iter_migration_files(versions_dir)
    # A revision that is not UTF-8 source gets the audit rule's one refusal; no other
    # reader opens it.
    readable = [path for path in paths if _reads_as_utf8(path)]
    findings = check_versions_dir(versions_dir)
    findings.extend(check_if_not_exists(readable))
    findings.extend(check_destructive_annotations(readable))
    findings.extend(check_audit_table_integrity(paths))
    security_findings = check_security_sensitive(readable)

    for finding in findings:
        print(finding.render(), file=sys.stderr)
    for finding in security_findings:
        print(f"WARN {finding.render()}", file=sys.stderr)

    if findings:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
