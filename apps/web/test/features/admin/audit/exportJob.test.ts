/**
 * E42-S04 (#1135): the session's signed export (E42-D04 §8, D12, D13, X1 to X12; the orchestrator's
 * BQ-7). One `Idempotency-Key` per export, kept for [Check again]; a `403 step_up_required` held
 * for the shipped gate and re-sent once; the job polled at 2 s, then 1 s longer each time to 5 s,
 * while held and visible; a failed poll never fails the job; and the download's every answer.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import type {
  AuditAnswer,
  ExportAccepted,
  ExportFile,
  Job,
} from "../../../../src/features/admin/audit/auditReads";
import { holdRequest, type StepUpChallenge } from "../../../../src/features/stepUp/challenge";
import {
  createExportStore,
  rangeDays,
  type ExportDeps,
  type ExportWindow,
} from "../../../../src/features/admin/audit/exportJob";
import { FakeDocument, JOB_ID, REF, T0, exportResult, job, problem } from "./fixtures";

const WINDOW: ExportWindow = {
  from: "2026-10-21T14:00:00Z",
  to: "2026-10-22T14:00:00Z",
  compress: true,
};
const CHALLENGE: StepUpChallenge = {
  challengeId: "6f1d2c3b-4a5e-4f60-8a7b-9c0d1e2f3a4b",
  expiresAt: "2026-10-22T14:07:11Z",
  actionClass: "audit",
  actionSummary: "Export the audit log from 2026-10-21 14:00 to 2026-10-22 14:00 (UTC)",
  target: null,
  clockOffsetMs: 0,
};
const HELD = holdRequest("POST", "/api/v1/admin/audit/export", {}, "{}");

interface Pending<T> {
  readonly key?: string;
  readonly signal?: AbortSignal;
  readonly answer: (outcome: AuditAnswer<T>) => Promise<void>;
}

function setup() {
  vi.useFakeTimers();
  vi.setSystemTime(T0);
  const doc = new FakeDocument();
  const starts: Pending<ExportAccepted>[] = [];
  const polls: Pending<Job>[] = [];
  const downloads: Pending<ExportFile>[] = [];
  const saved: ExportFile[] = [];
  let keys = 0;
  const settle = async (): Promise<void> => {
    await vi.advanceTimersByTimeAsync(0);
  };
  const pending = <T>(list: Pending<T>[], extra: { key?: string; signal?: AbortSignal }) =>
    new Promise<AuditAnswer<T>>((resolve) => {
      list.push({ ...extra, answer: async (o) => (resolve(o), settle()) });
    });
  const deps: ExportDeps = {
    now: () => Date.now(),
    setTimeout: (run, ms) => setTimeout(run, ms),
    clearTimeout: (handle) => clearTimeout(handle as ReturnType<typeof setTimeout>),
    document: doc as unknown as Document,
    newKey: () => `key-${String((keys += 1))}`,
    start: (_body, key) => pending(starts, { key }),
    poll: (_jobId, signal) => pending(polls, { signal }),
    download: (_jobId, signal) => pending(downloads, { signal }),
    save: (file) => void saved.push(file),
  };
  const store = createExportStore(deps);
  const last = <T>(list: Pending<T>[]): Pending<T> => {
    const call = list.at(-1);
    if (call === undefined) throw new Error("nothing was asked");
    return call;
  };
  return { store, doc, starts, polls, downloads, saved, last };
}

const ok = <T>(body: T): AuditAnswer<T> => ({ kind: "ok", body });
const accepted = ok<ExportAccepted>({ job_id: JOB_ID, download_url: null });
const refused = (status: number, code: string, extra: object = {}): AuditAnswer<never> =>
  ({ kind: "refused", status, code, ...extra }) as AuditAnswer<never>;
const stepUp = refused(403, "step_up_required", { stepUp: { challenge: CHALLENGE, held: HELD } });

afterEach(() => {
  vi.useRealTimers();
});

describe("the start (D12, X1 to X4, X11)", () => {
  it("test_export_start_sends_one_idempotency_id_per_export", async () => {
    const { store, starts, last } = setup();
    expect(store.start(WINDOW)).toBe(true);
    expect(store.getState().phase.kind).toBe("starting");
    expect(store.start(WINDOW)).toBe(false); // one at a time
    await last(starts).answer(refused(409, "conflict"));
    expect(store.getState().phase).toEqual({ kind: "refused", refusal: { kind: "busy" } });
    expect(store.start(WINDOW)).toBe(true);
    expect(starts.map((s) => s.key)).toEqual(["key-1", "key-2"]);
  });

  it("test_export_no_answer_is_unknown_and_check_again_resends_the_same_request", async () => {
    const { store, starts, last } = setup();
    store.start(WINDOW);
    await last(starts).answer({ kind: "unknown" });
    expect(store.getState().phase.kind).toBe("unknown");
    expect(store.checkAgain()).toBe(true);
    await last(starts).answer(accepted);
    expect(starts.map((s) => s.key)).toEqual(["key-1", "key-1"]);
    expect(store.getState().phase).toMatchObject({ kind: "running", jobId: JOB_ID, pct: null });
  });

  it("test_export_step_up_holds_the_request_for_the_gate_and_reads_its_one_resend", async () => {
    const { store, starts, last } = setup();
    store.start(WINDOW);
    await last(starts).answer(stepUp);
    expect(store.getState().phase).toMatchObject({ kind: "step_up", retried: false });
    const reply = new Response(JSON.stringify({ job_id: JOB_ID, download_url: null }), {
      status: 202,
      headers: { "Content-Type": "application/json" },
    });
    await store.resentStart(reply);
    expect(store.getState().phase).toMatchObject({ kind: "running", jobId: JOB_ID });
    expect(starts).toHaveLength(1); // the gate re-sent it, not the store
  });

  it("test_export_challenge_on_the_resend_opens_one_more_gate_then_refuses", async () => {
    const { store, starts, last } = setup();
    store.start(WINDOW);
    await last(starts).answer(stepUp);
    await store.resentStart(problem(403, "step_up_required", { ...stepUpBody() }));
    expect(store.getState().phase).toMatchObject({ kind: "step_up", retried: true });
    await store.resentStart(problem(403, "step_up_required", { ...stepUpBody() }));
    expect(store.getState().phase).toEqual({ kind: "refused", refusal: { kind: "other" } });
  });

  it.each([
    [
      refused(422, "validation_failed", { detail: "longer than 31 days" }),
      { kind: "range", days: "31" },
    ],
    [refused(503, "signing_unavailable"), { kind: "signing" }],
    [refused(503, "store_unavailable", { retryAfterS: 5 }), { kind: "store" }],
    [refused(403, "session_read_only"), { kind: "read_only" }],
    [refused(403, "view_as_read_only"), { kind: "view_as" }],
  ])("test_export_refusal_%#_is_said_in_the_dialog", async (answer, refusal) => {
    const { store, starts, last } = setup();
    store.start(WINDOW);
    await last(starts).answer(answer);
    expect(store.getState().phase).toEqual({ kind: "refused", refusal });
  });

  it("test_export_429_blocks_a_new_start_until_retry_after", async () => {
    const { store, starts, last } = setup();
    store.start(WINDOW);
    await last(starts).answer(refused(429, "rate_limited", { retryAfterS: 120 }));
    expect(store.getState().limitedUntil).toBe(T0 + 120_000);
    expect(store.start(WINDOW)).toBe(false);
    await vi.advanceTimersByTimeAsync(120_000);
    expect(store.getState().limitedUntil).toBeNull();
    expect(store.start(WINDOW)).toBe(true);
  });

  it("test_export_501_is_not_built_and_an_owner_403_withdraws_the_area", async () => {
    const built = setup();
    built.store.start(WINDOW);
    await built.last(built.starts).answer(refused(501, "not_implemented"));
    expect(built.store.getState().phase.kind).toBe("not_built");
    vi.useRealTimers();
    const gone = setup();
    gone.store.start(WINDOW);
    await gone.last(gone.starts).answer(refused(403, "forbidden", { refId: REF }));
    expect(gone.store.getState().denied).toEqual({ refId: REF });
    expect(gone.store.start(WINDOW)).toBe(false);
  });

  it("test_export_rangeDays_reads_the_limit_the_problem_names", () => {
    expect(rangeDays("The window may span at most 14 days.")).toBe("14");
    // the served detail (`api/audit.py`): before, this fell back to 31 whatever the limit
    expect(rangeDays("the window is longer than audit_export_max_range_days (14)")).toBe("14");
    expect(rangeDays(undefined)).toBe("31");
  });

  it("test_export_409_a_reused_idempotency_id_is_the_other_refusal_not_busy", async () => {
    const { store, starts, last } = setup();
    store.start(WINDOW);
    await last(starts).answer(refused(409, "idempotency_key_reuse"));
    expect(store.getState().phase).toEqual({ kind: "refused", refusal: { kind: "other" } });
  });
});

/** A `403 step_up_required` body for the `audit` class. */
function stepUpBody(): Record<string, unknown> {
  return {
    action_class: "audit",
    challenge_id: CHALLENGE.challengeId,
    challenge_expires_at: CHALLENGE.expiresAt,
    action_summary: CHALLENGE.actionSummary,
    target: null,
  };
}

