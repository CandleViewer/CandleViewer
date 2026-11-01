"""`GET /market/metrics` (`22-api-openapi.yaml` `getMetrics`), derivatives codes (E24-T04 PR B).

Serves the 22 `MetricCode`s the derivatives engine computes (`DERIVATIVE_CODES`: the ten 24 §7.2
descriptors plus the `funding_basis` / `liquidation_intensity` aliases). Each value is read
through `orderflow.derivatives.metric_value`, and each series' `unit` and `estimated` come from
the rule vocabulary's `MetricRegistry` descriptor, so the route, a pane and a rule condition
read one number with one unit. A `MetricCode` no engine computes yet is 422 (E20-T02, #645,
mounts the Deep-Stats codes on this route).

Order of refusal (RBAC mirrors `api/funding.py`, C-12.4): 501 without a resolver, 401, 403;
then 400 `validation_failed` (symbol, metric list, `bar_type` / `param`, `params`), 400
`invalid_time_range` (`from` / `to`, the window bounds) and 422 for a code not served or an
unlisted symbol, all before any store read (STRIDE D12); then 503 while a source is down.
"""

from __future__ import annotations

import inspect
import json
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Final, get_args

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from candleviewer.api._generated.openapi_models import MetricSeries
from candleviewer.api.funding import _SYMBOL_RE, _iso, _parse_time, _Principal, _problem, _Resolver
from candleviewer.bars.spec import TIME_INTERVALS
from candleviewer.domain.funding import FundingIntervalUnknown
from candleviewer.orderflow.deriv_limits import DerivInvalidRequest, DerivSymbolUnlisted
from candleviewer.orderflow.derivatives import (
    BarMetrics,
    DerivativesInputError,
    metric_value,
    resolve_params,
)
from candleviewer.orderflow.derivatives_query import (
    DERIVATIVE_CODES,
    DerivativesQuery,
    plan_window,
)
from candleviewer.orderflow.funding_metrics import deriv_range_rejected_total
from candleviewer.rules.vocabulary.metrics import default_registry
from candleviewer.rules.vocabulary.registry import MetricRegistry
from candleviewer.storage.errors import StorageTierUnavailable

_REQUIRED_PERMISSION: Final = "marketdata:read"
_ENDPOINT: Final = "metrics"
#: 22: `metric` is 1..12 values of `MetricCode`; `params` at most 2048 characters.
MAX_METRICS: Final = 12
MAX_PARAMS_LEN: Final = 2048
_METRIC_CODES: Final = frozenset(get_args(MetricSeries.model_fields["metric"].annotation))


def _bad(code: str, detail: str) -> JSONResponse:
    deriv_range_rejected_total.labels(endpoint=_ENDPOINT).inc()
    return _problem(400, code, "Bad request", detail)


def _wire(value: Decimal | int | str | None) -> str | None:
    if value is None or isinstance(value, str):
        return value  # None, or the quadrant's enum value
    return str(value) if isinstance(value, int) else format(value, "f")


def _parse_params(raw: str | None, codes: list[str]) -> dict[str, dict[str, str]]:
    """Per requested code its full params; `DerivativesInputError` on any bad entry."""
    given: object = {} if raw is None else json.loads(raw)
    if not isinstance(given, dict) or set(given) - set(codes):
        raise DerivativesInputError("params must be an object keyed by requested metrics")
    out: dict[str, dict[str, str]] = {}
    for code in codes:
        entry = given.get(code, {})
        if not isinstance(entry, dict):
            raise DerivativesInputError(f"params.{code} must be an object")
        out[code] = resolve_params(DERIVATIVE_CODES[code], entry)
    return out


def serialize_series(
    code: str, params: dict[str, str], rows: tuple[BarMetrics, ...], registry: MetricRegistry
) -> dict[str, object]:
    name = DERIVATIVE_CODES[code]
    descriptor = registry.get(name)
    if descriptor is None:  # the registry test pins all ten; a gap here is a server bug
        raise LookupError(f"{name} is not registered")
    return {
        "metric": code,
        "estimated": descriptor.confidence == "estimated",
        "params": params,
        "unit": descriptor.unit,
        "points": [
            {"t": _iso(m.start_ms * 1000), "v": _wire(metric_value(m, name, params))} for m in rows
        ],
    }


