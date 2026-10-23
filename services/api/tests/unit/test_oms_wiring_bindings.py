"""#913 slice 3B (E29-T04): the OMS's bounds (`oms_wiring.OmsBounds`), from the settings and
refused together when a set breaks a relation (D-2B2-01, CR-S3D-01, SEC-S3D-02)."""

from __future__ import annotations

import dataclasses
import math

import pytest

from candleviewer.oms import commands, idempotency, submit
from candleviewer.oms_wiring import OmsBounds
from candleviewer.settings import OMS_AFTER_ANCHOR_S, Settings


def test_bounds_of_the_default_settings_are_the_pipelines_own_defaults() -> None:
    """The settings and the components agree; M1's 12 s is the pipeline's own sum."""
    bounds = OmsBounds.from_settings(Settings())
    assert (bounds.submit_timeout_s, bounds.place_wait_s, bounds.stuck_after_s) == (
        commands.SUBMIT_TIMEOUT_S,
        submit.PLACE_WAIT_S,
        idempotency.STUCK_AFTER_S,
    )
    pipeline = submit._after_anchor_s(
        store_timeout_s=submit.STORE_TIMEOUT_S,
        place_wait_s=bounds.place_wait_s,
        result_wait_s=submit.RESULT_WAIT_S,
    )
    assert bounds.after_anchor_s == pipeline == bounds.submit_timeout_s + OMS_AFTER_ANCHOR_S


@pytest.mark.parametrize(
    ("change", "refused"),
    [
        (
            {"stuck_after_s": 17.0},
            "CV_OMS_INFLIGHT_STUCK_S",
        ),  # lowered to the 17 s after the anchor
        ({"stuck_after_s": 120.5}, "CV_OMS_INFLIGHT_STUCK_S"),  # past SEC-S3D-02's ceiling
        ({"submit_timeout_s": 8.5, "place_wait_s": 9.5}, "stop request"),  # raised: 2 + 8.5 > 10
        ({"submit_timeout_s": 10.0, "place_wait_s": 11.0, "stop_request_s": 13.0}, "command"),
        ({"place_wait_s": 5.0}, "place_wait_s"),  # not above the deadline (D-2B2-01)
        ({"result_wait_s": math.nan}, "result_wait_s"),
    ],
)
def test_bounds_refuse_a_set_that_breaks_a_relation(change: dict[str, float], refused: str) -> None:
    with pytest.raises(ValueError, match=refused):
        dataclasses.replace(OmsBounds.from_settings(Settings()), **change)
