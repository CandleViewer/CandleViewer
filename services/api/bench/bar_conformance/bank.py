"""Plan/write for the E12-Q02 conformance bank: tapes, goldens, `MANIFEST.toml`.

Only `regen_goldens --suite conformance --write --reason ...` calls `write`. Same refusal rules
as the E12-T04 goldens (never in CI, `--reason` required, a changed kind needs a `BUILD_VERSIONS`
bump); the manifest records the build_versions the goldens were produced under.

Tape-only exemption (#2200): the manifest also records a fingerprint of the builder sources and
the spec hash of every live case. A regeneration that changes only a tape (builder code and spec
hashes identical to the recorded ones) needs no `BUILD_VERSIONS` bump; any builder-code or
spec-hash change still does. A manifest written before the fingerprint existed counts as unchanged
once, and the next write records it.
"""

from __future__ import annotations

import hashlib
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from bench.bar_determinism import tapes
from candleviewer.bars import rows
from candleviewer.bars.rows import BUILD_VERSIONS
from candleviewer.exchange.base.models import TradeEvent

from . import runner as cf


@dataclass
class Plan:
    files: dict[str, bytes] = field(default_factory=dict)  # repo-relative posix path -> bytes
    changed: list[str] = field(default_factory=list)
    unbumped: list[str] = field(default_factory=list)
    summary: list[str] = field(default_factory=list)  # human diff summary
    manifest: str = ""
    mismatches: list[str] = field(default_factory=list)  # live vs reference; blocks --write


def _rel(p: Path) -> str:
    return p.relative_to(tapes.REPO).as_posix()


def recorded_versions() -> dict[str, int]:
    if not cf.MANIFEST.exists():
        return {}
    doc = tomllib.loads(cf.MANIFEST.read_text(encoding="utf-8"))
    bv = doc.get("build_versions", {})
    return {str(k): int(v) for k, v in bv.items()}


#: Sources whose behaviour decides what a builder emits (`rows.py` holds the versions: excluded).
_BUILDER_SOURCES = (
    "activity_builders.py",
    "builder_set.py",
    "models.py",
    "renko_builder.py",
    "spec.py",
    "threshold_builders.py",
    "time_builder.py",
)


def builder_fingerprint() -> str:
    d = Path(str(rows.__file__)).parent
    h = hashlib.sha256()
    for name in _BUILDER_SOURCES:
        h.update(name.encode() + b"\0" + (d / name).read_bytes() + b"\0")
    return h.hexdigest()


def spec_hashes() -> dict[str, str]:
    return {label: str(sp.spec_hash) for label, sp in sorted(cf.live_cases().items())}


def _recorded() -> dict[str, Any]:
    if not cf.MANIFEST.exists():
        return {}
    return tomllib.loads(cf.MANIFEST.read_text(encoding="utf-8"))


def builder_code_changed(rec: dict[str, Any]) -> bool:
    """True when the builder sources or any spec hash differ from the recorded ones. A manifest
    without the fingerprint (legacy) is treated as unchanged: the next write records it."""
    fp, specs = rec.get("builder_code_sha256"), rec.get("spec_hashes")
    return (fp is not None and fp != builder_fingerprint()) or (
        specs is not None and dict(specs) != spec_hashes()
    )


