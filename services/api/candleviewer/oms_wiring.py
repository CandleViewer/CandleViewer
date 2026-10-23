"""Composition-root wiring (not a module) of the OMS (E29-T04, #913 slice 3), part 1, pure: the
OMS's time bounds from the settings (`OmsBounds`, 20 Sec.7.2), refused together so a bad set fails
the runtime's start, never a request. Nothing is started or mounted here.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, fields
from typing import Final

from candleviewer.oms.submit import RESULT_WAIT_S, STORE_TIMEOUT_S
from candleviewer.settings import OMS_INFLIGHT_STUCK_MAX_S, Settings
from candleviewer.statechart.config import CV_COMMAND_TIMEOUT, CV_PERSIST_TIMEOUT

#: The stop request's bound (21 Sec.3.3.11, [LANE-25]), in seconds: how long an unanswered stop
#: request holds its key before it waits for the complete read (`RefuseWhileWaiting`); at least an
#: entry's answer path, 2 x `CV_PERSIST_TIMEOUT` + the submit timeout (`OmsBounds`). No safety
#: knob: either side of it refuses a second request for the key.
STOP_REQUEST_BOUND_S: Final = 10.0
#: B1's turn: what the pipeline's wait for the create's answer adds to the port's deadline.
B1_TURN_S: Final = 1.0


@dataclass(frozen=True, slots=True, kw_only=True)
class OmsBounds:
    """The OMS's time bounds in seconds (24 Sec.8.4), each finite and above zero (C-2.18). The
    submit timeout bounds one create's `place`: a stop request's answer, 2 x `CV_PERSIST_TIMEOUT`
    + it, fits `stop_request_s`, and B1's `CV_COMMAND_TIMEOUT` never cuts it. `place_wait_s`
    outlasts it (D-2B2-01). `stuck_after_s`, the anchor service's own threshold (CR-S3D-01), is
    above `after_anchor_s`, so no repeat decides an anchor whose request may still send, and at
    most `OMS_INFLIGHT_STUCK_MAX_S` (SEC-S3D-02)."""

    submit_timeout_s: float
    place_wait_s: float
    stuck_after_s: float
    result_wait_s: float = RESULT_WAIT_S
    store_timeout_s: float = STORE_TIMEOUT_S
    stop_request_s: float = STOP_REQUEST_BOUND_S

    def __post_init__(self) -> None:
        for name in (bound.name for bound in fields(self)):
            if not (math.isfinite(seconds := getattr(self, name)) and seconds > 0):
                raise ValueError(f"{name} must be a finite number of seconds above zero")
        answer_s = 2 * CV_PERSIST_TIMEOUT + self.submit_timeout_s
        if answer_s > self.stop_request_s or not self.submit_timeout_s < CV_COMMAND_TIMEOUT:
            raise ValueError(
                f"submit_timeout_s ({self.submit_timeout_s:g} s): a stop request's answer must fit "
                f"{self.stop_request_s:g} s, and B1's command timeout must not cut a create"
            )
        if not self.place_wait_s > self.submit_timeout_s:
            raise ValueError(
                f"place_wait_s must outlast the submit timeout ({self.place_wait_s:g} s)"
            )
        if not self.after_anchor_s < self.stuck_after_s <= OMS_INFLIGHT_STUCK_MAX_S:
            raise ValueError(
                f"CV_OMS_INFLIGHT_STUCK_S ({self.stuck_after_s:g} s) must be above the bounds "
                f"after the anchor ({self.after_anchor_s:g} s) and at most "
                f"{OMS_INFLIGHT_STUCK_MAX_S:g} s"
            )

    @property
    def after_anchor_s(self) -> float:
        """A request's bounds once its anchor exists: `SEND`'s write, the create's answer, its
        result step and four store bounds (24 Sec.8.4; the pipeline's `_after_anchor_s`)."""
        waits = self.place_wait_s + self.result_wait_s
        return CV_PERSIST_TIMEOUT + waits + 4 * self.store_timeout_s

    @classmethod
    def from_settings(cls, settings: Settings) -> OmsBounds:
        submit_s = settings.oms_submit_timeout_ms / 1000
        return cls(
            submit_timeout_s=submit_s,
            place_wait_s=submit_s + B1_TURN_S,
            stuck_after_s=settings.oms_inflight_stuck_s,
        )
