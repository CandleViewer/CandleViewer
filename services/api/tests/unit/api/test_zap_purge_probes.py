"""The DAST Owner purge probes (`security/zap/owner-purge-denials.yaml`, E16-X02, #494) stay
valid purge requests, so they reach the step-up refusal they test (the handler checks the body
before its step-up since #4622), and stay bounded by the epoch, so an elevated run removes
nothing. The governance lane cannot import the API, so this half of the check lives here."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from candleviewer.api.recorder_purge import PurgeRequest

PROBES = Path(__file__).resolve().parents[5] / "security/zap/owner-purge-denials.yaml"


def _bodies() -> list[dict[str, object]]:
    plan = yaml.safe_load(PROBES.read_text(encoding="utf-8"))
    return [entry["json"] for entry in plan["requests"]]


@pytest.mark.parametrize("body", _bodies())
def test_each_purge_probe_is_a_valid_request_bounded_by_the_epoch(body: dict[str, object]) -> None:
    request = PurgeRequest.model_validate_json(json.dumps(body))  # as the handler parses it
    assert request.before == datetime(1970, 1, 1, tzinfo=UTC)
    assert request.confirm_symbol == request.symbol
