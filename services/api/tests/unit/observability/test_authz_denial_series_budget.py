"""#4530: `authz_denied_by_route_total`'s `max_series` is sized from the contract's route table, not
guessed: the sum of the catalogue's `max_series` is the scrape's cost (the max-cardinality scrape
test), so an oversized budget is a defect and an undersized one drops real series. A series is a
(permission, route, role): a route template whose methods name different permissions in `x-rbac`
yields one series per permission, so the count is of (permission, route template) pairs."""

from __future__ import annotations

from pathlib import Path

import yaml

from candleviewer.auth.metrics import ENROLMENT_ONLY_ROLES
from candleviewer.observability.authz_denials import METRIC_NAME
from candleviewer.observability.metrics_catalogue import registered_specs

OPENAPI = Path(__file__).resolve().parents[5] / "docs" / "plan" / "22-api-openapi.yaml"
NON_ROUTE_ROUTES = ("unmatched", "ws")
HEADROOM, MARGIN = 1.25, 25


def _guarded_route_permissions() -> set[tuple[str, str]]:
    paths = yaml.safe_load(OPENAPI.read_text(encoding="utf-8"))["paths"]
    return {
        (permission, path)
        for path, item in paths.items()
        for op in item.values()
        if isinstance(op, dict)
        for permission in (op.get("x-rbac") or {}).get("permissions") or ()
    }


def _needed_series() -> int:
    pairs = len(_guarded_route_permissions()) + len(NON_ROUTE_ROUTES)
    return pairs * len(ENROLMENT_ONLY_ROLES)


def _max_series() -> int:
    return next(s.max_series for s in registered_specs() if s.name == METRIC_NAME)


def test_the_route_permission_pairs_are_read_from_the_contract() -> None:
    pairs = _guarded_route_permissions()
    assert len({path for _, path in pairs}) > 100  # a parse that found nothing must not pass
    assert len(pairs) > len({path for _, path in pairs})  # some templates carry two permissions


def test_authz_denied_by_route_max_series_covers_every_permission_route_and_role() -> None:
    assert _max_series() >= _needed_series()


def test_authz_denied_by_route_max_series_keeps_only_the_stated_headroom() -> None:
    assert _max_series() <= HEADROOM * _needed_series() + MARGIN
