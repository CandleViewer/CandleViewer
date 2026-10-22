# Fixtures for cv-storage-driver-chain (#2748): a driver error's text let out of an adapter.
import traceback

import asyncpg
import sqlalchemy as sa
from sqlalchemy import exc as sa_exc
from sqlalchemy.exc import DataError, DBAPIError
from sqlalchemy.exc import IntegrityError as Taken  # ruleid: cv-storage-driver-chain


class NameTaken(Exception):
    pass


class StorageIntegrityError(Exception):
    pass


def chained(session, constraint_of):
    try:  # ruleid: cv-storage-driver-chain
        session.execute("INSERT")
    except sa.exc.IntegrityError as exc:
        raise (NameTaken() if constraint_of(exc) else exc) from exc


def chained_with_finally(session):
    try:  # ruleid: cv-storage-driver-chain
        session.execute("INSERT")
    except sa_exc.IntegrityError as exc:
        raise NameTaken() from exc
    finally:
        session.close()


def chained_with_else(session):
    try:  # ruleid: cv-storage-driver-chain
        session.execute("INSERT")
    except sa_exc.IntegrityError as exc:
        raise NameTaken() from exc
    else:
        session.commit()


def chained_from_the_driver_error(session):
    try:  # ruleid: cv-storage-driver-chain
        session.execute("INSERT")
    except sa_exc.IntegrityError as exc:
        raise NameTaken() from exc.orig


def re_raised_by_name(session):
    try:  # ruleid: cv-storage-driver-chain
        session.execute("UPDATE")
    except DataError as exc:
        raise exc


def re_raised_by_name_with_else_and_finally(session):
    try:  # ruleid: cv-storage-driver-chain
        session.execute("UPDATE")
    except DataError as exc:
        raise exc from None
    else:
        session.commit()
    finally:
        session.close()


def bare_re_raise_after_a_check(session, sqlstate_of):
    try:  # ruleid: cv-storage-driver-chain
        session.execute("UPDATE")
    except DBAPIError as exc:
        if sqlstate_of(exc) != "40P01":
            raise


def bare_re_raise_with_finally(session):
    try:  # ruleid: cv-storage-driver-chain
        session.execute("UPDATE")
    except DBAPIError:
        raise
    finally:
        session.close()


def bare_re_raise_of_a_tuple(session):
    try:  # ruleid: cv-storage-driver-chain
        session.execute("DELETE")
    except (OSError, sa_exc.SQLAlchemyError):
        raise


def implicit_context(session):
    try:  # ruleid: cv-storage-driver-chain
        session.execute("INSERT")
    except sa_exc.IntegrityError:
        raise NameTaken()


def implicit_context_of_a_named_error(session):
    try:  # ruleid: cv-storage-driver-chain
        session.execute("INSERT")
    except sa_exc.IntegrityError as exc:
        raise NameTaken(type(exc).__name__)


def implicit_context_of_a_tuple(session):
    try:  # ruleid: cv-storage-driver-chain
        session.execute("INSERT")
    except (OSError, DBAPIError):
        raise NameTaken()


def a_driver_class(session):
    try:  # ruleid: cv-storage-driver-chain
        session.execute("INSERT")
    except asyncpg.UniqueViolationError as exc:
        raise NameTaken() from exc


def a_pending_rollback(session):
    try:  # ruleid: cv-storage-driver-chain
        session.flush()
    except sa_exc.PendingRollbackError as exc:
        raise NameTaken() from exc


def an_operational_error(session):
    try:  # ruleid: cv-storage-driver-chain
        session.execute("SELECT")
    except sa_exc.OperationalError as exc:
        raise NameTaken() from exc


def a_statement_error(session):
    try:  # ruleid: cv-storage-driver-chain
        session.execute("SELECT")
    except sa_exc.StatementError:
        raise


def a_postgres_error(session):
    try:  # ruleid: cv-storage-driver-chain
        session.execute("SELECT")
    except asyncpg.exceptions.PostgresError as exc:
        raise NameTaken() from exc


def its_text_in_the_message(session):
    try:
        session.execute("INSERT")
    except sa_exc.IntegrityError as exc:
        raise NameTaken(str(exc)) from None  # ruleid: cv-storage-driver-chain


def its_text_in_a_log_line(session, log):
    try:
        session.execute("INSERT")
    except DBAPIError as exc:
        log.error(f"insert failed: {exc}")  # ruleid: cv-storage-driver-chain
        raise NameTaken() from None


def its_traceback_in_a_log_line(session, log):
    try:
        session.execute("INSERT")
    except DBAPIError as exc:
        log.warning("insert failed", exc_info=exc)  # ruleid: cv-storage-driver-chain
        raise NameTaken() from None


def its_traceback_logged_without_a_name(session, log):
    try:
        session.execute("INSERT")
    except sa_exc.IntegrityError:
        log.exception("insert failed")  # ruleid: cv-storage-driver-chain
        raise NameTaken() from None


def its_traceback_formatted(session):
    try:
        session.execute("INSERT")
    except sa_exc.IntegrityError:
        detail = traceback.format_exc()  # ruleid: cv-storage-driver-chain
        raise NameTaken(detail) from None


def typed_from_none(session, sqlstate_of, constraint_of, log):
    try:  # ok: cv-storage-driver-chain
        session.execute("INSERT")
    except sa_exc.IntegrityError as exc:
        log.error("insert failed", error=type(exc).__name__, sqlstate=sqlstate_of(exc))
        raise NameTaken(sqlstate_of(exc), constraint_of(exc)) from None


def typed_after_the_handler(session, sqlstate_of):
    try:  # ok: cv-storage-driver-chain
        session.execute("INSERT")
    except sa_exc.IntegrityError as exc:
        failure = NameTaken(sqlstate_of(exc))
    else:
        return None
    raise failure


def a_domain_error_raised_in_the_try_body(session):
    try:  # ok: cv-storage-driver-chain
        if session.execute("SELECT") is None:
            raise NameTaken()
    except DBAPIError:
        raise NameTaken() from None


def timeout_re_raised_beside_a_typed_driver_error(session):
    try:  # ok: cv-storage-driver-chain
        session.execute("SELECT")
    except TimeoutError:
        raise
    except DBAPIError:
        raise NameTaken() from None


def not_a_driver_error(value):
    try:  # ok: cv-storage-driver-chain
        return int(value)
    except ValueError as exc:
        raise NameTaken() from exc


def a_domain_class_with_a_driver_like_name(session):
    try:  # ok: cv-storage-driver-chain
        session.execute("INSERT")
    except StorageIntegrityError as exc:
        raise NameTaken() from exc


def uses_the_alias(session):
    try:
        session.execute("INSERT")
    except Taken:
        return None
