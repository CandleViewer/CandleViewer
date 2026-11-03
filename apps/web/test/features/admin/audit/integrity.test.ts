/**
 * E42-S04 (#1135): the session's integrity model (E42-D04 §7, D10, D11, AL-10 to AL-13, AD-5; the
 * plan's §3). It shows the served fields as served and compares ids only: it never hashes and never
 * re-links rows. A run's `verified: false` starts FAILED, which only a later pass from genesis to
 * the head ends; a partial pass, an acknowledged incident or a cleared alert never does. An open or
 * acknowledged `audit_chain_break` incident (component `db`, read on entry and every 60 s,
 * PROPOSED) holds the banner too, and each episode speaks once. The halt line keys on the served
 * `open` incident, which acknowledging lifts, never on the kill-switch frame's free-text reason
 * (the orchestrator's BQ-5). My activity never reads incidents: a Manager holds no `admin:read`.
 */
import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type {
  AuditAnswer,
  IncidentPageBody,
  VerifyResult,
} from "../../../../src/features/admin/audit/auditReads";
import { AUDIT_COPY as COPY } from "../../../../src/features/admin/audit/copy";
import {
  GENESIS_HASH,
  INCIDENT_POLL_MS,
  bannerModel,
  checkLine,
  createIntegrityStore,
  episodeVoice,
  footerModel,
  haltIncident,
  isSpoken,
  recordLine,
  useIntegrity,
  type IntegrityDeps,
} from "../../../../src/features/admin/audit/integrity";
import {
  BROKEN,
  FakeDocument,
  INCIDENT_ID,
  REF,
  T0,
  entries,
  entry,
  hex,
  incident,
  pageBody,
  verifyBody,
} from "./fixtures";

interface Pending<T> {
  readonly signal?: AbortSignal;
  readonly answer: (outcome: AuditAnswer<T>) => Promise<void>;
}

function setup() {
  vi.useFakeTimers();
  vi.setSystemTime(T0);
  const doc = new FakeDocument();
  const reads: Pending<IncidentPageBody>[] = [];
  const checks: Pending<VerifyResult>[] = [];
  const settle = async (): Promise<void> => {
    await vi.advanceTimersByTimeAsync(0);
  };
  const deps: IntegrityDeps = {
    now: () => Date.now(),
    setTimeout: (run, ms) => setTimeout(run, ms),
    clearTimeout: (handle) => clearTimeout(handle as ReturnType<typeof setTimeout>),
    document: doc as unknown as Document,
    readIncidents: (signal) =>
      new Promise((resolve) => {
        reads.push({ signal, answer: async (o) => (resolve(o), settle()) });
      }),
    verify: () =>
      new Promise((resolve) => {
        checks.push({ answer: async (o) => (resolve(o), settle()) });
      }),
  };
  const store = createIntegrityStore(deps);
  const lastCheck = (): Pending<VerifyResult> => {
    const call = checks.at(-1);
    if (call === undefined) throw new Error("no check was run");
    return call;
  };
  const lastRead = (): Pending<IncidentPageBody> => {
    const call = reads.at(-1);
    if (call === undefined) throw new Error("no incident read was asked");
    return call;
  };
  /** Runs one check and answers it. */
  const run = async (outcome: AuditAnswer<VerifyResult>): Promise<void> => {
    expect(store.runCheck()).toBe(true);
    await lastCheck().answer(outcome);
  };
  return { store, doc, reads, checks, lastCheck, lastRead, run };
}

const ok = <T>(body: T): AuditAnswer<T> => ({ kind: "ok", body });
const incidents = (...items: ReturnType<typeof incident>[]): AuditAnswer<IncidentPageBody> =>
  ok({ items, meta: { next_cursor: null, has_more: false, count: items.length } });
const LATER = "2026-10-22T14:20:00Z";
const GENESIS_PASS = verifyBody({ anchor_hash: GENESIS_HASH, from_id: 1, checked_at: LATER });

afterEach(() => {
  vi.useRealTimers();
});