describe("the job (D13 as BQ-7 overrides it, X5 to X9, X12)", () => {
  async function running() {
    const s = setup();
    const release = s.store.hold();
    s.store.start(WINDOW);
    await s.last(s.starts).answer(accepted);
    return { ...s, release };
  }

  it("test_export_polls_at_2s_then_one_second_longer_each_time_up_to_5s", async () => {
    const { polls, last, release } = await running();
    const at: number[] = [];
    for (const wait of [2_000, 3_000, 4_000, 5_000, 5_000]) {
      await vi.advanceTimersByTimeAsync(wait - 1);
      expect(polls).toHaveLength(at.length);
      await vi.advanceTimersByTimeAsync(1);
      at.push(Date.now() - T0);
      await last(polls).answer(ok(job({ progress_pct: 10 * at.length })));
    }
    expect(at).toEqual([2_000, 5_000, 9_000, 14_000, 19_000]);
    release();
  });

  it("test_export_failed_poll_keeps_the_last_pct_and_never_fails_the_job", async () => {
    const { store, polls, last, release } = await running();
    await vi.advanceTimersByTimeAsync(2_000);
    await last(polls).answer(ok(job({ progress_pct: 42 })));
    await vi.advanceTimersByTimeAsync(3_000);
    await last(polls).answer(refused(503, "audit_unavailable"));
    expect(store.getState().phase).toMatchObject({ kind: "running", pct: 42, pollFailed: true });
    await vi.advanceTimersByTimeAsync(4_000);
    await last(polls).answer(ok(job({ progress_pct: 60 })));
    expect(store.getState().phase).toMatchObject({ kind: "running", pct: 60, pollFailed: false });
    release();
  });

  it.each([
    [ok(job({ status: "succeeded", progress_pct: 100, result: exportResult() })), "succeeded"],
    [ok(job({ status: "failed", error: "export_too_large" })), "failed"],
    [ok(job({ status: "cancelled" })), "cancelled"],
    [refused(404, "job_unknown"), "lost"],
  ] as const)("test_export_terminal_answer_%#_stops_the_polls", async (answer, kind) => {
    const { store, polls, last, release } = await running();
    await vi.advanceTimersByTimeAsync(2_000);
    await last(polls).answer(answer as AuditAnswer<Job>);
    expect(store.getState().phase.kind).toBe(kind);
    await vi.advanceTimersByTimeAsync(60_000);
    expect(polls).toHaveLength(1);
    release();
  });

  it("test_export_ten_failed_polls_in_a_row_back_off_to_30s_until_one_answers", async () => {
    // C-1135P2-16: an unreadable job is not polled at 5 s (12 audit rows a minute) for ever
    const { store, polls, last, release } = await running();
    for (let n = 0; n < 10; n += 1) {
      await vi.advanceTimersByTimeAsync(5_000);
      await last(polls).answer(refused(503, "audit_unavailable"));
    }
    expect(polls).toHaveLength(10);
    await vi.advanceTimersByTimeAsync(29_999);
    expect(polls).toHaveLength(10);
    await vi.advanceTimersByTimeAsync(1);
    expect(polls).toHaveLength(11);
    await last(polls).answer(ok(job({ progress_pct: 80 })));
    expect(store.getState().phase).toMatchObject({ pct: 80, pollFailed: false });
    await vi.advanceTimersByTimeAsync(5_000);
    expect(polls).toHaveLength(12); // back to the 5 s cap once a poll answers
    release();
  });

  it("test_export_poll_that_lands_while_hidden_arms_nothing_until_visible", async () => {
    // C-1135P2-09: a hidden tab never re-arms the 2 to 5 s poll
    const { doc, polls, last, release } = await running();
    await vi.advanceTimersByTimeAsync(2_000);
    expect(polls).toHaveLength(1);
    doc.show("hidden");
    await last(polls).answer(ok(job({ progress_pct: 10 })));
    expect(vi.getTimerCount()).toBe(0);
    await vi.advanceTimersByTimeAsync(30_000);
    expect(polls).toHaveLength(1);
    doc.show("visible");
    await vi.advanceTimersByTimeAsync(3_000);
    expect(polls).toHaveLength(2);
    release();
  });

  it("test_export_poll_403_forbidden_under_view_as_is_the_targets_never_withdrawn", async () => {
    // C-1135P2-07 / S-1135P2-01: the holding page's view-as source reaches the session's store
    const s = setup();
    const release = s.store.hold(() => true);
    s.store.start(WINDOW);
    await s.last(s.starts).answer(accepted);
    await vi.advanceTimersByTimeAsync(2_000);
    await s.last(s.polls).answer(refused(403, "forbidden", { refId: REF }));
    expect(s.store.getState()).toMatchObject({ denied: null, phase: { pollFailed: true } });
    release();
  });

  it("test_export_polls_pause_while_hidden_and_stop_when_the_page_lets_go", async () => {
    const { doc, polls, last, release } = await running();
    doc.show("hidden");
    await vi.advanceTimersByTimeAsync(30_000);
    expect(polls).toHaveLength(0);
    doc.show("visible");
    await vi.advanceTimersByTimeAsync(2_000);
    expect(polls).toHaveLength(1);
    const open = last(polls);
    release();
    await vi.advanceTimersByTimeAsync(0);
    expect(open.signal?.aborted).toBe(true);
    expect(vi.getTimerCount()).toBe(0);
  });
});

