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
    CI-MIG-003  destructive operation without a `# cv:contract-phase:` annotation
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
import hashlib
import importlib.util
import io
import itertools
import re
import sys
import tokenize
from collections.abc import Iterator
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
# dynamic-table check below and never the static per-table patterns. NUL is not
# a word character, so the pattern ends in `(?!\w)` — a trailing `\b` would
# silently never match at end-of-string or before whitespace.
_UNRESOLVED_PLACEHOLDER = "\x00"
_DYNAMIC_MUTATION_RE = re.compile(
    rf"\b(?:DELETE\s+FROM|UPDATE|DROP\s+TABLE|TRUNCATE(?:\s+TABLE)?|ALTER\s+TABLE)"
    rf"\s+{_TABLE_QUALIFIER}{re.escape(_UNRESOLVED_PLACEHOLDER)}(?!\w)"
    rf"|\bGRANT\s+(?:ALL(?:\s+PRIVILEGES)?|[A-Za-z, ]*?\b(?:UPDATE|DELETE|TRUNCATE)\b[A-Za-z, ]*?)"
    rf"\s+ON\s+{_TABLE_QUALIFIER}{re.escape(_UNRESOLVED_PLACEHOLDER)}(?!\w)",
    re.IGNORECASE,
)


# There is deliberately no escape hatch for audit-table mutations: C-5.7
# forbids UPDATE/DELETE/DROP/TRUNCATE/ALTER/mutating GRANT on an audit table
# unconditionally, so no annotation (however spelled) may suppress a genuine
# finding. A previous `# cv:audit-exempt:` marker was removed because it was
# indistinguishable, at review time, from a bypass of a real mutation — see
# PR #1518 review history.


def _resolve_simple_name_constants(tree: ast.AST) -> dict[str, str]:
    """Map `Name = Constant(str)` module/function-level assignments
    (`tbl = "audit_log"`) to their string value, so an f-string placeholder
    that is just a `Name` reference can be substituted before matching.
    Last assignment wins if a name is reassigned; conditional/loop-only
    assignments are still collected (fail-closed: over-resolving only ever
    adds table names to check, it never removes a real finding)."""
    values: dict[str, str] = {}
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Assign)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    values[target.id] = node.value.value
    return values


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
    return literals


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
    r"--[^\n]*"  # line comment
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
            text = literal[literal.index("'") + 1 : -1].replace("''", "'")
            if _BARE_NAME_RE.fullmatch(text) or _SQL_COMMAND_RE.match(text):
                names |= _sql_identifiers(text)
    return names


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


def _code_words(statement: str) -> list[str]:
    """The statement's words outside comments, quotes and `$$` bodies, upper-cased."""
    return [
        token["word"].upper()
        for token in _SQL_TOKEN_RE.finditer(statement)
        if token["word"] is not None
    ]


def _nested_sql(statement: str) -> list[str]:
    """The SQL inside `statement`: each `$$` body, and each `'...'` literal that is
    SQL (it opens with one of `SQL_COMMANDS`, as `EXECUTE '...'` writes it)."""
    nested: list[str] = []
    for token in _SQL_TOKEN_RE.finditer(statement):
        literal = token["string"] or token["estring"]
        if token["body"] is not None:
            nested.append(token["body"])
        elif literal is not None:
            text = literal[literal.index("'") + 1 : -1].replace("''", "'")
            if _SQL_COMMAND_RE.match(text):
                nested.append(text)
    return nested