describe("Run tamper check (D10, D11, AL-11, AL-12)", () => {
  it("test_check_pass_records_its_range_and_says_range_passed", async () => {
    const { store, lastCheck } = setup();
    expect(store.runCheck()).toBe(true);
    expect(checkLine(store.getState())).toEqual({
      key: "tamper.checking",
      text: "Checking entries…",
    });
    expect(store.runCheck()).toBe(false); // busy while it runs
    await lastCheck().answer(ok(verifyBody()));
    expect(store.getState().passes).toEqual([
      { fromId: 204_119, toId: 1_204_118, checkedAt: "2026-10-22T14:05:07Z" },
    ]);
    expect(checkLine(store.getState())).toEqual({
      key: "tamper.range_passed",
      text: "Tamper check: entries 204,119–1,204,118 checked at 14:05 UTC — passed. This covers that range only.",
    });
  });

  it("test_check_empty_pass_proves_nothing_and_records_no_range", async () => {
    const { store, run } = setup();
    await run(ok(verifyBody({ entries_checked: 0, from_id: null, to_id: null, last_hash: null })));
    expect(store.getState().passes).toEqual([]);
    expect(checkLine(store.getState())?.key).toBe("tamper.range_empty");
    await run(ok(verifyBody({ entries_checked: 0, last_hash: null }))); // bounds, no entries
    expect(store.getState().passes).toEqual([]);
    expect(checkLine(store.getState())?.key).toBe("tamper.range_empty");
  });

  it.each([
    [{ kind: "refused", status: 409, code: "conflict" }, "tamper.busy", COPY.tamper.busy],
    [
      { kind: "refused", status: 503, code: "store_unavailable", retryAfterS: 30 },
      "tamper.stopped",
      COPY.tamper.stopped("14:02:41"),
    ],
    [
      { kind: "refused", status: 503, code: "store_unavailable" },
      "tamper.stopped_entry",
      COPY.tamper.stoppedEntry,
    ],
    [
      { kind: "refused", status: 403, code: "session_read_only" },
      "inflight.read_only",
      "Not sent — read-only after three wrong codes.",
    ],
    [{ kind: "unknown" }, "tamper.no_answer", COPY.tamper.noAnswer],
    [
      { kind: "refused", status: 500, code: "internal_error" },
      "tamper.not_run",
      COPY.tamper.notRun,
    ],
  ] as const)("test_check_refusal_%#_has_its_line", async (outcome, key, text) => {
    const { store, run } = setup();
    await run(outcome as AuditAnswer<VerifyResult>);
    expect(checkLine(store.getState())).toEqual({ key, text });
  });

  it("test_check_view_as_refusal_is_not_sent_with_the_view_as_sentence", async () => {
    const { store, run } = setup();
    await run({ kind: "refused", status: 403, code: "view_as_read_only" });
    expect(
      checkLine(store.getState(), { viewAsReason: "Read-only while viewing as alex." })?.text,
    ).toBe("Not sent — your access changed. Read-only while viewing as alex.");
  });

  it("test_check_429_blocks_the_button_until_retry_after", async () => {
    const { store, run } = setup();
    await run({ kind: "refused", status: 429, code: "rate_limited", retryAfterS: 600 });
    expect(store.getState().check).toEqual({ kind: "limited", until: T0 + 600_000 });
    expect(checkLine(store.getState())?.text).toBe(
      "Too many tamper checks this hour — try again at 14:12 UTC.",
    );
    expect(store.runCheck()).toBe(false);
    await vi.advanceTimersByTimeAsync(600_000);
    expect(store.runCheck()).toBe(true);
  });

  it("test_check_owner_403_forbidden_withdraws_the_area", async () => {
    const { store, run } = setup();
    await run({ kind: "refused", status: 403, code: "forbidden", refId: REF });
    expect(store.getState().denied).toEqual({ refId: REF });
    expect(store.runCheck()).toBe(false);
  });

  it("test_check_lands_after_the_page_is_left_because_the_episode_is_the_sessions", async () => {
    const { store, lastCheck } = setup();
    const release = store.hold();
    store.runCheck();
    release();
    await vi.advanceTimersByTimeAsync(0);
    await lastCheck().answer(ok(BROKEN));
    expect(store.getState().failed?.firstBadId).toBe(1_204_118);
  });
});

