"""E25-D01 contract audit: what the plan docs and the shipped rule vocabulary say about detectors.

Standalone, offline, stdlib only. Nothing here is market or user evidence; the tool reads the repo's
own text and prints, with a source label on every row, (1) every regime vocabulary and how many
distinct ones exist, (2) every speed-of-tape window, baseline and update cadence named anywhere,
(3) the parameter names and defaults of the iceberg, stop-run and absorption detectors per source,
(4) where each document places the computation (client-side vs backend-side, with the matched
phrase per component so a hedge such as CMP-134's is visible), (5) the analytics events named on
the `- **Analytics/audit:**` lines of SCR-055..059 (only those lines, so a pointer line that
mentions an event name never counts), (6) the Poisson noise floor of a trades-per-second window at
1 / 5 / 30 s (the arithmetic the report's window recommendation quotes; a lower bound, since real
tape is overdispersed) and (7) the Sprint 10 and 13 dates from `calendar_cv.py`. A row reads
NOT FOUND when the anchor text moved; the tool never guesses a value and never raises on a moved
anchor.

Usage: python3 -I docs/design/_tools/e25_d01_contract_audit.py          (Markdown)
       python3 -I docs/design/_tools/e25_d01_contract_audit.py --json   (the boards' numbers)
"""

from __future__ import annotations

import importlib.util
import json
import math
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PLAN = "docs/plan/"
SHIPPED = "services/api/candleviewer/rules/vocabulary/metrics.py"
RATES = (
    5,
    50,
)  # prints/s; 5 is the order of the one recorded BTCUSDT window (E22-D01 §3.0), shape only
WINDOWS_S = (1, 5, 30)  # the windows 11 / 14 / 22 name
Z, PUSH_HZ, COOLDOWN_S = 3.0, 4, 60  # US-DET-002 z > 3; SCR-055 4 Hz; US-DET-002 cooldown 60 s
SCAN_PER_S = 4.0  # one-token scan, E22-D01 F5 (heuristic)
HEDGE = "or by a backend detector service"  # CMP-134's placement hedge (15-component-catalogue.md)