describe("the download (X10)", () => {
  async function ready() {
    const s = setup();
    const release = s.store.hold();
    s.store.start(WINDOW);
    await s.last(s.starts).answer(accepted);
    await vi.advanceTimersByTimeAsync(2_000);
    await s.last(s.polls).answer(ok(job({ status: "succeeded", result: exportResult() })));
    return { ...s, release };
  }
  const file: ExportFile = {
    blob: new Blob(["{}\n"]),
    fileName: `${JOB_ID}.ndjson.gz`,
    contentType: "application/gzip",
  };

  it("test_download_saves_the_served_file_once", async () => {
    const { store, downloads, saved, last, release } = await ready();
    expect(store.download()).toBe(true);
    expect(store.download()).toBe(false); // busy
    await last(downloads).answer(ok(file));
    expect(saved).toEqual([file]);
    release();
  });

  it("test_download_step_up_goes_through_the_gate_and_its_resend_saves", async () => {
    const { store, downloads, saved, last, release } = await ready();
    store.download();
    await last(downloads).answer(stepUp);
    expect(store.getState().phase).toMatchObject({ download: { kind: "step_up" } });
    const reply = new Response("{}\n", {
      status: 200,
      headers: { "Content-Disposition": 'attachment; filename="audit.ndjson"' },
    });
    await store.resentDownload(reply);
    expect(saved.map((f) => f.fileName)).toEqual(["audit.ndjson"]);
    expect(downloads).toHaveLength(1);
    release();
  });

  it("test_download_resend_whose_body_breaks_off_fails_and_can_be_tried_again", async () => {
    // C-1135P2-01: the gate's re-send settles; Download is never left "downloading"
    const { store, downloads, last, release } = await ready();
    store.download();
    await last(downloads).answer(stepUp);
    const broken = new Response(
      new ReadableStream<Uint8Array>({
        pull(controller) {
          controller.error(new TypeError("network error"));
        },
      }),
      { status: 200, headers: { "Content-Type": "application/gzip" } },
    );
    await expect(store.resentDownload(broken)).resolves.toBeUndefined();
    expect(store.getState().phase).toMatchObject({ download: { kind: "failed" } });
    expect(store.download()).toBe(true);
    release();
  });

  it("test_download_403_forbidden_under_view_as_is_not_sent_never_withdrawn", async () => {
    const s = setup();
    const release = s.store.hold(() => true);
    s.store.start(WINDOW);
    await s.last(s.starts).answer(accepted);
    await vi.advanceTimersByTimeAsync(2_000);
    await s.last(s.polls).answer(ok(job({ status: "succeeded", result: exportResult() })));
    s.store.download();
    await s.last(s.downloads).answer(refused(403, "forbidden", { refId: REF }));
    expect(s.store.getState()).toMatchObject({
      denied: null,
      phase: { download: { kind: "not_sent" } },
    });
    release();
  });

  it.each([
    [refused(404, "not_found"), { kind: "lost" }],
    [refused(410, "gone"), { kind: "expired", at: "2026-09-15T10:39:10Z" }],
  ] as const)("test_download_answer_%#_replaces_the_ready_line", async (answer, phase) => {
    const { store, downloads, last, release } = await ready();
    store.download();
    await last(downloads).answer(answer as AuditAnswer<ExportFile>);
    expect(store.getState().phase).toEqual(phase);
    release();
  });

  it("test_download_429_is_limited_until_retry_after_and_503_lets_it_try_again", async () => {
    const { store, downloads, last, release } = await ready();
    store.download();
    await last(downloads).answer(refused(429, "rate_limited", { retryAfterS: 600 }));
    expect(store.getState().phase).toMatchObject({
      download: { kind: "limited", until: T0 + 2_000 + 600_000 },
    });
    expect(store.download()).toBe(false);
    await vi.advanceTimersByTimeAsync(600_000);
    expect(store.download()).toBe(true);
    await last(downloads).answer(refused(503, "store_unavailable"));
    expect(store.getState().phase).toMatchObject({ download: { kind: "failed" } });
    expect(store.download()).toBe(true);
    release();
  });
});