def _toml_str(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def build(reason: str = "") -> Plan:
    if not reason.strip() and cf.MANIFEST.exists():  # a dry run keeps the recorded reason
        reason = str(tomllib.loads(cf.MANIFEST.read_text(encoding="utf-8")).get("reason", ""))
    p = Plan()
    entries: list[str] = []
    changed_kinds: set[str] = set()
    for name, d in tapes.TAPES.items():
        tape, meta = d.build()
        blob = tapes.serialise(tape)
        tpath = tapes.tape_path(name)
        p.files[_rel(tpath)] = blob
        if not tpath.exists() or tpath.read_bytes() != blob:
            p.changed.append(_rel(tpath))
            p.summary.append(f"tape {name}: {len(tape)} prints, {len(blob)} bytes")
        results = cf.run(tape, d.symbol)
        gold: list[str] = []
        for label, spec in cf.live_cases().items():
            rd = cf.reference_diffs(spec, d.symbol, tape, results[label])
            if rd:
                p.mismatches.append(f"{name}/{label}: {rd[0]}")
            ls = cf.lines(results[label])
            gp = cf.golden_path(name, label)
            p.files[_rel(gp)] = ("\n".join(ls) + "\n").encode()
            old = cf.read_golden(name, label) if gp.exists() else None
            if old != ls:
                p.changed.append(_rel(gp))
                changed_kinds.add(spec.kind)
                n_old = "new" if old is None else str(len(old))
                p.summary.append(f"golden {name}/{label}: bars {n_old} -> {len(ls)}")
            gold.append(f'  {{ pair = "{label}", bars = {len(ls)}, sha256 = "{cf.digest(ls)}" }}')
        entries.append(_entry(name, d, tape, blob, meta, gold))
    for label, msg in cf.rejected_cases().items():
        entries.append(_rejected(label, msg))
    rec = recorded_versions()
    if builder_code_changed(_recorded()):  # a tape-only regeneration needs no bump (#2200)
        p.unbumped = sorted(k for k in changed_kinds if rec.get(k) == BUILD_VERSIONS[k])
    p.manifest = _manifest_head(reason) + "\n".join(entries)
    mp = _rel(cf.MANIFEST)
    p.files[mp] = p.manifest.encode()
    if not cf.MANIFEST.exists() or cf.MANIFEST.read_text(encoding="utf-8") != p.manifest:
        p.changed.append(mp)
    return p


def _manifest_head(reason: str) -> str:
    bv = "\n".join(f"{k} = {v}" for k, v in sorted(BUILD_VERSIONS.items()))
    sh = "\n".join(f"{_toml_str(k)} = {_toml_str(v)}" for k, v in spec_hashes().items())
    return (
        "# E12-Q02 conformance fixture bank. GENERATED by bench.bar_determinism.regen_goldens\n"
        "# --suite conformance; never hand-edited (a hand edit fails the manifest test).\n"
        'licence = "Public market-data shape only (no account, order id, key or UID). '
        'Synthetic: generated, not recorded, so no third-party licence applies."\n'
        "public_market_data_only = true\n"
        f"reason = {_toml_str(reason or 'unchanged')}\n"
        f'builder_code_sha256 = "{builder_fingerprint()}"\n'
        f"[build_versions]\n{bv}\n\n[spec_hashes]\n{sh}\n\n"
    )


def _entry(
    name: str,
    d: tapes.TapeDef,
    tape: list[TradeEvent],
    blob: bytes,
    meta: dict[str, Any],
    gold: list[str],
) -> str:
    import hashlib

    ms = "".join(f"{k} = {_toml_str(str(v))}\n" for k, v in sorted(meta.items()))
    return (
        f"[[tape]]\nname = {_toml_str(name)}\nsymbol = {_toml_str(d.symbol)}\n"
        f"source_symbol_day = {_toml_str(d.source_symbol_day)}\n"
        f"description = {_toml_str(d.description)}\n"
        f"file = {_toml_str(_rel(tapes.tape_path(name)))}\nprint_count = {len(tape)}\n"
        f"sha256 = {_toml_str(hashlib.sha256(blob).hexdigest())}\n"
        "synthetic = true  # exception #1778 A: generated by bench.bar_determinism.tapes\n"
        'replace_with = "recorder capture (E16, epic #42 comment 6095472425)"\n'
        f"heavy = {str(d.heavy).lower()}\n"
        'licence_note = "public market data shape; synthetic, no account-scoped fields"\n'
        "goldens = [\n" + ",\n".join(gold) + ",\n]\n"
        f"[tape.meta]\n{ms}\n"
    )


def _rejected(label: str, msg: str) -> str:
    kind = "rejected-422-BarSpecError" if "ATR" in msg or "Heikin" in msg else "rejected"
    note = (
        "ADR-0033 defers ATR bricks; from_wire raises BarSpecError (422)"
        if "ATR" in msg
        else "not shipped as a builder: Heikin-Ashi is a chart transform over time bars "
        "(from_wire rejects it); E12-S02 follow-up if a builder is ever wanted"
    )
    return (
        f"[[rejected_pair]]\npair = {_toml_str(label)}\noutcome = {_toml_str(kind)}\n"
        f"message = {_toml_str(msg)}\nnote = {_toml_str(note)}\n\n"
    )


def write(p: Plan) -> None:
    for rel, data in p.files.items():
        path = tapes.REPO / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