def make_market_metrics_router(
    query_provider: Callable[[], DerivativesQuery | None],
    *,
    principal_resolver: _Resolver | None = None,
    now_us: Callable[[], int],
    registry: MetricRegistry | None = None,
) -> APIRouter:
    router = APIRouter(tags=["market-data"])
    vocabulary = registry if registry is not None else default_registry()

    @router.get("/market/metrics")
    async def get_metrics(
        request: Request,
        symbol: str | None = Query(default=None),
        metric: Annotated[list[str] | None, Query()] = None,
        from_: str | None = Query(default=None, alias="from"),
        to: str | None = Query(default=None, alias="to"),
        bar_type: str = Query(default="time"),
        param: str = Query(default="1"),
        params: str | None = Query(default=None),
    ) -> JSONResponse:
        if principal_resolver is None:
            return _problem(
                501, "not_implemented", "Not implemented", "no principal resolver wired"
            )
        resolved = principal_resolver.resolve(request)
        principal: _Principal | None = await resolved if inspect.isawaitable(resolved) else resolved
        if principal is None:
            return _problem(401, "unauthenticated", "Unauthorized", "no verified session")
        if not principal.has(_REQUIRED_PERMISSION):
            return _problem(403, "forbidden", "Forbidden", f"requires {_REQUIRED_PERMISSION}")
        if symbol is None or not _SYMBOL_RE.fullmatch(symbol):
            return _bad("validation_failed", "invalid symbol")
        codes = metric or []
        if not 1 <= len(codes) <= MAX_METRICS or not set(codes) <= _METRIC_CODES:
            return _bad("validation_failed", f"metric must be 1..{MAX_METRICS} MetricCode values")
        if bar_type != "time" or param not in TIME_INTERVALS:
            return _bad(
                "validation_failed", "derivatives metrics need bar_type=time and a time interval"
            )
        if params is not None and len(params) > MAX_PARAMS_LEN:
            return _bad("validation_failed", f"params is over {MAX_PARAMS_LEN} characters")
        unserved = sorted(set(codes) - set(DERIVATIVE_CODES))
        if unserved:
            detail = f"not computed by this server yet: {', '.join(unserved)}"
            return _problem(422, "validation_failed", "Unprocessable", detail)
        try:
            resolved_params = _parse_params(params, codes)
        except (ValueError, DerivativesInputError):  # json.JSONDecodeError is a ValueError
            return _bad("validation_failed", "params is not valid for the requested metrics")
        interval_ms = TIME_INTERVALS[param]
        try:
            window = plan_window(
                _parse_time(from_), _parse_time(to), interval_ms=interval_ms, now_us=now_us()
            )
        except ValueError:  # a malformed from/to timestamp
            return _bad("invalid_time_range", "invalid from/to timestamp")
        except DerivInvalidRequest as exc:
            return _bad(exc.code, exc.detail)
        query = query_provider()
        if query is None:
            return _problem(503, "store_unavailable", "Service unavailable", "metrics not wired")
        try:
            meta = query.check_symbol(symbol)
            rows = await query.compute(symbol, meta, interval_ms=interval_ms, window=window)
        except DerivSymbolUnlisted:
            return _problem(422, "validation_failed", "Unprocessable", f"{symbol} is not listed")
        except DerivInvalidRequest as exc:
            return _bad(exc.code, exc.detail)
        except (FundingIntervalUnknown, StorageTierUnavailable, TimeoutError):
            return _problem(503, "store_unavailable", "Service unavailable", "a source is down")
        except DerivativesInputError:  # a stored row the engine refuses: never a number
            return _problem(503, "degraded_data", "Service unavailable", "a stored row is invalid")
        series = [serialize_series(c, resolved_params[c], rows, vocabulary) for c in codes]
        generated = datetime.fromtimestamp(now_us() / 1e6, tz=UTC)
        return JSONResponse(
            status_code=200,
            content={
                "symbol": symbol,
                "bar_type": bar_type,
                "param": param,
                "series": series,
                "meta": {
                    "count": len(rows),
                    "has_more": False,
                    "next_cursor": None,
                    "generated_at": generated.isoformat().replace("+00:00", "Z"),
                },
            },
        )

    return router


__all__ = ["make_market_metrics_router", "serialize_series"]
