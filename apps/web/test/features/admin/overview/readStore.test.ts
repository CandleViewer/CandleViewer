/**
 * E42-S01 (#1022) BQ-5 and BQ-6: the admin reads' shared store. One entry per read, one request in
 * flight per read, nothing re-read under 30 s on a hold, one chained 30 s re-read of the overview
 * while the document is visible and something holds it (the ruling on BQ-5 for #5330: every other
 * read once per entry and on Retry), the last good body kept through a failure, and everything
 * stopped and dropped (timer, listener, requests, answers) when the last view lets go.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ReadOutcome } from "../../../../src/features/admin/overview/adminReads";
import {
  createAdminReadStore,
  CYCLE_READS,
  REREAD_MS,
  sameJson,
  type AdminReadDeps,
  type ReadBodies,
  type ReadId,
} from "../../../../src/features/admin/overview/readStore";

/** A document whose visibility the test sets, counting its listeners. */
class FakeDocument extends EventTarget {
  visibilityState: DocumentVisibilityState = "visible";
  listeners = 0;
  override addEventListener(...args: Parameters<EventTarget["addEventListener"]>): void {
    this.listeners += 1;
    super.addEventListener(...args);
  }
  override removeEventListener(...args: Parameters<EventTarget["removeEventListener"]>): void {
    this.listeners -= 1;
    super.removeEventListener(...args);
  }
  show(state: DocumentVisibilityState): void {
    this.visibilityState = state;
    this.dispatchEvent(new Event("visibilitychange"));
  }
}

interface Call {
  readonly id: ReadId;
  readonly signal: AbortSignal;
  readonly answer: (outcome: ReadOutcome<unknown>) => void;
}

/** A store on fake timers whose reads the test answers one by one. */
function setup() {
  vi.useFakeTimers();
  vi.setSystemTime(Date.UTC(2026, 9, 22, 14, 2, 11));
  const doc = new FakeDocument();
  const calls: Call[] = [];
  const deps: AdminReadDeps = {
    now: () => Date.now(),
    setTimeout: (run, ms) => setTimeout(run, ms),
    clearTimeout: (handle) => clearTimeout(handle as ReturnType<typeof setTimeout>),
    document: doc as unknown as Document,
    read: <K extends ReadId>(id: K, signal: AbortSignal) =>
      new Promise<ReadOutcome<ReadBodies[K]>>((resolve) => {
        calls.push({ id, signal, answer: (o) => resolve(o as ReadOutcome<ReadBodies[K]>) });
      }),
  };
  const store = createAdminReadStore(deps);
  const ids = (): ReadId[] => calls.map((c) => c.id);
  /** Answers the newest open call to `id` and lets its promise settle. */
  const answer = async (id: ReadId, outcome: ReadOutcome<unknown>): Promise<void> => {
    const call = [...calls].reverse().find((c) => c.id === id);
    call?.answer(outcome);
    await vi.advanceTimersByTimeAsync(0);
  };
  return { store, doc, calls, ids, answer };
}

const OVERVIEW = { users: { status: "ok", total: 4, without_mfa: 0 } };
const ok = (body: unknown = OVERVIEW): ReadOutcome<unknown> => ({ kind: "ok", body });
const settle = async (): Promise<void> => {
  await vi.advanceTimersByTimeAsync(0);
};

afterEach(() => {
  vi.useRealTimers();
});

