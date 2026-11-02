"""Fixtures for cv-no-raw-sql-interpolation (E12-X03, E12 STRIDE BR-25).
Run with: python tools/ci/check_semgrep_rule_tests.py
"""

import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.sql import text as sub_text
from sqlalchemy.sql.expression import text as expr_text

from candleviewer.storage.sql_identifiers import checked_identifier

_FAMILIES = frozenset({"time", "tick"})


def fstring_bad(symbol, start_us):
    sql = f"SELECT * FROM bars_time WHERE symbol = '{symbol}' AND ts >= {start_us}"  # ruleid: cv-no-raw-sql-interpolation
    return sql


def percent_bad(bar_param):
    return "SELECT ts FROM bars_time WHERE bar_param = '%s'" % bar_param  # ruleid: cv-no-raw-sql-interpolation


def format_bad(limit):
    return "SELECT * FROM klines LIMIT {}".format(limit)  # ruleid: cv-no-raw-sql-interpolation


def concat_bad(symbol):
    return "DELETE FROM bars_time WHERE symbol = '" + symbol  # ruleid: cv-no-raw-sql-interpolation


def bound_params_ok(symbol, start_us):
    sql = "SELECT * FROM bars_time WHERE symbol = $1 AND ts >= $2"  # ok: cv-no-raw-sql-interpolation
    return sql, (symbol, start_us)


def allowlisted_table_ok(kind, symbol):
    if kind not in _FAMILIES:
        raise ValueError(kind)
    sql = f"SELECT * FROM bars_{kind} WHERE symbol = $1"  # ok: cv-no-raw-sql-interpolation
    return sql, (symbol,)


def checked_identifier_ok(table, symbol):
    name = checked_identifier(table)
    return f"SELECT * FROM {name} WHERE symbol = $1", (symbol,)  # ok: cv-no-raw-sql-interpolation


def log_message_ok(symbol):
    return f"selected {symbol} from the catalogue"  # ok: cv-no-raw-sql-interpolation


def sqlalchemy_text_owned_by_the_raw_rule_ok(symbol, bar_param, limit, prefix, template):
    # `cv-raw-sql-string-interpolation` owns every `text(...)` call form, so this rule stays quiet
    # on the same line (#4548): exactly one finding for each.
    text(f"SELECT * FROM bars_time WHERE symbol = '{symbol}'")  # ok: cv-no-raw-sql-interpolation
    sa.text(f"SELECT * FROM bars_time WHERE symbol = '{symbol}'")  # ok: cv-no-raw-sql-interpolation
    sa.text("SELECT * FROM bars_time WHERE bar_param = '%s'" % bar_param)  # ok: cv-no-raw-sql-interpolation
    sa.text("SELECT * FROM klines LIMIT {}".format(limit))  # ok: cv-no-raw-sql-interpolation
    sa.sql.text(f"SELECT * FROM bars_time WHERE symbol = '{symbol}'")  # ok: cv-no-raw-sql-interpolation
    sa.sql.expression.text("SELECT * FROM klines LIMIT {}".format(limit))  # ok: cv-no-raw-sql-interpolation
    sub_text(f"SELECT * FROM bars_time WHERE symbol = '{symbol}'")  # ok: cv-no-raw-sql-interpolation
    expr_text("SELECT * FROM klines LIMIT {}".format(limit))  # ok: cv-no-raw-sql-interpolation
    # Variable template or left operand: still a `text(...)` call, owned by the raw rule.
    sa.text(prefix + "SELECT * FROM bars_time")  # ok: cv-no-raw-sql-interpolation
    sa.text(template % bar_param)  # ok: cv-no-raw-sql-interpolation
    sa.text(template.format(limit))  # ok: cv-no-raw-sql-interpolation
