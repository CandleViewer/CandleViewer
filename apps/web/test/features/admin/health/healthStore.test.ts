/**
 * E42-S06 (#1084) part 1: SCR-143's store (the plan's §1.2, §5): D5's reads on the hold and Re-read
 * only, one per id, the report kept stale after a failure (D6), a `403` withdraws once (BQ-10), the
 * release drops everything [BQ-20], frames fold into words and the transport's drop is stamped.
 */
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import {
  createHealthStore,
  type Bodies,
  type HealthStore,
  type ReadId,
} from "../../../../src/features/admin/health/healthStore";
import type { OpsAnswer } from "../../../../src/features/admin/ops/opsReads";
import {
  applySystemUpdate,
  getShellState,
  resetShellState,
  setShellState,
  subscribeShellState,
} from "../../../../src/shell/bootstrap/store";

const T = Date.parse("2026-10-22T14:02:11Z");
const REPORT = { overall: "healthy", components: [{ name: "oms", state: "healthy" }] } as const;
const PAGE = { items: [], meta: { has_more: false, count: 0, next_cursor: null } };

let calls: { id: ReadId; signal: AbortSignal; answer: (answer: OpsAnswer<unknown>) => void }[];
let deny: Mock<(refId: string | undefined) => void>;
let store: HealthStore;

const ok = (body: unknown) => ({ kind: "ok", body, at: Date.now() }) as const;
/** Answers every read in flight for `id` (all four when omitted) and lets them settle. */
async function answer(reply: (id: ReadId) => OpsAnswer<unknown>, only?: ReadId): Promise<void> {
  for (const call of calls.splice(0)) {
    if (only === undefined || call.id === only) call.answer(reply(call.id));
    else calls.push(call);
  }
  await vi.advanceTimersByTimeAsync(0);
}
const bodies = (id: ReadId) => ok(id === "health" ? REPORT : id === "protection" ? {} : PAGE);

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(T);
  resetShellState();
  calls = [];
  deny = vi.fn<(refId: string | undefined) => void>();
  store = createHealthStore({
    now: () => Date.now(),
    read: <K extends ReadId>(id: K, signal: AbortSignal) =>
      new Promise<OpsAnswer<Bodies[K]>>((resolve) => {
        // The test answers with untyped bodies: the store keeps what it is given.
        calls.push({ id, signal, answer: resolve as (answer: OpsAnswer<unknown>) => void });
      }),
    shell: { get: getShellState, subscribe: subscribeShellState },
    deny,
  });
});

afterEach(() => {
  store.reset();
  resetShellState();
  vi.useRealTimers();
});

describe("SCR-143's store", () => {
  it("test_store_reads_on_the_hold_and_never_on_a_timer", async () => {
    store.hold();
    expect(calls.map((c) => c.id)).toEqual(["health", "open", "acknowledged", "protection"]);
    await answer(bodies);
    await vi.advanceTimersByTimeAsync(60_000);
    expect(calls).toEqual([]);
    expect(store.getState().reads.health).toMatchObject({ phase: "ok", okAt: T, inFlight: false });
  });

  it("test_store_reread_asks_each_read_once_more_never_twice_at_a_time", async () => {
    store.hold();
    store.reread();
    expect(calls).toHaveLength(4);
    await answer(bodies);
    store.reread();
    store.retry("oms");
    expect(calls.map((c) => c.id)).toEqual(["health", "open", "acknowledged", "protection"]);
    expect(store.getState().reads.health).toMatchObject({ inFlight: true, retriedBy: "oms" });
  });

  it("test_store_a_failed_reread_keeps_the_report_stale_since_its_first_failure", async () => {
    store.hold();
    await answer(bodies);
    vi.setSystemTime(T + 5_000);
    store.retry("report");
    await answer(() => ({ kind: "failed", reason: "timeout" }));
    vi.setSystemTime(T + 9_000);
    store.reread();
    await answer(() => ({
      kind: "refused",
      status: 503,
      code: "store_unavailable",
      denied: false,
    }));
    expect(store.getState().reads.health).toEqual({
      phase: "failed",
      inFlight: false,
      data: REPORT,
      okAt: T,
      failedAt: T + 5_000,
      failure: { status: 503, code: "store_unavailable" },
      answers: 3,
    });
  });

  it("test_store_a_403_withdraws_once_drops_every_answer_and_asks_nothing_more", async () => {
    store.hold();
    const signals = calls.map((c) => c.signal);
    await answer(() => ({ kind: "refused", status: 403, code: "forbidden", denied: true }), "open");
    expect(deny).toHaveBeenCalledTimes(1);
    expect(deny).toHaveBeenCalledWith(undefined);
    expect(signals.map((s) => s.aborted)).toEqual([true, false, true, true]);
    store.reread();
    store.hold();
    expect(calls).toHaveLength(3); // the aborted three, never answered; none new
    expect(store.getState()).toMatchObject({ denied: { refId: undefined } });
    expect(store.getState().reads.health.phase).toBe("idle");
  });

  it("test_store_the_last_release_aborts_and_drops_everything", async () => {
    const release = store.hold();
    await answer(bodies, "health");
    release();
    await vi.advanceTimersByTimeAsync(0);
    expect(calls.every((c) => c.signal.aborted)).toBe(true);
    expect(store.getState().reads.health).toEqual({ phase: "idle", inFlight: false });
    expect(store.getState().words.size).toBe(0);
  });

  it("test_store_a_release_after_a_reset_leaves_the_next_hold_reading", async () => {
    const release = store.hold();
    store.reset();
    release();
    await vi.advanceTimersByTimeAsync(0);
    calls = [];
    store.hold();
    expect(calls).toHaveLength(4);
  });

  it("test_store_folds_frames_from_the_held_one_and_stamps_the_drop", async () => {
    setShellState({ everLive: true, connection: { kind: "live" } });
    applySystemUpdate({
      kind: "health",
      health: "healthy",
      components: [{ name: "oms", state: "healthy" }],
    });
    store.hold();
    expect(store.getState()).toMatchObject({ framesSeenAt: undefined });
    vi.setSystemTime(T + 1_000);
    applySystemUpdate({
      kind: "health",
      health: "degraded",
      components: [{ name: "oms", state: "degraded" }],
    });
    expect(store.getState().overall).toEqual({ word: "degraded", at: T + 1_000 });
    const words = store.getState().words;
    expect(words.get("oms")).toMatchObject({ state: "degraded" });
    vi.setSystemTime(T + 1_500);
    applySystemUpdate({ kind: "health", components: [{ name: "oms", state: "degraded" }] });
    // The same words: one number moves, no record does.
    expect(store.getState()).toMatchObject({ words, framesSeenAt: T + 1_500 });
    vi.setSystemTime(T + 2_000);
    setShellState({ connection: { kind: "reconnecting", attempt: 1, nextAttemptAtMs: 0 } });
    vi.setSystemTime(T + 3_000);
    setShellState({ connection: { kind: "connecting" } });
    expect(store.getState().droppedAt).toBe(T + 2_000);
    setShellState({ connection: { kind: "live" } });
    expect(store.getState().droppedAt).toBeUndefined();
  });
});
