"""Fixtures for cv-obs-metric-label-allowlist (E04-X02)."""


def bad(reg: object) -> None:
    reg.counter("cv_x_total", "help", ("account_id",))  # ruleid: cv-obs-metric-label-allowlist


def ok(reg: object) -> None:
    reg.counter("cv_y_total", "help", ("symbol", "result"))  # ok: cv-obs-metric-label-allowlist


def ok_trigger_mode(reg: object) -> None:
    reg.counter("cv_z_total", "help", ("trigger_mode",))  # ok: cv-obs-metric-label-allowlist


def ok_bounded_2453(reg: object) -> None:
    reg.counter("cv_a_total", "help", ("bucket", "resource"))  # ok: cv-obs-metric-label-allowlist
    reg.counter("cv_b_total", "help", ("cause",))  # ok: cv-obs-metric-label-allowlist
    reg.histogram("cv_h_s", "help", ("filter_class",))  # ok: cv-obs-metric-label-allowlist
    reg.histogram("cv_c_seconds", "help", ("operation",))  # ok: cv-obs-metric-label-allowlist
    reg.histogram("cv_d_s", "help", ("route", "status_class"))  # ok: cv-obs-metric-label-allowlist
    reg.counter("cv_e_total", "help", ("rule",))  # ok: cv-obs-metric-label-allowlist
    reg.gauge("cv_f_rows", "help", ("tool",))  # ok: cv-obs-metric-label-allowlist


def bad_raw_path(reg: object) -> None:
    reg.histogram("cv_g_seconds", "help", ("path",))  # ruleid: cv-obs-metric-label-allowlist


def ok_flag(reg: object) -> None:
    reg.counter("cv_w_total", "help", ("flag", "result"))  # ok: cv-obs-metric-label-allowlist
