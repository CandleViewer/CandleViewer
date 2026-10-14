"""Fixtures for cv-obs-metric-label-allowlist (E04-X02)."""


def bad(reg: object) -> None:
    reg.counter("cv_x_total", "help", ("account_id",))  # ruleid: cv-obs-metric-label-allowlist


def ok(reg: object) -> None:
    reg.counter("cv_y_total", "help", ("symbol", "result"))  # ok: cv-obs-metric-label-allowlist


def ok_trigger_mode(reg: object) -> None:
    reg.counter("cv_z_total", "help", ("trigger_mode",))  # ok: cv-obs-metric-label-allowlist


def ok_tier(reg: object) -> None:
    reg.histogram("cv_w_seconds", "help", ("tier",))  # ok: cv-obs-metric-label-allowlist