# A statement mutates when its first word does, or when a `GRANT` hands out a
# mutating privilege; fail-closed for the forms that hide the verb further in: a
# data-modifying `WITH`, an `EXPLAIN ANALYZE`, which runs its statement, a prepared
# statement, a `COPY` of a `RETURNING` query, a rule's action, and an upsert's
# `DO UPDATE`.
_MUTATING = frozenset({"DELETE", "UPDATE", "TRUNCATE", "DROP", "ALTER", "MERGE"})
_CARRIERS = frozenset({"WITH", "EXPLAIN", "PREPARE", "COPY"})
# A plpgsql or SQL-standard body, or a rule, starts a statement after these words
# without a `;` before it: `BEGIN DELETE ...`, `IF c THEN DELETE ...`, `LOOP UPDATE
# ...`, `FOR r IN DELETE ... RETURNING ...`, `RETURN QUERY DELETE ...`, `BEGIN ATOMIC
# DELETE ...`, `DO ALSO DELETE ...`. So the chunk's first word is not its only verb.
_BLOCK_OPENERS = frozenset(
    {"BEGIN", "THEN", "ELSE", "LOOP", "IN", "QUERY", "ATOMIC", "ALSO", "INSTEAD"}
)
_MUTATING_GRANTS = frozenset({"UPDATE", "DELETE", "TRUNCATE", "ALL"})
# A placeholder in dynamic SQL: its target is an argument, read where it is passed.
_PLACEHOLDER_RE = re.compile(r"%[IsL]|\$\d+")
#: The revision that creates the audit tables and their guard functions (21 §3.10).
#: It is exempt for exactly two statement kinds: its downgrade's `DROP TABLE` and
#: `DROP TRIGGER` on the audit tables, behind its refusal to drop a table that holds a
#: row, and the definition and drop of the guard functions. No other revision may do
#: either. It is merged and pinned by the migrations lockfile (C-5.4).
_AUDIT_OWNER_REVISION = "0003_audit_log"
#: The functions the audit tables' append-only triggers and hash chain run: replacing,
#: altering or dropping one neuters them without naming a table. `audit_field` encodes
#: each field `audit_chain` hashes.
_AUDIT_FUNCTIONS = frozenset(
    {"forbid_mutation", "audit_refuse_truncate", "audit_chain", "audit_field"}
)
_FUNCTION_DDL = (["CREATE", "FUNCTION"], ["DROP", "FUNCTION"], ["ALTER", "FUNCTION"])
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


def _mutates(words: list[str]) -> bool:
    if not words:
        return False
    first = words[0]
    if first in _MUTATING:
        return True
    if first == "GRANT":
        privileges = words[1 : words.index("ON")] if "ON" in words else words[1:]
        return bool(_MUTATING_GRANTS & set(privileges))
    rule = words[:2] == ["CREATE", "RULE"] or words[:4] == [
        "CREATE",
        "OR",
        "REPLACE",
        "RULE",
    ]
    if first in _CARRIERS or rule:
        return bool({"DELETE", "UPDATE", "MERGE", "TRUNCATE"} & set(words))
    if first == "INSERT":
        return ("DO", "UPDATE") in itertools.pairwise(words)
    return False


def _clauses(words: list[str]) -> Iterator[list[str]]:
    """The statements a `;`-chunk starts: at its first word, and after each block
    opener (`_BLOCK_OPENERS`), each running to the chunk's end. One at a time, so a
    chunk of many openers holds one clause, not all of them."""
    yield words
    for i, word in enumerate(words[:-1]):
        if word in _BLOCK_OPENERS:
            yield words[i + 1 :]


def _schema_wide(words: list[str]) -> bool:
    """`... ON ALL TABLES IN SCHEMA ...`: it reaches every table, the audit ones too."""
    seq = ["ALL", "TABLES", "IN", "SCHEMA"]
    return any(words[i : i + len(seq)] == seq for i in range(len(words)))


def _head_identifiers(statement: str) -> set[str]:
    """The names `statement` itself uses, outside its quotes and `$$` bodies."""
    names: set[str] = set()
    for token in _SQL_TOKEN_RE.finditer(statement):
        if token["word"] is not None:
            names.add(token["word"].lower())
        elif token["quoted"] is not None:
            names.add(token["quoted"].replace('""', '"'))
    return names


def _redefined_functions(words: list[str], statement: str) -> set[str]:
    """The guard functions the clause `words` of `statement` defines, replaces, alters
    or drops."""
    if words[:2] in _FUNCTION_DDL or words[:4] == [
        "CREATE",
        "OR",
        "REPLACE",
        "FUNCTION",
    ]:
        return _head_identifiers(statement) & _AUDIT_FUNCTIONS
    return set()


