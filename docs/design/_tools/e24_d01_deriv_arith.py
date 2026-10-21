"""E24-D01 derivatives arithmetic and provenance: the numbers the research memo quotes, computed.

Standalone, offline, stdlib only; no exchange host is contacted and nothing here is market or user
evidence. The tool reads the repo's own files and prints, with a source label on every row: (1) the
funding annualisation `rate x (525600 / interval_min) x 100` (the formula of
`services/api/candleviewer/domain/funding.py`, whose constant is checked, not imported) at the
intervals the plan docs name and on the fixture rates, with the settlements per day; (2) the SCR-054
imminent-settlement charge with its pay / receive sign; (3) the countdown wording ladder and the
remaining time in the one recorded ticker capture; (4) the cascade arithmetic of SCR-054's 500
prints/s target against the 250 ms client bucket, Bybit's 500 ms batching and the WS topic cadence
read from `ws/topics.py`; (5) the quadrant, OI-delta and basis definitions per source, the two names
of the quadrant metric code, the `22` `MetricCode` members the derivatives descriptors lack and the
component token bindings F30 names; (6) the `deriv.*` keys of the E24 epic against the `22`
`Settings` schema; (7) the fixture inventory (which derivative captures exist,
which are assembled from documented shapes, and that no liquidation or open-interest capture
exists); (8) the Sprint 10 / 12 / 13 dates from `calendar_cv.py`; (9) WCAG contrast of the token
pairs the memo names in the three themes. A row reads NOT FOUND when an anchor moved; the tool never
guesses and never raises on a moved anchor.

Usage: python3 -I docs/design/_tools/e24_d01_deriv_arith.py          (Markdown)
       python3 -I docs/design/_tools/e24_d01_deriv_arith.py --json   (the boards' numbers)
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PLAN = "docs/plan/"
FUNDING_PY = "services/api/candleviewer/domain/funding.py"
METRICS_PY = "services/api/candleviewer/rules/vocabulary/metrics.py"
TOPICS_PY = "services/api/candleviewer/ws/topics.py"
FIX = "packages/fixtures/bybit/2026-10-05/"
MINUTES_PER_YEAR = 525_600  # mirrors domain/funding.py; the check below reports if it moves
INTERVALS_MIN = (480, 240, 120, 60)  # 22 /market/funding: "8 h common, some 1/2/4 h"
RATE = Decimal("0.0001")  # 0.01 % per interval, the 24 section 2.7 worked example
CHARGE = Decimal("12.40")  # SCR-054 states line: "position will be charged ~ 12.40 USDT"
WARN_MS = 300_000  # SCR-054: the <5 min warning; announced at 5 min and 1 min only
LADDER_MS = (11_564_000, 3_599_000, 252_000, 59_000, 0)  # 03:12:44, 00:59:59, 00:04:12, 00:00:59, 0
CASCADE = {"prints_per_s": 500, "seconds": 10, "bucket_ms": 250, "bybit_push_ms": 500}
DERIV_24 = [  # 24 section 7.2 Derivatives table, in order
    "open_interest",
    "open_interest_value",
    "open_interest_delta",
    "oi_price_quadrant",
    "funding_rate",
    "funding_annualized",
    "time_to_funding_ms",
    "basis",
    "premium_pct",
    "liquidation_notional",
]
PROBED = [
    "deriv.oi.mode",
    "deriv.funding.annualised",
    "deriv.liq.mode",
    "deriv.liq.min_notional_usd",
]
TOKEN_FILES = ("primitives", "semantic-dark", "semantic-light", "semantic-hc")
COMPONENT_TOKENS = (  # (component, token name as 15 binds it) - memo F30; "resolves" = real names
    ("CMP-126", "font.mono"),
    ("CMP-126", "color.text.buy"),
    ("CMP-126", "color.text.sell"),
    ("CMP-127", "color.status.danger"),
    ("CMP-188", "color.chart.axis"),
    ("CMP-188", "font.mono"),
    ("resolves", "font.family.mono"),
    ("resolves", "color.status.danger.default"),
)
PAIRS = (  # (foreground token, background token, bar, what the memo uses the pair for)
    ("color.text.primary", "color.surface.raised", 4.5, "readouts and legend words"),
    ("color.text.secondary", "color.surface.raised", 4.5, "interval, source"),
    ("color.text.tertiary", "color.surface.raised", 4.5, "chip text, the lower-bound note"),
    ("color.status.info.strong", "color.status.info.subtle", 4.5, "the (estimated) chip text"),
    ("color.status.warning.strong", "color.status.warning.subtle", 4.5, "<5 min warning chip"),
    ("color.text.primary", "color.status.info.subtle", 4.5, "chip text that passes everywhere"),
    ("color.text.primary", "color.status.warning.subtle", 4.5, "warning body text"),
    ("color.status.info.default", "color.surface.raised", 3.0, "chip outline, hatched zone edge"),
    ("color.buy.default", "color.surface.raised", 3.0, "short-liquidation / price-up bar fill"),
    ("color.sell.default", "color.surface.raised", 3.0, "long-liquidation / price-down bar fill"),
    ("color.neutral.default", "color.surface.raised", 3.0, "the unclassified-bar hatch"),
    ("color.data-confidence.stale.text", "color.data-confidence.stale.surface", 4.5, "stale text"),
)


def text(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def grab(rel: str, pattern: str) -> str | None:
    m = re.search(pattern, text(rel), re.DOTALL)
    return re.sub(r"\s+", " ", m.group(1)).strip() if m else None


def annualised_pct(rate: Decimal, interval_min: int) -> str:
    """`rate x (525600 / interval_min) x 100` in Decimal, as domain/funding.py computes it."""
    value = rate * (Decimal(MINUTES_PER_YEAR) / Decimal(interval_min)) * Decimal(100)
    return str(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def hms(ms: int) -> str:
    """One fixed-width hh:mm:ss form at every rung (memo F11): never mm:ss beside it."""
    s = ms // 1000
    h, m, sec = s // 3600, (s % 3600) // 60, s % 60
    return f"{h:02d}:{m:02d}:{sec:02d}"


def ladder(ms: int, interval_min: int = 480) -> dict[str, object]:
    """The PROPOSED countdown wording ladder (memo section 3.3), one fixed-width hh:mm:ss form.

    At settlement two states run independently: the countdown restarts at once from the ticker's
    advanced next_funding_time_ms (23 section 14.8), while the header rate reads 'settled rate
    pending' until the /market/funding row arrives; the restart never waits for that fetch.
    """
    if ms <= 0:
        return {
            "ms": ms,
            "band": "settlement",
            "form": f"next in {hms(interval_min * 60_000)}",
            "rate": "settled rate pending",
            "restart": "at once, from the ticker's advanced next_funding_time_ms",
        }
    if ms < WARN_MS:
        return {
            "ms": ms,
            "band": "<5 min",
            "form": f"Funding settles in {hms(ms)}",
            "warn": True,
            "scope": "the selected account's position on the symbol",
        }
    return {"ms": ms, "band": "<1 h" if ms < 3_600_000 else ">=1 h", "form": f"next in {hms(ms)}"}


def token_keys() -> set[str]:
    """Every token name declared in packages/ui/tokens (the four files), for the F30 bindings."""
    keys: set[str] = set()
    for name in TOKEN_FILES:
        keys.update(json.loads(text(f"packages/ui/tokens/{name}.tokens.json")))
    return keys


def rel_lum(hex_colour: str) -> float:
    def lin(c: int) -> float:
        v = c / 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

    r, g, b = (int(hex_colour[i : i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def contrast(a: str, b: str) -> float:
    la, lb = rel_lum(a), rel_lum(b)
    return round((max(la, lb) + 0.05) / (min(la, lb) + 0.05), 2)


def tokens(theme: str) -> dict[str, str]:
    """Primitives + the dark set + the theme's overlay (light and hc are partial sets), resolved."""
    merged: dict[str, object] = {}
    for name in ("primitives", "semantic-dark", f"semantic-{theme}"):
        merged.update(json.loads(text(f"packages/ui/tokens/{name}.tokens.json")))

    def resolve(key: str, depth: int = 0) -> str:
        raw = merged.get(key)
        value = raw.get("$value") if isinstance(raw, dict) else raw
        if isinstance(value, str) and value.startswith("{") and depth < 8:
            return resolve(value.strip("{}"), depth + 1)
        return str(value) if isinstance(value, str) else "NOT FOUND"

    return {k: resolve(k) for k in merged if k.startswith("color.")}


