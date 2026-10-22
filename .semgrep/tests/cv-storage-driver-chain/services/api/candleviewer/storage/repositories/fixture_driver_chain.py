# Fixtures for cv-storage-driver-chain (#2748): a driver error's text let out of an adapter.
import traceback

import asyncpg
import asyncpg as pg  # ruleid: cv-storage-driver-chain
import psycopg
import sqlalchemy as sa
from asyncpg.exceptions import UniqueViolationError  # ruleid: cv-storage-driver-chain
from psycopg import errors as pg_errors  # ruleid: cv-storage-driver-chain
from sqlalchemy import exc as sa_exc
from sqlalchemy.exc import DataError, DBAPIError
from sqlalchemy.exc import IntegrityError as Taken  # ruleid: cv-storage-driver-chain


class NameTaken(Exception):
    pass


class StorageIntegrityError(Exception):
    pass


class IntegrityErrorLike(Exception):
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


def every_other_sqlalchemy_class(session):
    try:  # ruleid: cv-storage-driver-chain
        session.execute("SELECT")
    except sa_exc.ProgrammingError:
        raise
    try:  # ruleid: cv-storage-driver-chain
        session.execute("SELECT")
    except sa_exc.InterfaceError:
        raise
    try:  # ruleid: cv-storage-driver-chain
        session.execute("SELECT")
    except sa_exc.InternalError:
        raise
    try:  # ruleid: cv-storage-driver-chain
        session.execute("SELECT")
    except sa_exc.DatabaseError:
        raise
    try:  # ruleid: cv-storage-driver-chain
        session.execute("SELECT")
    except sa_exc.NotSupportedError:
        raise


def a_psycopg_class(session):
    try:  # ruleid: cv-storage-driver-chain
        session.execute("INSERT")
    except psycopg.errors.UniqueViolation as exc:
        raise NameTaken() from exc


def the_error_in_a_new_one(session):
    try:
        session.execute("INSERT")
    except DBAPIError as exc:
        raise NameTaken(exc) from None  # ruleid: cv-storage-driver-chain


def every_other_text_shape(session, log):
    try:
        session.execute("INSERT")
    except DBAPIError as exc:
        text = repr(exc)  # ruleid: cv-storage-driver-chain
        text = f"{exc!r}"  # ruleid: cv-storage-driver-chain
        text = "failed: %s" % exc  # ruleid: cv-storage-driver-chain
        text = "%s: %s" % ("insert", exc)  # ruleid: cv-storage-driver-chain
        text = "failed: {}".format(exc)  # ruleid: cv-storage-driver-chain
        text = exc.args  # ruleid: cv-storage-driver-chain
        text = exc.statement  # ruleid: cv-storage-driver-chain
        text = exc.params  # ruleid: cv-storage-driver-chain
        text = exc.with_traceback(None)  # ruleid: cv-storage-driver-chain
        text = str(exc.orig)  # ruleid: cv-storage-driver-chain
        text = repr(exc.orig)  # ruleid: cv-storage-driver-chain
        text = f"{exc.orig}"  # ruleid: cv-storage-driver-chain
        text = exc.orig.args  # ruleid: cv-storage-driver-chain
        text = exc.orig.detail  # ruleid: cv-storage-driver-chain
        text = exc.orig.message  # ruleid: cv-storage-driver-chain
        text = exc.orig.pgerror  # ruleid: cv-storage-driver-chain
        text = exc.orig.hint  # ruleid: cv-storage-driver-chain
        log.error("insert failed", error=exc)  # ruleid: cv-storage-driver-chain
        log.error(exc)  # ruleid: cv-storage-driver-chain
        log.exception("insert failed")  # ruleid: cv-storage-driver-chain
        traceback.print_exc()  # ruleid: cv-storage-driver-chain
        raise NameTaken(text) from None


def its_text_in_every_clause_context(session):
    try:
        session.execute("INSERT")
    except DBAPIError as exc:
        raise NameTaken(str(exc)) from None  # ruleid: cv-storage-driver-chain
    else:
        session.commit()
    try:
        session.execute("INSERT")
    except DBAPIError as exc:
        raise NameTaken(str(exc)) from None  # ruleid: cv-storage-driver-chain
    finally:
        session.close()
    try:
        session.execute("INSERT")
    except DBAPIError as exc:
        raise NameTaken(str(exc)) from None  # ruleid: cv-storage-driver-chain
    else:
        session.commit()
    finally:
        session.close()


def exc_info_without_a_name(session, log):
    try:
        session.execute("INSERT")
    except (OSError, DBAPIError):
        log.error("insert failed", exc_info=True)  # ruleid: cv-storage-driver-chain
        raise NameTaken() from None


def its_traceback_without_a_name_in_every_clause_context(session, log):
    try:
        session.execute("INSERT")
    except (OSError, DBAPIError):
        log.exception("insert failed")  # ruleid: cv-storage-driver-chain
        raise NameTaken() from None
    else:
        session.commit()
    try:
        session.execute("INSERT")
    except (OSError, DBAPIError):
        log.exception("insert failed")  # ruleid: cv-storage-driver-chain
        raise NameTaken() from None
    finally:
        session.close()
    try:
        session.execute("INSERT")
    except (OSError, DBAPIError):
        log.exception("insert failed")  # ruleid: cv-storage-driver-chain
        raise NameTaken() from None
    else:
        session.commit()
    finally:
        session.close()


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


def a_class_that_only_starts_like_a_driver_one(session):
    try:  # ok: cv-storage-driver-chain
        session.execute("INSERT")
    except IntegrityErrorLike as exc:
        raise NameTaken() from exc


def uses_the_alias(session):
    try:
        session.execute("INSERT")
    except Taken:
        return None
