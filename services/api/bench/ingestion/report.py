"""Markdown evidence report (one per run under `bench/reports/`).

matplotlib is not a dependency, so the RSS curve is an inline SVG polyline written as plain
text (no new dependency). The report carries only numbers, scenario names, scaling notes,
machine profile and a Grafana time range: `redact()` strips anything that looks like a header,
token, key or account id, and a test asserts it (security notes).
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import UTC, datetime

from bench.ingestion import HARNESS_VERSION
from bench.ingestion.budgets import Verdict
from bench.ingestion.config import Scenario
from bench.ingestion.gate import GateResult, render_diff

_ISO = "%Y-%m-%dT%H:%M:%SZ"
_SECRETISH = re.compile(
    r"(?i)(authorization|cookie|x-[a-z0-9]+-(?:api-key|sign|signature|timestamp|recv-window)|api[_-]?key|secret|token|signature|session"
    r"|uid|account[_-]?id)\s*[:=]\s*\S+"
)


def redact(text: str) -> str:
    return _SECRETISH.sub(lambda m: f"{m.group(1)}=[REDACTED]", text)


def svg_curve(points: dict[str, float], width: int = 480, height: int = 120) -> str:
    """Inline SVG polyline of RSS (MiB) over scenario time; empty string for <2 points."""
    if len(points) < 2:
        return ""
    xs = [float(k) for k in points]
    ys = list(points.values())
    x0, x1 = min(xs), max(xs) or 1.0
    y0, y1 = min(ys), max(ys)
    span_y = (y1 - y0) or 1.0
    pts = " ".join(
        f"{(x - x0) / ((x1 - x0) or 1.0) * width:.1f},{height - (y - y0) / span_y * height:.1f}"
        for x, y in zip(xs, ys, strict=True)
    )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'role="img" aria-label="RSS {y0:.1f}-{y1:.1f} MiB over {x1 - x0:.0f} s">'
        f'<polyline fill="none" stroke="black" points="{pts}"/></svg>'
    )


def render(
    runs: Sequence[tuple[Scenario, Verdict, GateResult]],
    profile: str,
    started: datetime,
    finished: datetime,
    grafana_url: str = "",
) -> str:
    rng = f"from={int(started.timestamp() * 1000)}&to={int(finished.timestamp() * 1000)}"
    ok = all(v.passed for _, v, _ in runs) and not any(g.failures for _, _, g in runs)
    out = [
        f"# E08-Q04 ingestion performance report — {'PASS' if ok else 'FAIL'}",
        "",
        f"- Harness: `{HARNESS_VERSION}` · machine profile: `{profile}`",
        f"- Run: {started.astimezone(UTC):{_ISO}} → {finished.astimezone(UTC):{_ISO}}",
        f"- Grafana range: `{grafana_url}?{rng}`" if grafana_url else f"- Grafana range: `{rng}`",
        "- Data: recorded exchange corpus (capture 2026-10-05) + seeded synthetic feed; "
        "no network.",
        "",
    ]
    for sc, v, g in runs:
        out += [
            f"## {sc.name} — {sc.title} — {'PASS' if v.passed else 'FAIL'} (gate {g.status})",
            "",
            f"Profile `{sc.profile}`. Scaling: {sc.scaling}",
            "",
            "| check | budget | measured | limit | unit | result |",
            "|---|---|---:|---:|---|---|",
        ]
        for c in v.checks:
            res = "pass" if c.passed else ("FAIL" if c.hard else "warn (soft)")
            note = f" — {c.note}" if c.note else ""
            nums = f"{c.measured:.4g} | {c.limit:.4g} | {c.unit}"
            out.append(f"| {c.name}{note} | {c.budget} | {nums} | {res} |")
        out += ["", "| metric | p50 | p95 | max | n |", "|---|---:|---:|---:|---:|"]
        for k, m in sorted(v.metrics.items()):
            if k.startswith("_"):
                continue
            out.append(
                f"| {k} | {m['p50']:.4g} | {m['p95']:.4g} | {m['max']:.4g} | {m['count']:.0f} |"
            )
        curve = svg_curve(v.metrics.get("_curve", {}))
        if curve:
            out += ["", "RSS curve (MiB):", "", curve]
        out += ["", f"Baseline gate: **{g.status}**" + (f" ({g.reason})" if g.reason else "")]
        out += [f"- WARN {w}" for w in g.warnings] + [f"- FAIL {f}" for f in g.failures]
        if g.diff:
            out += ["", render_diff(g)]
        out.append("")
    return redact("\n".join(out))
