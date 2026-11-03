# Fixture for cv-oms-env-branch in the OMS composition modules (`oms_*.py`), in a file with PEP 695
# syntax, where Semgrep parses another way and a string metavariable loses its quotes (#3549).
from candleviewer.config import ProcessEnvironment

type Figures = object

_NOT_LIVE = frozenset({"demo", "testnet"})


def figures_for[T](env: str, none: T, served: T, live_default: str) -> T:
    if env not in _NOT_LIVE and none is None:  # ok: cv-oms-env-branch
        raise ValueError(env)
    if env == "demo":  # ruleid: cv-oms-env-branch
        return served
    if env is ProcessEnvironment.TESTNET:  # ruleid: cv-oms-env-branch
        return served
    if env == "live":  # ruleid: cv-oms-env-branch
        raise ValueError(env)
    elif none is None:
        return served
    if env == live_default:  # ok: cv-oms-env-branch
        return none
    return none if env not in _NOT_LIVE else served  # ruleid: cv-oms-env-branch