describe("FAILED (D11, §7, AL-13)", () => {
  it("test_failed_run_names_the_entry_its_facts_and_the_copy_details", async () => {
    const { store, run, lastRead } = setup();
    const release = store.hold();
    await lastRead().answer(incidents());
    await run(ok(BROKEN));
    expect(checkLine(store.getState())).toBeNull(); // the banner speaks, not the footer
    // A-1135P2-09: the banner waits for the incident read the break sent, then speaks once
    expect(bannerModel(store.getState())).toBeNull();
    await lastRead().answer(incidents());
    expect(bannerModel(store.getState())).toEqual({
      voice: "break:1204118",
      entryId: 1_204_118,
      title: "Tamper check FAILED at entry 1,204,118 — treat this as a security incident",
      facts: "Found at 14:05:07 UTC on 2026-10-22 in a check of entries 204,119–1,204,118.",
      meaning: COPY.tamper.failed.meaning,
      // C-1135P2-08: no incident served, so never "does not stop order entry"
      safe: COPY.tamper.failed.mayBeHalted,
      halted: false,
      recheck: COPY.tamper.failed.recheck,
      steps: COPY.tamper.failed.steps,
      details: [
        "first_bad_id: 1204118",
        "checked_at: 2026-10-22T14:05:07Z",
        "from_id: 204119",
        "to_id: 1204118",
        `last_hash: ${hex("4")}`,
        `anchor_hash: ${hex("e")}`,
      ].join("\n"),
    });
    release();
  });

  it("test_failed_run_whose_incident_read_fails_shows_the_banner_saying_it_may_be_halted", async () => {
    const { store, run, lastRead } = setup();
    const release = store.hold();
    await lastRead().answer(incidents());
    await run(ok(BROKEN));
    expect(bannerModel(store.getState())).toBeNull();
    await lastRead().answer({ kind: "failed", reason: "timeout" });
    expect(bannerModel(store.getState())).toMatchObject({
      voice: "break:1204118",
      safe: COPY.tamper.failed.mayBeHalted,
      halted: false,
    });
    release();
  });

  it("test_failed_run_after_the_page_let_go_is_read_at_once_on_the_next_hold", async () => {
    // the break waits for its incident: a quick return reads it now, not when its 60 s are up
    const { store, reads, run, lastRead } = setup();
    const first = store.hold();
    await lastRead().answer(incidents());
    first();
    await vi.advanceTimersByTimeAsync(0);
    await run(ok(BROKEN));
    expect(reads).toHaveLength(1);
    expect(bannerModel(store.getState())).toBeNull();
    const again = store.hold();
    expect(reads).toHaveLength(2);
    await lastRead().answer(incidents(incident()));
    expect(bannerModel(store.getState())).toMatchObject({ halted: true });
    again();
  });

  it("test_failed_holds_through_a_partial_pass_and_an_acknowledged_incident", async () => {
    const { store, run, lastRead } = setup();
    await run(ok(BROKEN));
    await run(ok(verifyBody({ checked_at: LATER }))); // a pass, not from genesis
    expect(store.getState().failed).not.toBeNull();
    const release = store.hold();
    await lastRead().answer(incidents(incident({ status: "acknowledged" })));
    expect(store.getState().failed).not.toBeNull();
    expect(bannerModel(store.getState())?.voice).toBe("break:1204118");
    release();
  });

  it("test_genesis_pass_ends_the_sessions_failed_while_an_open_incident_keeps_the_banner", async () => {
    const { store, run, lastRead } = setup();
    const release = store.hold();
    await lastRead().answer(incidents(incident()));
    await run(ok(BROKEN));
    await run(ok(GENESIS_PASS));
    expect(store.getState().failed).toBeNull();
    expect(bannerModel(store.getState())?.title).toBe(
      "Tamper check FAILED at entry 1,204,118 — treat this as a security incident",
    );
    await vi.advanceTimersByTimeAsync(INCIDENT_POLL_MS);
    await lastRead().answer(incidents(incident({ status: "resolved" })));
    expect(bannerModel(store.getState())).toBeNull();
    release();
  });

  it("test_incident_alone_raises_the_banner_from_its_served_text", async () => {
    const { store, lastRead } = setup();
    const release = store.hold();
    await lastRead().answer(
      incidents(
        incident({ id: "1a000000-0000-4000-8000-000000000001", component: "recorder" }),
        incident(),
      ),
    );
    expect(bannerModel(store.getState())).toMatchObject({
      voice: "break:1204118",
      entryId: 1_204_118,
      title: "Tamper check FAILED at entry 1,204,118 — treat this as a security incident",
      facts: "Found at 14:05:07 UTC on 2026-10-22.",
      details: [
        `incident: ${INCIDENT_ID}`,
        "status: open",
        "first_seen_at: 2026-10-22T14:05:07Z",
        "detail: audit chain break at id 1204118",
      ].join("\n"),
    });
    release();
  });

  it("test_incident_naming_no_entry_still_raises_the_banner_without_one", async () => {
    const { store, lastRead } = setup();
    const release = store.hold();
    await lastRead().answer(incidents(incident({ detail: null })));
    expect(bannerModel(store.getState())).toMatchObject({
      voice: `incident:${INCIDENT_ID}`,
      entryId: null,
      title: COPY.tamper.failed.titleUnknown,
    });
    release();
  });

  it.each([
    ["another component", { component: "recorder" }],
    ["another title", { title: "audit writer stalled" }],
    ["a resolved one", { status: "resolved" as const }],
  ])("test_incident_of_%s_raises_no_banner", async (_name, change) => {
    const { store, lastRead } = setup();
    const release = store.hold();
    await lastRead().answer(incidents(incident(change)));
    expect(bannerModel(store.getState())).toBeNull();
    release();
  });

  it("test_one_voice_per_episode", async () => {
    const { store, run } = setup();
    await run(ok(BROKEN));
    const voice = episodeVoice(store.getState());
    expect(voice).toBe("break:1204118");
    expect(isSpoken(store.getState(), "break:1204118")).toBe(false);
    store.markSpoken("break:1204118");
    expect(isSpoken(store.getState(), "break:1204118")).toBe(true);
    await run(ok({ ...BROKEN, first_bad_id: 1_204_200, checked_at: LATER }));
    expect(episodeVoice(store.getState())).toBe("break:1204200");
    expect(isSpoken(store.getState(), "break:1204200")).toBe(false);
  });

  it("test_failed_run_reads_incidents_once_at_once_so_the_halt_line_never_lags", async () => {
    // The orchestrator's Q2 (a): the break a run finds raises its incident, so the incidents are
    // read again at once, not on the next 60 s tick; one extra `admin.area_entered` row.
    const { store, reads, run, lastRead } = setup();
    const release = store.hold();
    await lastRead().answer(incidents()); // the entry's read: no incident yet
    await vi.advanceTimersByTimeAsync(10_000);
    await run(ok(BROKEN));
    expect(reads).toHaveLength(2);
    await lastRead().answer(incidents(incident()));
    expect(bannerModel(store.getState())).toMatchObject({
      safe: COPY.tamper.failed.halted,
      halted: true,
    });
    // the cadence starts again from that answer: one read more in all, never a second loop
    await vi.advanceTimersByTimeAsync(INCIDENT_POLL_MS - 1);
    expect(reads).toHaveLength(2);
    await vi.advanceTimersByTimeAsync(1);
    expect(reads).toHaveLength(3);
    release();
  });

  it("test_failed_run_replaces_an_incident_read_already_in_flight", async () => {
    // a read sent before the break was recorded may miss its incident: it is dropped for a new one
    const { store, reads, run } = setup();
    const release = store.hold();
    const first = reads[0];
    await run(ok(BROKEN));
    expect(first?.signal?.aborted).toBe(true);
    expect(reads).toHaveLength(2);
    release();
  });

  it.each([
    ["a passing run", ok(verifyBody())],
    ["a refused run", { kind: "refused", status: 409, code: "conflict" } as const],
  ])("test_%s_reads_no_extra_incidents", async (_name, outcome) => {
    const { store, reads, run, lastRead } = setup();
    const release = store.hold();
    await lastRead().answer(incidents());
    await run(outcome as AuditAnswer<VerifyResult>);
    expect(reads).toHaveLength(1);
    release();
  });

  it("test_failed_run_reads_no_incidents_once_the_page_has_let_go", async () => {
    // My activity never reads them, and a page that is gone reads nothing (BQ-4)
    const { store, reads, run } = setup();
    const own = store.hold("own");
    await run(ok(BROKEN));
    own();
    const raw = store.hold();
    expect(reads).toHaveLength(1); // the entry's read alone
    raw();
    await vi.advanceTimersByTimeAsync(0);
    await run(ok({ ...BROKEN, checked_at: LATER }));
    expect(reads).toHaveLength(1);
  });

  it("test_halt_line_follows_the_served_open_incident_and_lifts_on_acknowledge", async () => {
    const { store, run, lastRead } = setup();
    await run(ok(BROKEN)); // the session's own run: no incident served yet
    expect(haltIncident(store.getState())).toBeNull();
    expect(bannerModel(store.getState())).toBeNull(); // it waits for the incident read
    const release = store.hold();
    await lastRead().answer(incidents(incident()));
    expect(haltIncident(store.getState())?.id).toBe(INCIDENT_ID);
    expect(bannerModel(store.getState())).toMatchObject({
      safe: COPY.tamper.failed.halted,
      halted: true,
    });
    await vi.advanceTimersByTimeAsync(INCIDENT_POLL_MS);
    await lastRead().answer(incidents(incident({ status: "acknowledged" })));
    expect(haltIncident(store.getState())).toBeNull();
    expect(bannerModel(store.getState())).toMatchObject({
      safe: COPY.tamper.failed.safe,
      halted: false,
    });
    release();
  });
});