def text(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def grab(rel: str, pattern: str, group: int = 1) -> str | None:
    m = re.search(pattern, text(rel), re.DOTALL)
    return re.sub(r"\s+", " ", m.group(group)).strip() if m else None


def block(rel: str, start: str, end: str) -> str:
    """Text between the first `start` heading and the next `end`; '' when `start` moved."""
    t = text(rel)
    try:
        i = t.index(start)
    except ValueError:
        return ""  # the dependent rows then read NOT FOUND instead of killing the run
    j = t.find(end, i + len(start))
    return t[i : j if j > 0 else len(t)]


def regime_vocabularies() -> dict[str, object]:
    found = {
        "11 US-DET-008": grab(PLAN + "11-user-stories.md", r"classified as ([a-z, ]+ or calm)"),
        "14 SCR-057": grab(PLAN + "14-screens-catalogue.md", r"Classification badge \(([^)]*)\)"),
        "15 CMP-133": grab(PLAN + "15-component-catalogue.md", r"`regime: ([^`]*)` · `confidence`"),
        "21 §4.11": grab(PLAN + "21-database-schema.md", r"regime\s+SYMBOL[^\n]*--\s*([^\n]*)"),
        "22 RegimeExplanation": grab(
            PLAN + "22-api-openapi.yaml", r"RegimeExplanation:.*?enum: \[([^\]]*)\]"
        ),
        "24 §7.2": grab(PLAN + "24-internal-schemas.md", r"`market_regime`\s*\|\s*enum `([^`]*)`"),
        "30 §6.2": grab(PLAN + "30-release-roadmap.md", r"market-regime classifier \(([^)]*)\)"),
        "shipped metrics.py": grab(SHIPPED, r'"market_regime", "Market regime", "enum:([^"]*)"'),
    }
    sets: dict[str, list[str]] = {}
    for src, raw in found.items():
        if raw is None:
            continue
        toks = re.split(r"[|/,]| or ", raw.replace("\\|", "|").replace("`", ""))
        sets[src] = sorted({t.strip().strip("'\"").lower() for t in toks if t.strip()})
    distinct = {tuple(v) for v in sets.values()}
    return {"raw": found, "sets": sets, "sources": len(sets), "distinct": len(distinct)}


def tape_windows() -> dict[str, str | None]:
    s11, s14, s22, s23 = (
        PLAN + "11-user-stories.md",
        PLAN + "14-screens-catalogue.md",
        PLAN + "22-api-openapi.yaml",
        PLAN + "23-ws-protocol.md",
    )
    return {
        "11 US-DET-001 given window": grab(s11, r"Given a (\d+-second window)"),
        "11 US-DET-001 switched window": grab(s11, r"switch to a (\d+-second window)"),
        "11 US-DET-001 NFR cadence": grab(s11, r"NFR: update at (\d+ Hz)"),
        "11 US-DET-002 threshold / cooldown": " / ".join(
            x or "NOT FOUND"
            for x in (
                grab(s11, r"threshold of (z > 3)"),
                grab(s11, r"cooldown [^.]*default (\d+ s)"),
            )
        ),
        "14 SCR-055 Data windows": grab(s14, r"`metrics\.\{symbol\}`; window ([^.]*)\."),
        "14 SCR-055 checklist selector": grab(s14, r"rolling window selector \(([^)]*)\)"),
        "14 SCR-055 Performance cadence": grab(s14, r"pushed on `metrics\.\{symbol\}` at (\d+ Hz)"),
        "14 SCR-055 A11y baseline": grab(s14, r"sigma above the (1-hour mean)"),
        "14 SCR-057 Performance cadence": grab(
            s14, r"pushed on `metrics\.\{symbol\}` at most (\d+ Hz)"
        ),
        "22 /market/metrics windows": grab(s22, r"`book_updates_per_sec` \(windows ([^)]*)\)"),
        "22 tape_acceleration": grab(s22, r"`tape_acceleration` \(([^)]*)\)"),
        "23 metrics.{symbol} default throttle": grab(
            s23, r"`metrics\.\{symbol\}`\s*\|[^|]*\|[^|]*\|\s*(\d+ ms)"
        ),
        "shipped tape_speed params": grab(
            SHIPPED, r'"tape_speed", "Tape speed", "count", _T, "([^"]*)"'
        ),
        "shipped tape_speed_zscore params": grab(
            SHIPPED, r'"tape_speed_zscore", [^\n]*?_T, "([^"]*)"'
        ),
        "shipped book_speed params": grab(
            SHIPPED, r'"book_speed", "Book speed", "count", _B, "([^"]*)"'
        ),
    }


def detector_params() -> dict[str, object]:
    s22, s24, s14 = (
        PLAN + "22-api-openapi.yaml",
        PLAN + "24-internal-schemas.md",
        PLAN + "14-screens-catalogue.md",
    )
    cfg = block(s22, "    DetectorConfig:", "    DetectorMethodology:")
    names24 = {"iceberg": "iceberg_present_at_level", "stop_run": "stop_run_detected"}
    out: dict[str, object] = {}
    for det in ("iceberg", "stop_run", "absorption"):
        desc = grab(s22, r"`" + det + r"` \(([^)]*)\)") or ""
        desc_pairs = [p.strip() for p in desc.split(",") if "estimated" not in p and p.strip()]
        sub = re.search(r"        " + det + r":\n(.*?)(?=\n        \w+:|\Z)", cfg, re.DOTALL)
        cfg_pairs = (
            [
                f"{n} {d.strip()}"
                for n, d in re.findall(r"(\w+): \{[^}]*default: ([^,}]*)", sub.group(1))
            ]
            if sub
            else []
        )
        cell = grab(s24, r"`" + names24.get(det, det) + r"`\s*\|[^|]*\|([^|]*)\|") or ""
        pairs24 = [p.replace("=", " ") for p in re.findall(r"`([^`]*)`", cell)]
        ship = (
            grab(SHIPPED, r'"' + names24.get(det, det) + r'", "[^"]*", "[^"]*", _[A-Z], "([^"]*)"')
            or ""
        )
        ship_pairs = [p.replace("=", " ") for p in ship.split(";") if p]
        by_src = {
            "22 /market/metrics description": desc_pairs,
            "22 DetectorConfig": [p for p in cfg_pairs if not p.startswith("enabled")],
            "24 §7.2": pairs24,
            "shipped metrics.py": ship_pairs,
        }
        name_sets = {tuple(sorted(p.split()[0] for p in v)) for v in by_src.values() if v}
        out[det] = {"by_source": by_src, "distinct_name_sets": len(name_sets)}
    out["14 SCR-059 threshold names"] = grab(s14, r"explicit thresholds \(([^)]*)\)")
    return out


def placement() -> dict[str, object]:
    """Per component the clause saying client-side (hedges visible); per screen, backend-side."""
    s14, s15 = PLAN + "14-screens-catalogue.md", PLAN + "15-component-catalogue.md"
    cmps = (
        ("CMP-131", "CMP-132"),
        ("CMP-132", "CMP-133"),
        ("CMP-133", "CMP-134"),
        ("CMP-134", "CMP-135"),
    )
    scrs = (("SCR-055", "SCR-056"), ("SCR-056", "SCR-057"), ("SCR-057", "SCR-058"))
    phrases: dict[str, str] = {}
    for a, b in cmps:
        m = re.search(r"[^.;\n]*client-side[^.;\n]*", block(s15, f"### {a}", f"### {b}"))
        phrases[a] = re.sub(r"\s+", " ", m.group(0)).strip() if m else "NOT FOUND"
    return {
        "components_saying_client_side": sum(p != "NOT FOUND" for p in phrases.values()),
        "hedged": ", ".join(c for c, p in phrases.items() if HEDGE in p) or "none",
        "phrases": phrases,
        "screens_saying_backend_side": sum(
            "backend-side" in block(s14, f"### {a}", f"### {b}") for a, b in scrs
        ),
    }


def analytics() -> dict[str, int]:
    """Event names counted on the `- **Analytics/audit:**` lines of SCR-055..059 only."""
    s14 = PLAN + "14-screens-catalogue.md"
    lines = [
        ln
        for n in range(55, 60)
        for ln in block(s14, f"### SCR-0{n}", f"### SCR-0{n + 1}").splitlines()
        if ln.startswith("- **Analytics/audit:**")
    ]
    joined = "\n".join(lines)
    return {
        k: joined.count(k)
        for k in ("methodology.opened", "regime.explain_opened", "regime.panel_opened")
    }


def poisson_tail(n: float, k: int) -> float:
    """P(X >= k) for X ~ Poisson(n): the CDF summed in log space, so exp(-n) never underflows."""
    log_cdf = -math.inf
    for i in range(k):
        log_pmf = -n + i * math.log(n) - math.lgamma(i + 1)
        hi, lo = max(log_cdf, log_pmf), min(log_cdf, log_pmf)
        log_cdf = hi + math.log1p(math.exp(lo - hi)) if lo > -math.inf else hi
    return max(0.0, 1.0 - math.exp(log_cdf))


def noise_floor() -> dict[str, object]:
    rows = {}
    for lam in RATES:
        for w in WINDOWS_S:
            n = lam * w
            thr = math.ceil(n + Z * math.sqrt(n))
            p = poisson_tail(n, thr)
            indep = 3600 / w
            rows[f"{lam}/s x {w} s"] = {
                "expected_prints": n,
                "cv_pct": round(100 / math.sqrt(n), 1),
                "z3_threshold_prints": thr,
                "p_cross_pct": round(100 * p, 2),
                "independent_windows_per_h": int(indep),
                "false_crossings_per_h": round(p * indep, 1),
                "overlap_pct_at_push": round(100 * (1 - 1 / (PUSH_HZ * w)), 1),
            }
    return {
        "rows": rows,
        "cooldown_cap_per_h": 3600 // COOLDOWN_S,
        "digit_swaps_vs_scan": PUSH_HZ / SCAN_PER_S,
    }


def sprints() -> dict[str, str]:
    """The sprint dates from calendar_cv.py, loaded by path (sys.path is left alone)."""
    spec = importlib.util.spec_from_file_location(
        "calendar_cv", ROOT / "docs/plan/backlog/_tools/calendar_cv.py"
    )
    if spec is None or spec.loader is None:
        return {f"S{n:02d}": "NOT FOUND" for n in (10, 12, 13)}
    calendar_cv = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(calendar_cv)
    return {
        f"S{n:02d}": " -> ".join(str(d) for d in calendar_cv.sprint_range(n)) for n in (10, 12, 13)
    }


def main(argv: list[str]) -> int:
    data = {
        "regime": regime_vocabularies(),
        "tape": tape_windows(),
        "params": detector_params(),
        "placement": placement(),
        "analytics": analytics(),
        "noise": noise_floor(),
        "sprints": sprints(),
    }
    if "--json" in argv:
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return 0
    reg = data["regime"]
    print(f"## Regime vocabularies ({reg['sources']} sources, {reg['distinct']} distinct sets)\n")
    for src, toks in reg["sets"].items():
        print(f"- {src}: {', '.join(toks)}")
    print("\n## Speed-of-tape windows, baselines and cadences\n")
    for k, v in data["tape"].items():
        print(f"- {k}: {v if v is not None else 'NOT FOUND'}")
    print("\n## Detector parameters per source\n")
    for det, d in data["params"].items():
        if not isinstance(d, dict):
            print(f"- {det}: {d}")
            continue
        print(f"- {det} ({d['distinct_name_sets']} distinct parameter-name sets):")
        for src, pairs in d["by_source"].items():
            print(f"  - {src}: {', '.join(pairs) if pairs else 'NOT FOUND'}")
    print("\n## Placement and analytics\n")
    pl = data["placement"]
    print(
        f"- components saying client-side: {pl['components_saying_client_side']} "
        f"(hedged: {pl['hedged']})"
    )
    for cmp_id, phrase in pl["phrases"].items():
        print(f"  - {cmp_id}: {phrase}")
    print(f"- screens saying backend-side: {pl['screens_saying_backend_side']}")
    print(f"- events on the SCR-055..059 Analytics/audit lines: {data['analytics']}")
    print("\n## Poisson noise floor of a prints/s window (lower bound; z > 3 at 4 Hz pushes)\n")
    print(
        "| Rate x window | E[prints] | CV % | z>3 at | P(cross) % | indep./h | false/h "
        "| overlap % |"
    )
    print("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
    for k, r in data["noise"]["rows"].items():
        print(
            f"| {k} | {r['expected_prints']} | {r['cv_pct']} | {r['z3_threshold_prints']} | "
            f"{r['p_cross_pct']} | {r['independent_windows_per_h']} | "
            f"{r['false_crossings_per_h']} | "
            f"{r['overlap_pct_at_push']} |"
        )
    print(
        f"\ncooldown caps alerts at {data['noise']['cooldown_cap_per_h']}/h; a 4 Hz digit swap is "
        f"{data['noise']['digit_swaps_vs_scan']:g}x the one-token scan rate"
    )
    print("\n## Sprints (calendar_cv.py)\n")
    for k, v in data["sprints"].items():
        print(f"- {k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