def _audit_mutations(sql: str, tables: frozenset[str], *, owner: bool) -> set[str]:
    """The audit tables a statement in `sql` mutates (or `*`: every table, by a
    schema-wide grant; `fn:<name>`: a guard function it redefines or drops). A
    statement counts when a clause of it mutates (`_clauses`, `_mutates`: a body or
    a rule starts one mid-statement) and it names an audit table as an identifier
    (`_sql_identifiers`, fail-closed: a subquery's table counts too), or
    when SQL nested in it mutates a placeholder's target and the statement names an
    audit table (`EXECUTE format('DELETE FROM %I', ...)`). Nested SQL is read the
    same way. In the owner revision, its downgrade's drops of the audit tables and
    their triggers, and the guard functions' definitions, are not findings."""
    hits: set[str] = set()
    for statement in _sql_split(sql):
        words = _code_words(statement)
        dynamic = False
        for nested in _nested_sql(statement):
            found = _audit_mutations(nested, tables, owner=owner)
            hits |= found
            if (
                not found
                and _mutates(_code_words(nested))
                and _PLACEHOLDER_RE.search(nested)
            ):
                dynamic = True
        if not owner:
            hits |= {
                f"fn:{name}"
                for clause in _clauses(words)
                for name in _redefined_functions(clause, statement)
            }
        clauses = [clause for clause in _clauses(words) if _mutates(clause)]
        if any(clause[:1] == ["GRANT"] and _schema_wide(clause) for clause in clauses):
            hits.add("*")
            continue
        if owner:
            clauses = [
                clause
                for clause in clauses
                if not (
                    clause[:1] == ["DROP"] and clause[1:2] in (["TABLE"], ["TRIGGER"])
                )
            ]
        if clauses or dynamic:
            hits |= _sql_identifiers(statement) & tables
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


