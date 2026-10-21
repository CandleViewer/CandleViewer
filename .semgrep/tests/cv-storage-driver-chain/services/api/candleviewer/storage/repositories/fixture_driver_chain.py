# Fixtures for cv-storage-driver-chain (#2748): a driver error chained or re-raised as it is.
import sqlalchemy as sa
from sqlalchemy import exc as sa_exc
from sqlalchemy.exc import DataError, DBAPIError


class NameTaken(Exception):
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


def re_raised_by_name(session):
    try:  # ruleid: cv-storage-driver-chain
        session.execute("UPDATE")
    except DataError as exc:
        raise exc


def bare_re_raise_after_a_check(session, sqlstate_of):
    try:  # ruleid: cv-storage-driver-chain
        session.execute("UPDATE")
    except DBAPIError as exc:
        if sqlstate_of(exc) != "40P01":
            raise


def bare_re_raise_of_a_tuple(session):
    try:  # ruleid: cv-storage-driver-chain
        session.execute("DELETE")
    except (OSError, sa_exc.SQLAlchemyError):
        raise


def typed_from_none(session, sqlstate_of):
    try:  # ok: cv-storage-driver-chain
        session.execute("INSERT")
    except sa_exc.IntegrityError as exc:
        failure = NameTaken(sqlstate_of(exc))
    else:
        return None
    raise failure


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