describe("the admin read store", () => {
  it("reads what is held, once: a second hold of a read in flight or fresh asks nothing", async () => {
    const { store, ids, answer } = setup();
    const release = store.hold(["overview", "capacity"]);
    expect(ids()).toEqual(["overview", "capacity"]);
    expect(store.getState().overview).toMatchObject({ phase: "idle", inFlight: true });
    const again = store.hold(["overview"]);
    expect(ids()).toEqual(["overview", "capacity"]); // in flight: one request
    await answer("overview", ok());
    const third = store.hold(["overview"]);
    expect(ids()).toEqual(["overview", "capacity"]); // answered under 30 s ago: not repeated
    expect(store.getState().overview).toMatchObject({ phase: "ok", data: OVERVIEW });
    [release, again, third].forEach((r) => r());
  });

  it("re-reads the overview every 30 s, chained, and nothing once released", async () => {
    const { store, ids, answer } = setup();
    const release = store.hold(["overview"]);
    await answer("overview", ok());
    await vi.advanceTimersByTimeAsync(REREAD_MS - 1);
    expect(ids()).toEqual(["overview"]);
    await vi.advanceTimersByTimeAsync(1);
    expect(ids()).toEqual(["overview", "overview"]);
    await answer("overview", ok());
    await vi.advanceTimersByTimeAsync(REREAD_MS);
    expect(ids()).toHaveLength(3);
    release();
    await settle();
    expect(vi.getTimerCount()).toBe(0);
    await vi.advanceTimersByTimeAsync(REREAD_MS * 3);
    expect(ids()).toHaveLength(3);
  });

  // The orchestrator's ruling on BQ-5 for #5330 (S-5330-02, C-5330-03): the cycle repeats the
  // overview alone, so it writes one `admin.area_entered` row per 30 s; the rest wait for an entry.
  // The lines fed by `flags`, `invites` and `capacity` print their own read time instead
  // (C-5330-11): none of them joins the cycle, or each `/admin/*` one adds a row per tick (#5331).
  it("re-reads only the overview on the cycle; every other read once per entry and on Retry", async () => {
    const { store, ids, answer } = setup();
    const entry = [
      "overview",
      "capacity",
      "health",
      "flags",
      "audit",
      "backups",
      "invites",
    ] as const;
    expect(CYCLE_READS).toEqual(["overview"]);
    const release = store.hold(entry);
    for (const id of entry) await answer(id, ok({}));
    for (let tick = 0; tick < 3; tick += 1) {
      await vi.advanceTimersByTimeAsync(REREAD_MS);
      await answer("overview", ok({}));
    }
    expect(ids()).toEqual([...entry, "overview", "overview", "overview"]);
    store.retry(["flags"], "trading");
    expect(ids().at(-1)).toBe("flags");
    release();
  });

  it("holds a tick off a read a Retry answered under half a period ago (C-5330-08)", async () => {
    const { store, ids, answer } = setup();
    const release = store.hold(["overview"]);
    await answer("overview", ok());
    await vi.advanceTimersByTimeAsync(20_000);
    store.retry(["overview"], "users");
    await answer("overview", ok());
    expect(ids()).toHaveLength(2);
    await vi.advanceTimersByTimeAsync(10_000); // the tick at 30 s finds an answer 10 s old
    expect(ids()).toHaveLength(2);
    await vi.advanceTimersByTimeAsync(REREAD_MS); // the next one, at 60 s, reads
    expect(ids()).toHaveLength(3);
    release();
  });

  it("pauses while the document is hidden and reads what is due when it shows again", async () => {
    const { store, doc, ids, answer } = setup();
    const release = store.hold(["overview"]);
    await answer("overview", ok());
    doc.show("hidden");
    expect(vi.getTimerCount()).toBe(0);
    await vi.advanceTimersByTimeAsync(REREAD_MS * 4);
    expect(ids()).toEqual(["overview"]);
    doc.show("visible");
    expect(ids()).toEqual(["overview", "overview"]); // older than 30 s: read at once
    expect(vi.getTimerCount()).toBe(1); // and the chain starts again
    release();
  });

  it("reads on showing again only the overview and what was never answered", async () => {
    const { store, doc, ids, answer } = setup();
    const release = store.hold(["overview", "flags"]);
    await answer("overview", ok());
    await answer("flags", ok({ resolution: "stored", items: [] }));
    doc.show("hidden");
    const late = store.hold(["health"]); // held while hidden: asked for nothing yet
    await vi.advanceTimersByTimeAsync(REREAD_MS * 4);
    doc.show("visible");
    expect(ids()).toEqual(["overview", "flags", "overview", "health"]);
    [release, late].forEach((r) => r());
  });

  it("asks nothing while hidden, even for a first hold, until the document shows", async () => {
    const { store, doc, ids } = setup();
    doc.visibilityState = "hidden";
    const release = store.hold(["health"]);
    expect(ids()).toEqual([]);
    doc.show("visible");
    expect(ids()).toEqual(["health"]);
    release();
  });

  it("keeps the last good body through a failure: stale since the first failure", async () => {
    const { store, answer } = setup();
    const release = store.hold(["overview"]);
    await answer("overview", ok());
    const okAt = store.getState().overview.okAt;
    const failedAt = Date.now() + REREAD_MS;
    await vi.advanceTimersByTimeAsync(REREAD_MS);
    await answer("overview", { kind: "failed", reason: "status", status: 503 });
    expect(store.getState().overview).toMatchObject({
      phase: "failed",
      data: OVERVIEW,
      okAt,
      failedAt,
      reason: "status",
      status: 503,
    });
    await vi.advanceTimersByTimeAsync(REREAD_MS);
    await answer("overview", { kind: "failed", reason: "timeout" });
    expect(store.getState().overview).toMatchObject({ failedAt, reason: "timeout" });
    await vi.advanceTimersByTimeAsync(REREAD_MS);
    await answer("overview", ok());
    expect(store.getState().overview.failedAt).toBeUndefined();
    release();
  });

  it("keeps each slice's last ok time, so a slice that errs reads its last good", async () => {
    const { store, answer } = setup();
    const release = store.hold(["overview"]);
    const at = "2026-10-22T14:01:40Z";
    await answer("overview", ok({ users: { status: "ok", generated_at: at } }));
    await vi.advanceTimersByTimeAsync(REREAD_MS);
    await answer("overview", ok({ users: { status: "error", detail: "timed out after 300 ms" } }));
    expect(store.getState().overview.sliceGoodAt).toEqual({ users: Date.parse(at) });
    release();
  });

  it("keeps the same body when a re-read changed nothing, so its readers stay still", async () => {
    const { store, answer } = setup();
    const release = store.hold(["overview"]);
    await answer("overview", ok({ ...OVERVIEW }));
    const first = store.getState().overview.data;
    await vi.advanceTimersByTimeAsync(REREAD_MS);
    await answer("overview", ok(JSON.parse(JSON.stringify(OVERVIEW))));
    expect(store.getState().overview.data).toBe(first);
    expect(sameJson({ a: 1 }, { a: 1 })).toBe(true);
    release();
  });

  it("stops at the last release: aborts the reads in flight, drops the timer and the listener", async () => {
    const { store, doc, calls } = setup();
    const release = store.hold(["overview", "health"]);
    expect(doc.listeners).toBe(1);
    release();
    release(); // a second call changes nothing
    await settle();
    expect(calls.map((c) => c.signal.aborted)).toEqual([true, true]);
    expect(vi.getTimerCount()).toBe(0);
    expect(doc.listeners).toBe(0);
    expect(store.getState().overview).toMatchObject({ phase: "idle", inFlight: false });
    // A read that answers after it was stopped changes nothing.
    calls[0]?.answer(ok());
    await settle();
    expect(store.getState().overview.phase).toBe("idle");
  });

  // C-5330-02: leaving the area keeps nothing it read, so a later visit never paints an old visit's
  // answers as fresh, and its render measure is real.
  it("drops every answer at the last release, so the next visit starts cold", async () => {
    const { store, ids, answer } = setup();
    const release = store.hold(["overview", "health"]);
    await answer("overview", ok());
    await answer("health", { kind: "failed", reason: "network" });
    release();
    await settle();
    for (const id of ["overview", "health"] as const) {
      expect(store.getState()[id], id).toEqual({ phase: "idle", inFlight: false });
    }
    const again = store.hold(["overview", "health"]);
    expect(ids()).toEqual(["overview", "health", "overview", "health"]);
    again();
  });

  it("keeps going when a route change lets go and holds again in one go", async () => {
    const { store, calls } = setup();
    const release = store.hold(["overview"]);
    release();
    const again = store.hold(["overview"]);
    await settle();
    expect(calls).toHaveLength(1);
    expect(calls[0]?.signal.aborted).toBe(false);
    again();
  });

  it("reads again at once after an aborted read: it never answered", async () => {
    const { store, ids } = setup();
    store.hold(["overview"])();
    await settle();
    const again = store.hold(["overview"]);
    expect(ids()).toEqual(["overview", "overview"]);
    again();
  });

  it("retries now for a tile: only that tile's read is marked, until it answers", async () => {
    const { store, ids, answer } = setup();
    const release = store.hold(["overview"]);
    await answer("overview", { kind: "failed", reason: "network" });
    store.retry(["overview"], "users");
    expect(ids()).toEqual(["overview", "overview"]);
    expect(store.getState().overview).toMatchObject({ inFlight: true, retriedBy: "users" });
    store.retry(["overview"], "users"); // in flight: no second request
    expect(ids()).toHaveLength(2);
    await answer("overview", ok());
    expect(store.getState().overview.retriedBy).toBeUndefined();
    release();
  });

  it("asks nothing more for a read the server refused: the area is withdrawn", async () => {
    const { store, ids, answer } = setup();
    const release = store.hold(["overview"]);
    await answer("overview", { kind: "denied", refId: "urn:cv:req:1" });
    expect(store.getState().overview).toMatchObject({ phase: "denied", refId: "urn:cv:req:1" });
    store.retry(["overview"], "users");
    await vi.advanceTimersByTimeAsync(REREAD_MS);
    expect(ids()).toEqual(["overview"]);
    release();
  });

  // S-5330-03: a refusal withdraws the whole area: every other read stops, its answer is dropped,
  // and nothing is asked again for any read; the refusal itself outlives the last release.
  it("drops every other answer on a refusal, asks nothing more, and stays withdrawn", async () => {
    const { store, calls, ids, answer } = setup();
    const release = store.hold(["overview", "health", "audit"]);
    await answer("overview", ok());
    await answer("audit", { kind: "denied", refId: "urn:cv:req:2" });
    expect(calls.find((c) => c.id === "health")?.signal.aborted).toBe(true);
    expect(store.getState().overview).toEqual({ phase: "idle", inFlight: false });
    expect(store.getState().health).toEqual({ phase: "idle", inFlight: false });
    store.retry(["overview", "health"], "users");
    await vi.advanceTimersByTimeAsync(REREAD_MS * 2);
    expect(ids()).toEqual(["overview", "health", "audit"]);
    release();
    await settle();
    expect(store.getState().audit).toMatchObject({ phase: "denied", refId: "urn:cv:req:2" });
    const again = store.hold(["overview"]);
    expect(ids()).toHaveLength(3);
    again();
  });

  it("notifies on every answer and lets a listener go", async () => {
    const { store, answer } = setup();
    const listener = vi.fn();
    const unsubscribe = store.subscribe(listener);
    const release = store.hold(["flags"]);
    await answer("flags", { kind: "not_built" });
    expect(listener).toHaveBeenCalled();
    expect(store.getState().flags.phase).toBe("not_built");
    unsubscribe();
    listener.mockClear();
    store.reset();
    expect(listener).not.toHaveBeenCalled();
    expect(store.getState().flags.phase).toBe("idle");
    release();
  });
});
