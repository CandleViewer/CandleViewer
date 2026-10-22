# Outside storage/repositories: the rule's path scope does not reach a route module.
from sqlalchemy.exc import IntegrityError


class Conflict(Exception):
    pass


def route(session):
    try:  # ok: cv-storage-driver-chain
        session.execute("INSERT")
    except IntegrityError as exc:
        raise Conflict() from exc