def sprints() -> dict[str, str]:
    path = ROOT / "docs/plan/backlog/_tools/calendar_cv.py"
    spec = importlib.util.spec_from_file_location("calendar_cv", path)
    if spec is None or spec.loader is None:
        return {"error": "NOT FOUND"}
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    out = {}
    for n in (10, 12, 13):
        start, end = mod.sprint_range(n)
        out[f"S{n}"] = f"{start.isoformat()} -> {end.isoformat()}"
    return out


def fixtures() -> dict[str, object]:
    recorded = [
        json.loads(ln) for ln in text(FIX + "ws/recorded_tickers_BTCUSDT.jsonl").splitlines()
    ]
    d = recorded[0].get("data", {})
    oi = [float(r["data"]["openInterest"]) for r in recorded if r["data"].get("openInterest")]
    oiv = [
        float(r["data"]["openInterestValue"])
        for r in recorded
        if r["data"].get("openInterestValue")
    ]
    manifest = json.loads(text(FIX + "manifest.json"))["fixtures"]
    files = {e["path"]: e["source"] for e in manifest if re.search(r"funding|tickers", e["path"])}
    names = [p.name.lower() for p in (ROOT / "packages/fixtures").rglob("*")]
    first_ts, next_ms = int(recorded[0]["ts"]), int(d.get("nextFundingTime", 0))
    mark, index = Decimal(d.get("markPrice", "0")), Decimal(d.get("indexPrice", "1"))
    premium = (mark - index) / index * 100
    return {
        "deriv_files": files,
        "liquidation_fixture_files": sum("liquid" in n for n in names),
        "open_interest_fixture_files": sum(bool(re.search(r"open[-_]?interest", n)) for n in names),
        "recorded_ticker_frames": len(recorded),
        "recorded_span_s": round((int(recorded[-1]["ts"]) - first_ts) / 1000, 1),
        "recorded_oi_min_max": [min(oi), max(oi)],
        "recorded_oi_value_min_max": [min(oiv), max(oiv)],
        "recorded_implied_price": round(oiv[0] / oi[0], 1),
        "recorded_mark_price": str(mark),
        "recorded_index_price": str(index),
        "recorded_last_price": d.get("lastPrice"),
        "recorded_basis_mark_minus_index": str(mark - index),
        "recorded_premium_pct": str(premium.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)),
        "recorded_live_rate": d.get("fundingRate"),
        "recorded_live_annualised_pct": annualised_pct(Decimal(d.get("fundingRate", "0")), 480),
        "recorded_interval_hour_field": d.get("fundingIntervalHour"),
        "recorded_remaining_ms": next_ms - first_ts,
        "recorded_remaining": hms(next_ms - first_ts),
        "symbol_day_with_settlement_and_cascade": False,
    }


