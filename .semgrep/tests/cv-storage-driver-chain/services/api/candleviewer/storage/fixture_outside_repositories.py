# Out of scope for cv-storage-driver-chain: storage code outside the relational adapters.
from sqlalchemy.exc import IntegrityError


class NameTaken(Exception):
    pass


def chained_outside_the_adapters(session):
    try:  # ok: cv-storage-driver-chain
        session.execute("INSERT")
    except IntegrityError as exc:
        raise NameTaken() from exc
