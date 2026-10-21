import json, os, re

DATE = "2026-09-24"
HERE = os.path.dirname(os.path.abspath(__file__))
# docs/plan/backlog/ (two levels up); the trailing separator stays: callers use ROOT + name
ROOT = os.path.normpath(os.path.join(HERE, "..", "..")) + os.sep

BANNER_TMPL = (
    "> **Re-scoped {date} for full xstate-statemachine adoption (ADR-0016 Accepted):** "
    "{note}\n\n"
)

SCOPE_BULLETS_TMPL = (
    "- Implement the `{bn}` lifecycle as `statechart/machines/{file}` "
    "(committed by {commit_story}, hash-locked). Do not hand-write the state enum or transition table.\n"
    "- Build it only through `statechart.factory.build('{mid}', lane=…)`, and restore it only through "
    "`statechart.persistence.restore`.\n"
    "- Write guards, actions and services in `statechart/bindings/{bnn}_{mid}.py` as a `MachineLogic`. "
    "Everything is `async def`, and services are idempotent under re-entry.\n"
    "- Add `tests/xstate_contract/test_{bnn}_{mid}.py`, which becomes a member of the blocking gate.\n"
    "- All sends go through `statechart.gateway`.\n"
)

TECH_NOTE_TMPL = (
    "\n**Statechart contract.** Normative contract: `28-statechart-catalogue.md` §{bn}.1–.8. "
    "Mandatory config: `29-statechart-adoption-plan.md` §1.2 (`79-r14-final-readiness-verdict.md` §7 FINAL block). "
    "Hot-path parts listed in `29-statechart-adoption-plan.md` §3 stay plain code.\n"
)

TEST_PLAN_TMPL = (
    "\n**Statechart test plan additions:**\n"
    "- Pure-API unit tests of the `{bnn}_{mid}` binding module using a `SimulatedClock`.\n"
    "- Contract-suite membership in `tests/xstate_contract/test_{bnn}_{mid}.py`, covering both spellings "
    "and every §{bn}.7 invariant.\n"
    "- A snapshot round-trip (persist→restore) at every quiescence point this ticket introduces, plus a "
    "refused restore on a `machine_hash` or HMAC mismatch.\n"
)

DOD_TMPL = (
    "\n**Statechart DoD additions:** `machine_hash` committed in `machine_hashes.lock`; "
    "`tools/lint_statecharts.py` green; `tests/xstate_contract` green; no import of `xstate_statemachine` "
    "outside `statechart/`.\n"
)


def apply_rescope(t, bn, mid, file_, bnn, note, commit_story, extra_blocked):
    body = t["body"]
    banner = BANNER_TMPL.format(date=DATE, note=note)
    # prepend to ## Context
    body = body.replace("## Context\n", "## Context\n" + banner, 1)

    scope_bullets = SCOPE_BULLETS_TMPL.format(
        bn=bn, file=file_, mid=mid, bnn=bnn, commit_story=commit_story
    )
    body = body.replace(
        "## Scope / Deliverables\n",
        "## Scope / Deliverables\n" + scope_bullets,
        1,
    )

    tech_note = TECH_NOTE_TMPL.format(bn=bn)
    body = body.replace(
        "## Technical notes / design\n",
        "## Technical notes / design\n" + tech_note,
        1,
    )

    test_plan = TEST_PLAN_TMPL.format(bnn=bnn, mid=mid, bn=bn)
    body = body.replace("## Test plan\n", "## Test plan\n" + test_plan, 1)

    dod = DOD_TMPL
    body = body.replace(
        "## Definition of Done\n", "## Definition of Done\n" + dod, 1
    )

    t["body"] = body

    if "statechart" not in t["labels"]:
        t["labels"].append("statechart")

    for k in extra_blocked:
        if k not in t["blocked_by"]:
            t["blocked_by"].append(k)

    return t


def load(f):
    return json.load(open(ROOT + f, encoding="utf-8"))


def dump(f, d):
    json.dump(d, open(ROOT + f, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    open(ROOT + f, "a", encoding="utf-8").write("\n")


TICKETS = [
    # file, key, bn, mid, file_name, bnn, note, new_estimate, persists, epic
    ("E39.json", "E39-S03", "B18", "kill_switch", "B18.kill_switch.machine.json", "b18",
     "the KillSwitch engine (states clear→engaging→engaged/error, C-07b unguarded RELEASE "
     "fall-through) is built directly on the library via the factory; the enum, transition "
     "table and snapshot/rehydrate code it replaces are dropped.",
     3, True, "E39"),
    ("E39.json", "E39-S02", "B20", "risk_lockout", "B20.risk_lockout.machine.json", "b20",
     "the automatic-lockout, day-boundary reset and step-up override lifecycle (clear→warning→locked) "
     "is built directly on the library via the factory; the day-boundary timer and override window "
     "are the chart's coarse `after:` states, not hand-rolled bookkeeping.",
     2, True, "E39"),
    ("E40.json", "E40-T03", "B10", "alert", "B10.alert.machine.json", "b10",
     "the gating, storm-suppression and snooze lifecycle (armed→…→firing→resolved) is built directly "
     "on the library via the factory; per-tick condition evaluation itself stays plain code "
     "(BENCH-2: 381 ev/s vs a 2000 ev/s target, hot-path exclusion, 29 §3).",
     2, True, "E40"),
    ("E44.json", "E44-T04", "B17", "live_gate", "B17.live_gate.machine.json", "b17",
     "the three-state live-trading gate (locked→eligible→enabled) is built directly on the library "
     "via the factory; the evidence-binding and audit logic that feeds the gate's guards stays as is.",
     3, True, "E44"),
    ("E45.json", "E45-T01", "B19", "reconciliation", "B19.reconciliation.machine.json", "b19",
     "the reconciliation core (idle→fetching→diffing→remediating→reporting) runs as a B19-invoked "
     "service; the diff/remediation logic dominates and is unchanged, so this ticket nets to zero "
     "points but the lifecycle itself is built directly on the library via the factory.",
     5, True, "E45"),
    ("E45.json", "E45-T02", "B19/B20", "reconciliation", "B19.reconciliation.machine.json", "b19",
     "the reconciliation-trigger scheduling and stale-account lockout lifecycle is B19 plus the B20 "
     "chart; `OPERATOR_RESOLVED` has an arm in every state (R12-15), built directly on the library "
     "via the factory, with no hand-rolled trigger state.",
     2, True, "E45"),
]


def main():
    by_file = {}
    for fname, key, bn, mid, file_, bnn, note, new_est, persists, epic in TICKETS:
        by_file.setdefault(fname, []).append(
            (key, bn, mid, file_, bnn, note, new_est, persists)
        )

    for fname, items in by_file.items():
        d = load(fname)
        idx = {t["key"]: t for t in d}
        for key, bn, mid, file_, bnn, note, new_est, persists in items:
            t = idx[key]
            old_est = t["estimate"]
            commit_story = "E50-S02"
            extra_blocked = ["E50-T59", "E50-S02"]
            if persists:
                extra_blocked.append("E50-T49")
            apply_rescope(t, bn, mid, file_, bnn, note, commit_story, extra_blocked)
            t["estimate"] = new_est
            print(f"{fname} {key}: pts {old_est} -> {new_est}")
        dump(fname, d)


if __name__ == "__main__":
    main()