def definitions() -> dict[str, object]:
    p24, p22 = PLAN + "24-internal-schemas.md", PLAN + "22-api-openapi.yaml"
    p11 = PLAN + "11-user-stories.md"
    prose = grab(p24, r"(OI-price quadrant table \(research 08 §6\): [^\n]+)") or ""
    quad = {
        "24 section 7.2": grab(p24, r"`oi_price_quadrant`\s*\|\s*enum `([^`]+)`"),
        "24 section 7.2 prose": " / ".join(re.findall(r"= ([^;.\n]+)", prose)) or None,
        "shipped metrics.py": grab(
            METRICS_PY, r'"oi_price_quadrant", "OI/price quadrant", "enum:([^"]+)"'
        ),
        "30 section 6.2": grab(
            PLAN + "30-release-roadmap.md", r"quadrant classification \(([^)]+)\)"
        ),
    }
    codes = {
        "11 US-DERIV-002 NFR": grab(p11, r"classification exposed as a metric \(`([a-z_]+)`\)"),
        "24 section 7.2": grab(p24, r"`(oi_price_quadrant)`\s*\|\s*enum"),
        "shipped metrics.py": grab(METRICS_PY, r'"(oi_price_quadrant)", "OI/price quadrant"'),
    }
    keys = token_keys()
    code22 = grab(p22, r"\n    MetricCode:\n      type: string\n      enum:\n(.*?)\n\n") or ""
    members = re.findall(r"- ([a-z_]+)", code22)
    settings_block = grab(p22, r"\n    Settings:\n(.*?)\n    [A-Z]") or ""
    row = (
        grab(PLAN + "14-screens-catalogue.md", r'\n\| "\(estimated\)" labelling\s*\|([^\n]*)\|')
        or ""
    )
    return {
        "quadrant_spellings": quad,
        "quadrant_distinct": len({v for v in quad.values() if v}),
        "quadrant_metric_codes": codes,
        "quadrant_metric_code_distinct": len({v for v in codes.values() if v}),
        "component_token_bindings": [
            {"component": c, "token": t, "defined": t in keys} for c, t in COMPONENT_TOKENS
        ],
        "undefined_component_tokens": sorted({t for _, t in COMPONENT_TOKENS if t not in keys}),
        "oi_delta_24": grab(p24, r"`open_interest_delta`\s*\|\s*`([^`]+)`"),
        "oi_delta_shipped": grab(
            METRICS_PY, r'"open_interest_delta", "OI change", "([^"]+)", "oi", "([^"]+)"'
        ),
        "basis_24": grab(p24, r"`basis`, `premium_pct`\s*\|\s*`([^`]+)`"),
        "basis_shipped": grab(
            METRICS_PY, r'"basis", "Basis", "price", "funding", "", 0, _E, "symbol", "([^"]+)"'
        ),
        "basis_21": grab(PLAN + "21-database-schema.md", r"basis\s+DOUBLE\s+-- ([^\n]+)"),
        "metric_code_members": members,
        "deriv_members_present": [m for m in DERIV_24 if m in members],
        "deriv_members_missing": [m for m in DERIV_24 if m not in members],
        "extra_deriv_codes": [
            m for m in members if m in ("funding_basis", "liquidation_intensity")
        ],
        "deriv_keys_in_E24_json": sorted(
            set(re.findall(r"deriv\.[a-z_]+(?:\.[a-z_]+)+", text(PLAN + "backlog/E24.json")))
        ),
        "probed_keys": PROBED,
        "deriv_in_22_settings_schema": "deriv" in settings_block,
        "key_regex_21": grab(
            PLAN + "21-database-schema.md", r"st_key_fmt CHECK \(key ~ '([^']+)'\)"
        ),
        "stale_after_2s_in_14": "after 2 s without an expected update"
        in text(PLAN + "14-screens-catalogue.md"),
        "scr054_in_estimated_labelling_row": "054" in row,
        "estimated_labelling_row": row.strip(),
        "liq_history_sentence_21": grab(
            PLAN + "21-database-schema.md", r"(No REST history exists for liquidations[^\n]*)"
        ),
        "ws_liquidations_throttle_ms": grab(
            TOPICS_PY, r'_md\(\s*"liquidations",\s*\(\("symbol",\),\s*\(\)\),\s*(\d+),'
        ),
        "scr054_mock_text": grab(
            PLAN + "14-screens-catalogue.md",
            r"(Funding\s+0\.0100% next in [0-9:]+ \(annl [0-9]+%\))",
        ),
        "scr054_charge_copy": grab(
            PLAN + "14-screens-catalogue.md", r'"(Funding settles in [^"]+)"'
        ),
        "scr054_announce_rule": grab(
            PLAN + "14-screens-catalogue.md", r"(the funding countdown is announced at [^.]+)"
        ),
        "ticker_fields_have_interval": "fundingIntervalHour"
        in text("services/api/candleviewer/exchange/base/ticker_delta.py"),
    }