def _core_mutations(tree: ast.AST, tables: frozenset[str]) -> dict[int, str]:
    """`{line: audit table}` of each SQLAlchemy Core `delete`/`update` of a
    `table(...)`/`Table(...)` object on an audit table, called on it
    (`sa.table("<t>").delete()`, through a name or not) or given to it
    (`sa.delete(t)`)."""
    names = _resolve_simple_name_constants(tree)

    def audit_table(node: ast.AST) -> str | None:
        if not isinstance(node, ast.Call) or not node.args:
            return None
        func = node.func
        callee = (
            func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
        )
        first = node.args[0]
        if isinstance(first, ast.Constant):
            value = first.value
        else:
            value = names.get(first.id) if isinstance(first, ast.Name) else None
        if callee in {"table", "Table"} and isinstance(value, str) and value in tables:
            return value
        return None

    bound: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and (table := audit_table(node.value)):
            bound.update({t.id: table for t in node.targets if isinstance(t, ast.Name)})

    def target(node: ast.AST) -> str | None:
        if isinstance(node, ast.Name):
            return bound.get(node.id)
        return audit_table(node)

    hits: dict[int, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        callee = (
            func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
        )
        if callee not in {"delete", "update"}:
            continue
        on = func.value if isinstance(func, ast.Attribute) else None
        table = (target(on) if on is not None else None) or next(
            (found for arg in node.args if (found := target(arg))), None
        )
        if table is not None:
            hits.setdefault(node.lineno, table)
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
    """The dump of the tree Python compiles from `source`, None where it compiles none."""
    try:
        return ast.dump(ast.parse(source))
    except (SyntaxError, RecursionError):
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
        for lineno, line in enumerate(text.splitlines(), start=1):
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
    one. `op.rename_table`/`op.alter_column` calls and SQLAlchemy Core
    `delete`/`update` on an audit `table(...)` are read from the AST.

    There is no escape hatch: a genuine `CREATE TABLE`/`CREATE INDEX` on an
    audit table never mutates existing rows, so it is no mutation, but any
    mutation is always forbidden — no comment, marker or annotation of any kind
    suppresses a finding here. Defining, replacing, altering or dropping one of the
    guard functions (`_AUDIT_FUNCTIONS`) is a finding too. The one revision that creates
    the audit tables and those functions, `_AUDIT_OWNER_REVISION` (`0003_audit_log`), is
    exempt for exactly two statement kinds: its downgrade's `DROP TABLE` and
    `DROP TRIGGER` on the audit tables, and the definition and drop of the functions.
    It is the file of that name whose module-level `revision` says so, the file the
    migrations lockfile pins. Every other statement in it is checked. The revision that
    replaces `audit_chain()`, `_CHAIN_HARDENING_REVISION`, named as the owner is, is
    exempt while it holds nothing but the function text and the restore its pins hash
    (`_chain_hardening_deviations`); otherwise each line that deviates is a finding and
    the revision is read as any other. A revision is read as the import system reads it,
    and one that is not UTF-8 source read as Python compiles it (`_reads_as_utf8`) is
    refused."""
    findings: list[LintFinding] = []
    for path in paths:
        if not _reads_as_utf8(path):
            findings.append(
                LintFinding(
                    code="CI-MIG-003",
                    path=path,
                    message=(
                        "the revision does not read as UTF-8 source: refused, the "
                        "audit-table rule reads revisions as UTF-8 only "
                        "(C-5.7, ADR-0013 rule 9)"
                    ),
                )
            )
            continue
        source = _read_revision(path)
        try:
            tree: ast.Module | None = ast.parse(source, filename=str(path))
        except SyntaxError:
            tree = None
        # The owner is the file the migrations lockfile pins by name and bytes, and
        # it says so as Alembic reads it: another revision cannot claim its exemption.
        owner = (
            tree is not None
            and path.stem == _AUDIT_OWNER_REVISION
            and _revision_id(tree) == _AUDIT_OWNER_REVISION
        )
        if (
            tree is not None
            and path.stem == _CHAIN_HARDENING_REVISION
            and _revision_id(tree) == _CHAIN_HARDENING_REVISION
        ):
            deviations = _chain_hardening_deviations(tree)
            if not deviations:
                continue
            findings.extend(
                LintFinding(
                    code="CI-MIG-003",
                    path=path,
                    message=(
                        f"line {line}: {_CHAIN_HARDENING_REVISION} may hold nothing but "
                        "its two pinned audit_chain() statements, so it is read as any "
                        "revision (C-5.7, ADR-0013 rule 9)"
                    ),
                )
                for line in deviations
            )

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
            for table in sorted(
                _audit_mutations(literal, forbidden_tables, owner=owner)
            ):
                if table == "*":
                    target = "every table of a schema, the append-only ones too"
                elif table.startswith("fn:"):
                    target = f"the append-only guard function '{table[3:]}'"
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

        if tree is None:
            continue
        reshapes = _op_targets(
            tree, frozenset({"rename_table", "alter_column"}), forbidden_tables
        )
        for line, table in sorted(
            {**reshapes, **_core_mutations(tree, forbidden_tables)}.items()
        ):
            findings.append(
                LintFinding(
                    code="CI-MIG-003",
                    path=path,
                    message=(
                        f"line {line}: operation targets append-only "
                        f"table '{table}' — forbidden regardless of "
                        "annotation (C-5.7, ADR-0013 rule 9)"
                    ),
                )
            )
    return findings


def check_destructive_annotations(
    paths: list[Path],
    forbidden_tables: frozenset[str] = _FORBIDDEN_DESTRUCTIVE_TABLES,
) -> list[LintFinding]:
    findings: list[LintFinding] = []
    drops = frozenset({"drop_column", "drop_table", "drop_index", "drop_constraint"})
    for path in paths:
        source = _read_revision(path)
        lines = source.splitlines()
        try:  # the call's arguments, from the line it starts on, however it wraps
            audit_drops = _op_targets(ast.parse(source), drops, forbidden_tables)
        except SyntaxError:
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
    always read as code. A revision Python cannot parse has every word read as
    a name (fail-closed). One finding per table per file, ordered by table."""
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
        except SyntaxError:  # not Python: every word is a name, fail-closed
            names = {word.lower() for word in _WORD_RE.findall(source)}
        else:
            names = set()
            literals = _iter_string_literals(path, source, skip_docstrings=True)
            for _, literal, _ in literals:
                names |= _sql_identifiers(literal)
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
    findings: list[LintFinding] = []
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
