# Fixture for cv-oms-no-float-money in the OMS composition modules (`oms_*.py`).


class Clock:
    def now(self, read, figures):
        risk = float(figures.committed_risk)  # ruleid: cv-oms-no-float-money
        return float(read()), risk  # ok: cv-oms-no-float-money
