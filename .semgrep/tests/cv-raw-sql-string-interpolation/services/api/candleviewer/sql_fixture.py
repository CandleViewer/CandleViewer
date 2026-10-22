"""Fixtures for cv-raw-sql-string-interpolation.
Run with: python tools/ci/check_semgrep_rule_tests.py (covers cv-raw-sql-string-interpolation)
"""


def bad_fstring(conn: object, account_id: str) -> None:
    conn.execute(f"SELECT * FROM orders WHERE account_id = {account_id}")  # ruleid: cv-raw-sql-string-interpolation


def bad_percent(conn: object, account_id: str) -> None:
    conn.execute("SELECT * FROM orders WHERE account_id = %s" % account_id)  # ruleid: cv-raw-sql-string-interpolation


def bad_format(conn: object, account_id: str) -> None:
    conn.execute("SELECT * FROM orders WHERE account_id = {}".format(account_id))  # ruleid: cv-raw-sql-string-interpolation


def bad_concat(conn: object, account_id: str) -> None:
    conn.execute("SELECT * FROM orders WHERE account_id = " + account_id)  # ruleid: cv-raw-sql-string-interpolation


def ok_parameterised(conn: object, account_id: str) -> None:
    params = {"account_id": account_id}
    query = "SELECT * FROM orders WHERE account_id = :account_id"
    conn.execute(query, params)  # ok: cv-raw-sql-string-interpolation