describe("the incident read (§7): on entry and every 60 s while visible", () => {
  it("test_my_activity_never_reads_incidents", async () => {
    // BQ-4: `listIncidents` needs `admin:read`, which a Manager does not hold
    const { store, reads } = setup();
    const release = store.hold("own");
    await vi.advanceTimersByTimeAsync(INCIDENT_POLL_MS * 3);
    expect(reads).toHaveLength(0);
    expect(vi.getTimerCount()).toBe(0);
    release();
  });

  it("test_incident_read_polls_every_60s_pauses_hidden_and_stops_on_release", async () => {
    const { store, doc, reads, lastRead } = setup();
    const release = store.hold();
    expect(reads).toHaveLength(1);
    await lastRead().answer(incidents());
    await vi.advanceTimersByTimeAsync(INCIDENT_POLL_MS);
    expect(reads).toHaveLength(2);
    await lastRead().answer(incidents());
    doc.show("hidden");
    await vi.advanceTimersByTimeAsync(INCIDENT_POLL_MS * 3);
    expect(reads).toHaveLength(2);
    doc.show("visible");
    expect(reads).toHaveLength(3);
    const open = lastRead();
    release();
    await vi.advanceTimersByTimeAsync(0);
    expect(open.signal?.aborted).toBe(true);
    expect(vi.getTimerCount()).toBe(0);
    expect(doc.listeners).toBe(0);
  });

  it("test_incident_read_on_a_quick_return_waits_for_its_60s", async () => {
    const { store, reads, lastRead } = setup();
    const release = store.hold();
    await lastRead().answer(incidents());
    release();
    await vi.advanceTimersByTimeAsync(10_000);
    const again = store.hold();
    expect(reads).toHaveLength(1);
    await vi.advanceTimersByTimeAsync(INCIDENT_POLL_MS - 10_000);
    expect(reads).toHaveLength(2);
    again();
  });

  it("test_failed_incident_read_keeps_the_last_banner_and_says_unavailable", async () => {
    const { store, lastRead } = setup();
    const release = store.hold();
    await lastRead().answer(incidents(incident()));
    await vi.advanceTimersByTimeAsync(INCIDENT_POLL_MS);
    await lastRead().answer({ kind: "refused", status: 501, code: "not_implemented" });
    expect(store.getState().incidentRead).toBe("unavailable");
    expect(bannerModel(store.getState())).not.toBeNull();
    const page = pageBody([entry()]);
    expect(footerModel(store.getState(), page, { view: "raw" }).incidents).toEqual({
      key: "tamper.incidents_unavailable",
      text: "Tamper status: incident log unavailable",
    });
    release();
  });

  it("test_incident_read_403_forbidden_under_view_as_is_the_targets_never_withdrawn", async () => {
    // C-1135P2-07 / S-1135P2-01: the holding page's view-as source reaches the session's store
    const { store, lastRead } = setup();
    const release = store.hold("raw", () => true);
    await lastRead().answer({ kind: "refused", status: 403, code: "forbidden", refId: REF });
    expect(store.getState()).toMatchObject({ denied: null, incidentRead: "unavailable" });
    release();
  });

  it("test_owner_403_on_the_incident_read_withdraws_and_reads_nothing_more", async () => {
    const { store, reads, lastRead } = setup();
    const release = store.hold();
    await lastRead().answer({ kind: "refused", status: 403, code: "forbidden", refId: REF });
    expect(store.getState().denied).toEqual({ refId: REF });
    await vi.advanceTimersByTimeAsync(INCIDENT_POLL_MS * 2);
    expect(reads).toHaveLength(1);
    release();
  });
});

