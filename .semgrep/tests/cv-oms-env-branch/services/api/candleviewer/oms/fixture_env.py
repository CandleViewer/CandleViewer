# Fixture for cv-oms-env-branch (E29-X02): tests of the environment against its values in an OMS
# module; fail-closed self-checks, C-2.11's comparisons of two environments and look-alikes stay
# quiet. A marker sits on the comparison's line.
from candleviewer.config import ProcessEnvironment
from candleviewer.domain.primitives import Environment

_NOT_LIVE = frozenset({"demo", "testnet"})


def branches(env, environment, order, settings, accounts, served, unserved):
    if env == "live":  # ruleid: cv-oms-env-branch
        served()
    if environment != "demo":  # ruleid: cv-oms-env-branch
        served()
    if "testnet" == env:  # ruleid: cv-oms-env-branch
        served()
    if environment is ProcessEnvironment.LIVE:  # ruleid: cv-oms-env-branch
        served()
    if settings.environment == Environment.DEMO:  # ruleid: cv-oms-env-branch
        served()
    if env not in _NOT_LIVE:  # ruleid: cv-oms-env-branch
        served()
    while order.environment in {"demo"}:  # ruleid: cv-oms-env-branch
        served()
    figures = unserved() if env not in _NOT_LIVE else served()  # ruleid: cv-oms-env-branch
    live = env == "live"  # ruleid: cv-oms-env-branch
    if environment == "live":  # ruleid: cv-oms-env-branch
        raise ValueError("live")
    else:
        served()
    if environment == "live":  # ruleid: cv-oms-env-branch
        unserved()
        raise ValueError("live")
    return [a for a in accounts if a.mode in ("live", "demo")], figures, live  # ruleid: cv-oms-env-branch


def isolation(account, route_environment, order, mode, phase, ViewAsPhase, served):
    if account.environment != route_environment:  # ok: cv-oms-env-branch
        served()
    if order.environment == order.route.environment:  # ok: cv-oms-env-branch
        served()
    if mode == "paper":  # ok: cv-oms-env-branch
        served()
    if phase is not ViewAsPhase.LIVE:  # ok: cv-oms-env-branch
        served()
    if order.environment in order.router.ports:  # ok: cv-oms-env-branch
        served()


def chains(env, ready, served):
    """The exemption covers the raising `if`'s own condition, not the branches after it."""
    if not ready:
        raise ValueError
    elif env == "live":  # ruleid: cv-oms-env-branch
        served()
    if not ready:
        raise ValueError
    else:
        if env not in _NOT_LIVE:  # ruleid: cv-oms-env-branch
            served()
    if not ready:
        raise ValueError
    elif env == "demo":  # ok: cv-oms-env-branch
        raise KeyError


def refuse_live_without_position_rows(environment, positions, NoPositionRows, Unavailable):
    if environment == ProcessEnvironment.LIVE and isinstance(positions, NoPositionRows):  # ok: cv-oms-env-branch
        raise Unavailable("a live process needs the position projection")


def refuse(environment, remediates, bundle, live_enabled):
    if environment in ("live", "demo") and not remediates(environment):  # ok: cv-oms-env-branch
        raise ValueError("a live or demo reconciliation job always remediates")
    if bundle is None and environment not in _NOT_LIVE and live_enabled:  # ok: cv-oms-env-branch
        raise LookupError


def gate(environment, enabled, refused):
    """By design: the marker placement the OMS's reviewed exceptions use."""
    # nosemgrep: cv-oms-env-branch reason=live-gate owner=@CandleViewer/security review=2027-02-04
    if environment not in _NOT_LIVE and not enabled():  # ok: cv-oms-env-branch
        return refused()
    return None
