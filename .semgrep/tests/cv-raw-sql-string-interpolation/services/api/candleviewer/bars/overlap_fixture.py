"""The raw rule fires on `sa.text(...)` splices under `bars/`; cv-no-raw-sql-interpolation (E12) is
quiet there (its fixture holds the `ok` lines), so each line is reported once (#4548)."""

import sqlalchemy as sa
from sqlalchemy import text


def bad_in_bars(symbol: str, bar_param: str, limit: int) -> None:
    sa.text(f"SELECT * FROM bars_time WHERE symbol = '{symbol}'")  # ruleid: cv-raw-sql-string-interpolation
    sa.text("SELECT * FROM bars_time WHERE bar_param = '%s'" % bar_param)  # ruleid: cv-raw-sql-string-interpolation
    sa.text("SELECT * FROM klines LIMIT {}".format(limit))  # ruleid: cv-raw-sql-string-interpolation
    sa.sql.text(f"SELECT * FROM bars_time WHERE symbol = '{symbol}'")  # ruleid: cv-raw-sql-string-interpolation
    sa.sql.expression.text("SELECT * FROM klines LIMIT {}".format(limit))  # ruleid: cv-raw-sql-string-interpolation
    text(f"SELECT * FROM bars_time WHERE symbol = '{symbol}'")  # ruleid: cv-raw-sql-string-interpolation


def bad_variable_operand_in_bars(prefix: str, template: str, x: str) -> None:
    # Caught by cv-no-raw-sql-interpolation on `main` before the E12 exclusion; one rule now.
    sa.text(prefix + "SELECT * FROM bars_time")  # ruleid: cv-raw-sql-string-interpolation
    sa.text(template % x)  # ruleid: cv-raw-sql-string-interpolation
    sa.text(template.format(x))  # ruleid: cv-raw-sql-string-interpolation
    sa.sql.text(prefix + "SELECT * FROM bars_time")  # ruleid: cv-raw-sql-string-interpolation
    sa.sql.expression.text(template % x)  # ruleid: cv-raw-sql-string-interpolation
    text(template.format(x))  # ruleid: cv-raw-sql-string-interpolation


def ok_in_bars(symbol: str) -> None:
    sa.text("SELECT * FROM bars_time WHERE symbol = :symbol")  # ok: cv-raw-sql-string-interpolation