describe("the footer and the record lines (D04 §4's table, AD-1, AD-5)", () => {
  const PAGE = pageBody(entries(3));

  it("test_footer_line_by_page_state", async () => {
    const { store, run } = setup();
    const s = (): ReturnType<typeof store.getState> => store.getState();
    expect(footerModel(s(), null, { view: "raw" }).line).toBeNull();
    expect(footerModel(s(), pageBody([]), { view: "raw" }).line).toBeNull();
    expect(footerModel(s(), PAGE, { view: "raw" }).line).toEqual({
      key: "tamper.page_passed",
      text: COPY.tamper.pagePassed,
      failed: false,
    });
    const partial = pageBody(entries(3), { chain: false });
    expect(footerModel(s(), partial, { view: "raw" }).line?.key).toBe("tamper.page_partial");
    expect(footerModel(s(), partial, { view: "own" }).line?.key).toBe("tamper.page_partial_own");
    expect(footerModel(s(), PAGE, { view: "raw", newestPartial: true }).line?.key).toBe(
      "tamper.newest_partial",
    );
    expect(footerModel(s(), PAGE, { view: "own", newestPartial: true }).line?.key).toBe(
      "tamper.page_partial_own",
    );
    expect(footerModel(s(), PAGE, { view: "raw" }).incidents).toBeNull();
    await run(ok(BROKEN));
    expect(footerModel(s(), PAGE, { view: "raw" }).line).toEqual({
      key: "tamper.failed.title",
      text: "Tamper check FAILED at entry 1,204,118 — treat this as a security incident",
      failed: true,
    });
    // BQ-4: My activity's lines stay neutral, whatever the session holds
    expect(footerModel(s(), PAGE, { view: "own" }).line?.key).toBe("tamper.page_passed");
    expect(footerModel(s(), partial, { view: "own" }).line?.key).toBe("tamper.page_partial_own");
  });

  it("test_record_line_after_break_wins_then_the_latest_passing_range_then_not_checked", async () => {
    const { store, run } = setup();
    expect(recordLine(store.getState(), entry({ id: 1_000_000 }))).toEqual({
      key: "rec.not_checked",
      text: COPY.rec.notChecked,
      tone: "neutral",
    });
    await run(ok(verifyBody({ from_id: 1, to_id: 2_000_000, checked_at: "2026-10-22T13:00:00Z" })));
    await run(ok(verifyBody()));
    expect(recordLine(store.getState(), entry({ id: 1_000_000 }))).toEqual({
      key: "rec.verified_to",
      text: "In entries 204,119–1,204,118, checked at 14:05 UTC — passed (last tamper check).",
      tone: "neutral",
    });
    expect(recordLine(store.getState(), entry({ id: 100 })).text).toBe(
      "In entries 1–2,000,000, checked at 13:00 UTC — passed (last tamper check).",
    );
    await run(ok({ ...BROKEN, checked_at: LATER }));
    for (const id of [1_204_118, 1_500_000]) {
      expect(recordLine(store.getState(), entry({ id }))).toEqual({
        key: "rec.after_break",
        text: "Not verified — at or after the break at entry 1,204,118.",
        tone: "danger",
      });
    }
    expect(recordLine(store.getState(), entry({ id: 1_204_117 })).key).toBe("rec.verified_to");
  });
});

describe("useIntegrity", () => {
  it("test_useIntegrity_rerenders_on_a_change_it_selects", async () => {
    const { store, run } = setup();
    const { result } = renderHook(() => useIntegrity((s) => s.failed?.firstBadId ?? null, store));
    expect(result.current).toBeNull();
    await act(async () => {
      await run(ok(BROKEN));
    });
    expect(result.current).toBe(1_204_118);
  });
});