def build() -> dict[str, object]:
    settled = json.loads(text(FIX + "rest/funding_history_BTCUSDT_8h.json"))["result"]["list"]
    notional = CHARGE / RATE
    c = CASCADE
    total, buckets = c["prints_per_s"] * c["seconds"], c["seconds"] * 1000 // c["bucket_ms"]
    themes = {t: tokens(t) for t in ("dark", "light", "hc")}
    pairs = []
    for fg, bg, bar, use in PAIRS:
        ratios = {t: contrast(themes[t][fg], themes[t][bg]) for t in themes}
        ok = all(v >= bar for v in ratios.values())
        pairs.append({"fg": fg, "bg": bg, "use": use, "bar": bar, **ratios, "pass": ok})
    return {
        "annualisation": {
            "formula": "rate x (525600 / interval_min) x 100",
            "constant_in_funding_py": f"MINUTES_PER_YEAR: Final[int] = {MINUTES_PER_YEAR:_}"
            in text(FUNDING_PY),
            "rows": [
                {
                    "rate": str(RATE),
                    "interval_min": i,
                    "annualised_pct": annualised_pct(RATE, i),
                    "settlements_per_day": 1440 // i,
                }
                for i in INTERVALS_MIN
            ],
            "fixture_settled_rows": [
                {
                    "rate": r["fundingRate"],
                    "annualised_pct": annualised_pct(Decimal(r["fundingRate"]), 480),
                }
                for r in settled
            ],
        },
        "charge": {
            "scr054_charge_usdt": str(CHARGE),
            "rate": str(RATE),
            "implied_notional_usdt": str(notional.quantize(Decimal(1))),
            "rows": [
                {
                    "side": s,
                    "rate": str(r),
                    "payment_usdt": str((notional * r).quantize(Decimal("0.01"))),
                    "reads": "you pay" if (r > 0) == (s == "long") else "you receive",
                }
                for s in ("long", "short")
                for r in (RATE, -RATE)
            ],
        },
        "countdown": {
            "ladder": [ladder(ms) for ms in LADDER_MS],
            "announce_at_ms": [WARN_MS, 60_000],
            "drift_alarm_ms": 500,
        },
        "cascade": {
            **c,
            "prints_total": total,
            "client_buckets": buckets,
            "prints_per_bucket": total // buckets,
            "bybit_pushes_max": c["seconds"] * 1000 // c["bybit_push_ms"],
            "client_buckets_per_push": c["bybit_push_ms"] // c["bucket_ms"],
        },
        "definitions": definitions(),
        "fixtures": fixtures(),
        "sprints": sprints(),
        "contrast": pairs,
    }


def table(rows: list[dict[str, object]]) -> None:
    keys = list(rows[0])
    print("| " + " | ".join(keys) + " |\n|" + " --- |" * len(keys))
    for r in rows:
        print("| " + " | ".join(str(r.get(k, "")) for k in keys) + " |")


def main(argv: list[str]) -> int:
    data = build()
    if "--json" in argv:
        print(json.dumps(data, indent=2, sort_keys=True))
        return 0
    print("# E24-D01 derivatives arithmetic and provenance\n")
    for name, section in data.items():
        print(f"## {name}\n")
        rows = section if isinstance(section, list) else None
        for key, value in ({} if rows else section).items():
            if isinstance(value, list) and value and isinstance(value[0], dict):
                print(f"- {key}:")
                table(value)
            else:
                print(f"- {key}: {value}")
        if rows:
            table(rows)
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
