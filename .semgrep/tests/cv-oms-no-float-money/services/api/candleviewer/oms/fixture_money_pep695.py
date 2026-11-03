# Fixture for cv-oms-no-float-money in a file with PEP 695 syntax, which Semgrep parses another way
# (#3549), as `oms/day_figures.py` and `oms/reconcile_job.py` are.
type Tiers = dict[str, list[str]]


class _Kept[T]:
    def __init__(self, value: T, wait_s: float) -> None:
        self.value, self.wait_s = value, float(wait_s)  # ok: cv-oms-no-float-money
        self.rung = {"take_profit": float(value)}  # ruleid: cv-oms-no-float-money
        self.ttl = {"refresh_s": float(wait_s)}  # ok: cv-oms-no-float-money


def _fresh[K, T](wallet: dict[K, T], key: K) -> float:
    return float(wallet[key].available_balance)  # ruleid: cv-oms-no-float-money
