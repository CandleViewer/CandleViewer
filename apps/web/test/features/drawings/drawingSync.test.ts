import { afterEach, describe, expect, it, vi } from "vitest";
import { createDrawingStore } from "../../../src/features/drawings/store/drawingStore.js";
import {
  BACKOFF_CAP_MS,
  backoffMs,
  createDrawingSync,
  fold,
  type Scheduler,
} from "../../../src/features/drawings/store/drawingSync.js";
import type {
  BatchOutcome,
  DrawingsApi,
} from "../../../src/features/drawings/store/drawingsApi.js";
import type {
  Drawing,
  DrawingBatchOp,
  Notice,
} from "../../../src/features/drawings/store/types.js";
import { counter, input, row } from "./fixtures.js";

const flush = async (): Promise<void> => {
  for (let i = 0; i < 30; i += 1) await Promise.resolve();
};

function fakeClock(): Scheduler & { advance: (ms: number) => Promise<void>; size: () => number } {
  let now = 0;
  let seq = 0;
  const timers = new Map<number, { at: number; run: () => void }>();
  return {
    now: () => now,
    setTimeout: (run, ms) => {
      seq += 1;
      timers.set(seq, { at: now + ms, run });
      return seq;
    },
    clearTimeout: (handle) => {
      timers.delete(handle as number);
    },
    size: () => timers.size,
    advance: async (ms) => {
      const end = now + ms;
      for (;;) {
        const due = [...timers].filter(([, t]) => t.at <= end).sort((a, b) => a[1].at - b[1].at)[0];
        if (due === undefined) break;
        timers.delete(due[0]);
        now = due[1].at;
        due[1].run();
        await flush();
      }
      now = end;
      await flush();
    },
  };
}

interface Call {
  readonly body: string;
  readonly key: string;
  readonly ops: DrawingBatchOp[];
}

function fakeApi() {
  const calls: Call[] = [];
  const queue: (BatchOutcome | Promise<BatchOutcome>)[] = [];
  const state = {
    items: [] as Drawing[],
    listOk: true,
    lists: 0,
    listThrows: false,
    listHold: null as Promise<void> | null,
  };
  let tick = 0;
  const token = (): string => {
    tick += 1;
    return `2026-09-13T12:00:00.${String(tick).padStart(6, "0")}Z`;
  };
  const echo = (ops: DrawingBatchOp[]): BatchOutcome => ({
    kind: "ok",
    result: {
      created: ops.flatMap((o) => (o.op === "create" ? [row(o.id ?? "", o.drawing, token())] : [])),
      updated: ops.flatMap((o) => (o.op === "update" ? [row(o.id, o.drawing, token())] : [])),
      deleted: ops.flatMap((o) => (o.op === "delete" ? [o.id] : [])),
    },
  });
  const api: DrawingsApi = {
    batch: (body, key) => {
      const ops = (JSON.parse(body) as { operations: DrawingBatchOp[] }).operations;
      calls.push({ body, key, ops });
      return Promise.resolve(queue.shift() ?? echo(ops));
    },
    list: async () => {
      state.lists += 1;
      if (state.listHold !== null) await state.listHold;
      if (state.listThrows) throw new Error("list blew up");
      return state.listOk
        ? { ok: true as const, items: state.items }
        : { ok: false as const, status: 503 };
    },
  };
  return { api, calls, queue, state, echo };
}

function setup() {
  const clock = fakeClock();
  const fake = fakeApi();
  const store = createDrawingStore({ mintId: counter("h") });
  const notices: Notice[] = [];
  store.onNotice((n) => notices.push(n));
  const sync = createDrawingSync({
    store,
    api: fake.api,
    scheduler: clock,
    random: () => 0.5,
    newKey: counter("key"),
    mintId: counter("re"),
  });
  const status = (symbol = "BTCUSDT") => store.getSymbol(symbol).status;
  return { clock, ...fake, store, notices, sync, status };
}

const conflict = (rule: string, index: number | null): BatchOutcome => ({
  kind: "conflict",
  rule,
  index,
});

describe("drawing sync: coalescing and timing", () => {
  it("debounces 500 ms and sends one create; status pending -> saved", async () => {
    const t = setup();
    t.store.create(input());
    expect(t.status()).toEqual({ kind: "pending" });
    await t.clock.advance(499);
    expect(t.calls).toHaveLength(0);
    await t.clock.advance(1);
    expect(t.calls).toHaveLength(1);
    expect(t.calls[0]?.ops).toEqual([{ op: "create", id: "h-2", drawing: input() }]);
    expect(t.status()).toEqual({ kind: "saved" });
    expect(t.store.tokenOf("h-2")).not.toBeNull();
  });

  it("a continuous drag still sends after the 2 s maxWait", async () => {
    const t = setup();
    const a = t.store.create(input());
    for (let i = 1; i <= 6; i += 1) {
      await t.clock.advance(400);
      t.store.update("BTCUSDT", a, { z_index: i });
    }
    expect(t.calls).toHaveLength(1);
    expect(t.clock.now()).toBe(2400);
    expect(t.calls[0]?.ops[0]).toMatchObject({ op: "create", drawing: { z_index: 4 } });
  });

  it("create+update folds into one create; create+delete sends nothing", async () => {
    const t = setup();
    const a = t.store.create(input());
    t.store.update("BTCUSDT", a, { label: "x" });
    const b = t.store.create(input());
    t.store.remove("BTCUSDT", [b]);
    t.sync.flush();
    await t.clock.advance(0);
    expect(t.calls).toHaveLength(1);
    expect(t.calls[0]?.ops).toEqual([
      { op: "create", id: "h-2", drawing: input("BTCUSDT", { label: "x" }) },
    ]);
    expect(t.sync.pendingCount()).toBe(0);
  });

  it("keeps one request in flight and resolves if_match at send time", async () => {
    const t = setup();
    let release: (o: BatchOutcome) => void = () => undefined;
    t.queue.push(new Promise<BatchOutcome>((r) => (release = r)));
    const a = t.store.create(input());
    t.sync.flush();
    await flush();
    t.store.update("BTCUSDT", a, { locked: true });
    await t.clock.advance(5_000);
    t.sync.flush();
    expect(t.calls).toHaveLength(1);
    const token = "2026-09-13T12:00:00.000777Z";
    release({
      kind: "ok",
      result: { created: [row("h-2", input(), token)], updated: [], deleted: [] },
    });
    await flush();
    expect(t.calls).toHaveLength(2);
    expect(t.calls[1]?.ops).toEqual([
      { op: "update", id: "h-2", if_match: token, drawing: input("BTCUSDT", { locked: true }) },
    ]);
    expect(t.calls[1]?.body).toContain(`"if_match":"${token}"`);
  });

  it("chunks at 200 operations and sends the rest right after", async () => {
    const t = setup();
    for (let i = 0; i < 250; i += 1) t.store.create(input());
    t.sync.flush();
    await flush();
    expect(t.calls.map((c) => c.ops.length)).toEqual([200, 50]);
    expect(t.status()).toEqual({ kind: "saved" });
  });

  it("an update whose target was never confirmed is dropped at send", async () => {
    const t = setup();
    let release: (o: BatchOutcome) => void = () => undefined;
    t.queue.push(new Promise<BatchOutcome>((r) => (release = r)));
    const a = t.store.create(input());
    t.sync.flush();
    await flush();
    t.store.update("BTCUSDT", a, { label: "later" });
    release({ kind: "rejected", status: 403, code: "forbidden" });
    await flush();
    await t.clock.advance(600);
    expect(t.calls).toHaveLength(1);
    expect(t.sync.pendingCount()).toBe(0);
  });
});

describe("drawing sync: failures", () => {
  it("5xx re-sends the same body under the same key with backoff; new edits wait for the next batch", async () => {
    const t = setup();
    t.queue.push({ kind: "retryable", status: 503 }, { kind: "retryable", status: 0 });
    const a = t.store.create(input());
    t.sync.flush();
    await flush();
    expect(t.status()).toEqual({ kind: "unsaved", retryable: true });
    t.store.update("BTCUSDT", a, { label: "next" });
    await t.clock.advance(499);
    expect(t.calls).toHaveLength(1);
    await t.clock.advance(1);
    expect(t.calls).toHaveLength(2);
    await t.clock.advance(999);
    expect(t.calls).toHaveLength(2);
    await t.clock.advance(1);
    expect(t.calls).toHaveLength(4);
    expect(t.calls[1]).toMatchObject({ body: t.calls[0]?.body, key: "key-1" });
    expect(t.calls[2]).toMatchObject({ body: t.calls[0]?.body, key: "key-1" });
    expect(t.calls[3]?.key).toBe("key-2");
    expect(t.calls[3]?.ops[0]).toMatchObject({ op: "update", drawing: { label: "next" } });
    expect(t.status()).toEqual({ kind: "saved" });
  });

  it("429 waits Retry-After (or backs off when absent) and keeps the key", async () => {
    const t = setup();
    t.queue.push(
      { kind: "rate_limited", retryAfterS: 3 },
      { kind: "rate_limited", retryAfterS: null },
    );
    t.store.create(input());
    t.sync.flush();
    await flush();
    expect(t.status()).toEqual({ kind: "pending" });
    await t.clock.advance(2_999);
    expect(t.calls).toHaveLength(1);
    await t.clock.advance(1);
    expect(t.calls).toHaveLength(2);
    await t.clock.advance(500);
    expect(t.calls.map((c) => c.key)).toEqual(["key-1", "key-1", "key-1"]);
  });

  it("a 403 is never re-sent: unconfirmed creates go, server truth is re-read, status unsaved", async () => {
    const t = setup();
    t.state.items = [row("s1", input())];
    t.queue.push({ kind: "rejected", status: 403, code: "forbidden" });
    t.store.create(input());
    t.sync.flush();
    await flush();
    await t.clock.advance(60_000);
    expect(t.calls).toHaveLength(1);
    expect(t.state.lists).toBe(1);
    expect(t.store.selectPane("BTCUSDT", null).map((d) => d.id)).toEqual(["s1"]);
    expect(t.status()).toEqual({ kind: "unsaved", retryable: false });
    t.store.update("BTCUSDT", t.store.selectPane("BTCUSDT", null)[0]?.handle ?? ("" as never), {
      label: "again",
    });
    expect(t.status()).toEqual({ kind: "pending" });
  });

  it("a batch whose transport throws is re-sent like a 5xx: same key, after backoff", async () => {
    const t = setup();
    t.queue.push(Promise.reject(new Error("socket closed")));
    t.store.create(input());
    t.sync.flush();
    await flush();
    expect(t.status()).toEqual({ kind: "unsaved", retryable: true });
    await t.clock.advance(60_000);
    expect(t.calls).toHaveLength(2);
    expect(t.calls[1]?.key).toBe(t.calls[0]?.key);
    expect(t.status()).toEqual({ kind: "saved" });
  });

  it("a re-read that throws during reconciliation marks unsaved and the queue keeps going", async () => {
    const t = setup();
    t.state.listThrows = true;
    t.queue.push({ kind: "rejected", status: 403, code: "forbidden" });
    t.store.create(input());
    t.sync.flush();
    await flush();
    expect(t.status()).toEqual({ kind: "unsaved", retryable: false });
    t.state.listThrows = false;
    t.store.create(input());
    await t.clock.advance(500);
    expect(t.calls).toHaveLength(2);
    expect(t.status()).toEqual({ kind: "saved" });
  });

  it("backoff is full jitter with a floor and a 30 s cap", () => {
    expect(backoffMs(1, () => 0)).toBe(250);
    expect(backoffMs(1, () => 0.5)).toBe(500);
    expect(backoffMs(3, () => 0.5)).toBe(2_000);
    expect(backoffMs(20, () => 0.999_999)).toBeLessThan(BACKOFF_CAP_MS);
    expect(fold({ op: "update", id: "a", input: input() }, { op: "delete", id: "a" })).toEqual({
      op: "delete",
      id: "a",
    });
  });
});

describe("drawing sync: 409 reconciliation (atomic batch)", () => {
  async function confirmed(t: ReturnType<typeof setup>, n: number) {
    const handles = Array.from({ length: n }, () => t.store.create(input()));
    t.sync.flush();
    await flush();
    t.calls.length = 0;
    return handles;
  }

  it("version_conflict: the server version wins once, the rest is re-sent", async () => {
    const t = setup();
    const [a, b] = await confirmed(t, 2);
    if (a === undefined || b === undefined) throw new Error("setup");
    t.store.update("BTCUSDT", a, { label: "mine" });
    t.store.update("BTCUSDT", b, { label: "mine-b" });
    t.state.items = [row("h-2", input("BTCUSDT", { label: "theirs" })), row("h-4", input())];
    t.queue.push(conflict("version_conflict", 0));
    t.sync.flush();
    await flush();
    expect(t.notices).toEqual([{ kind: "changed_elsewhere", symbol: "BTCUSDT", ids: ["h-2"] }]);
    const recA = t.store.getSymbol("BTCUSDT").doc.drawings.get(a);
    expect(recA).toMatchObject({ tag: "conflict", input: { label: "theirs" } });
    await t.clock.advance(500);
    expect(t.calls).toHaveLength(2);
    expect(t.calls[1]?.ops).toEqual([expect.objectContaining({ op: "update", id: "h-4" })]);
    expect(t.status()).toEqual({ kind: "conflict" });
    // Undo stays usable: re-applying the local version is one undoable command.
    t.store.undo("BTCUSDT");
    expect(t.status()).toEqual({ kind: "pending" });
  });

  it("version_conflict against our own replayed write is confirmed silently", async () => {
    const t = setup();
    const [a] = await confirmed(t, 1);
    if (a === undefined) throw new Error("setup");
    t.store.update("BTCUSDT", a, { label: "mine" });
    t.state.items = [
      row("h-2", input("BTCUSDT", { label: "mine" }), "2026-09-13T12:00:09.000001Z"),
    ];
    t.queue.push(conflict("version_conflict", 0));
    t.sync.flush();
    await flush();
    await t.clock.advance(1_000);
    expect(t.notices).toEqual([]);
    expect(t.calls).toHaveLength(1);
    expect(t.store.tokenOf("h-2")).toBe("2026-09-13T12:00:09.000001Z");
    expect(t.status()).toEqual({ kind: "saved" });
  });

  it("version_conflict whose row is gone removes it; an already-applied delete is confirmed", async () => {
    const t = setup();
    const [a, b] = await confirmed(t, 2);
    if (a === undefined || b === undefined) throw new Error("setup");
    t.store.update("BTCUSDT", a, { label: "x" });
    t.store.remove("BTCUSDT", [b]);
    t.state.items = [];
    t.queue.push(conflict("version_conflict", 0));
    t.sync.flush();
    await flush();
    expect(t.notices).toEqual([{ kind: "removed_elsewhere", symbol: "BTCUSDT", ids: ["h-2"] }]);
    expect(t.store.selectPane("BTCUSDT", null)).toEqual([]);
    expect(t.store.tokenOf("h-4")).toBeNull();
    expect(t.sync.pendingCount()).toBe(0);
  });

  it("a failed re-read puts the whole batch back and retries after backoff", async () => {
    const t = setup();
    const [a] = await confirmed(t, 1);
    if (a === undefined) throw new Error("setup");
    t.store.update("BTCUSDT", a, { label: "x" });
    t.state.listOk = false;
    t.queue.push(conflict("version_conflict", 0));
    t.sync.flush();
    await flush();
    expect(t.sync.pendingCount()).toBe(1);
    t.state.listOk = true;
    await t.clock.advance(500);
    expect(t.calls).toHaveLength(2);
  });

  it("a 409 whose re-read keeps failing escalates the backoff instead of resetting it", async () => {
    const t = setup();
    const [a] = await confirmed(t, 1);
    if (a === undefined) throw new Error("setup");
    t.store.update("BTCUSDT", a, { label: "x" });
    t.state.listOk = false;
    for (let i = 0; i < 4; i += 1) t.queue.push(conflict("version_conflict", 0));
    t.sync.flush();
    await flush();
    expect(t.calls).toHaveLength(1);
    // random = 0.5: 500 ms, then 1 s, then 2 s (full jitter of 1 s, 2 s, 4 s).
    for (const [wait, n] of [
      [500, 2],
      [1_000, 3],
      [2_000, 4],
    ] as const) {
      await t.clock.advance(wait - 1);
      expect(t.calls).toHaveLength(n - 1);
      await t.clock.advance(1);
      expect(t.calls).toHaveLength(n);
    }
    expect(t.state.lists).toBe(4);
  });

  it("target_unavailable removes the object and tells once; for a delete it is silent", async () => {
    const t = setup();
    const [a, b] = await confirmed(t, 2);
    if (a === undefined || b === undefined) throw new Error("setup");
    t.store.update("BTCUSDT", a, { label: "x" });
    t.store.remove("BTCUSDT", [b]);
    t.queue.push(conflict("target_unavailable", 1), conflict("target_unavailable", 0));
    t.sync.flush();
    await flush();
    expect(t.notices).toEqual([]);
    await t.clock.advance(500);
    expect(t.notices).toEqual([{ kind: "removed_elsewhere", symbol: "BTCUSDT", ids: ["h-2"] }]);
    expect(t.store.selectPane("BTCUSDT", null)).toEqual([]);
  });

  it("id_unavailable: our own lost create is confirmed (and updated if it differs)", async () => {
    const t = setup();
    const a = t.store.create(input("BTCUSDT", { label: "mine" }));
    t.state.items = [row("h-2", input())];
    t.queue.push(conflict("id_unavailable", 0));
    t.sync.flush();
    await flush();
    await t.clock.advance(500);
    expect(t.calls[1]?.ops).toEqual([
      expect.objectContaining({
        op: "update",
        id: "h-2",
        drawing: input("BTCUSDT", { label: "mine" }),
      }),
    ]);
    expect(t.store.getSymbol("BTCUSDT").doc.drawings.get(a)?.id).toBe("h-2");
  });

  it("id_unavailable with no such row re-mints the id and folds later edits in", async () => {
    const t = setup();
    let release: (o: BatchOutcome) => void = () => undefined;
    t.queue.push(new Promise<BatchOutcome>((r) => (release = r)));
    const a = t.store.create(input());
    t.sync.flush();
    await flush();
    t.store.update("BTCUSDT", a, { label: "later" });
    t.state.items = [];
    release(conflict("id_unavailable", 0));
    await flush();
    await t.clock.advance(500);
    expect(t.calls[1]?.ops).toEqual([
      { op: "create", id: "re-1", drawing: input("BTCUSDT", { label: "later" }) },
    ]);
    expect(t.store.getSymbol("BTCUSDT").doc.drawings.get(a)?.id).toBe("re-1");
  });

  it("no batch starts while a 409 re-read is pending; edits made meanwhile follow the re-mint", async () => {
    const t = setup();
    let release = (): void => undefined;
    t.state.listHold = new Promise<void>((resolve) => {
      release = resolve;
    });
    t.queue.push(conflict("id_unavailable", 0));
    const handle = t.store.create(input());
    t.sync.flush();
    await flush();
    const lost = t.calls[0]?.ops[0];
    expect(lost).toMatchObject({ op: "create" });
    t.store.update("BTCUSDT", handle, { label: "while reconciling" });
    await t.clock.advance(5_000);
    t.sync.flush();
    await flush();
    expect(t.calls).toHaveLength(1);
    release();
    await flush();
    await t.clock.advance(5_000);
    expect(t.calls).toHaveLength(2);
    expect(t.calls[1]?.ops).toEqual([
      {
        op: "create",
        id: "re-1",
        drawing: expect.objectContaining({ label: "while reconciling" }),
      },
    ]);
    expect(t.status()).toEqual({ kind: "saved" });
  });

  it("quota: optimistic creates are reverted, other operations go again", async () => {
    const t = setup();
    const [a] = await confirmed(t, 1);
    if (a === undefined) throw new Error("setup");
    t.store.update("BTCUSDT", a, { label: "x" });
    t.store.create(input());
    t.queue.push(conflict("drawings_quota_exceeded", null));
    t.sync.flush();
    await flush();
    expect(t.notices).toEqual([{ kind: "quota_exceeded", symbol: "BTCUSDT", ids: ["h-4"] }]);
    expect(t.store.selectPane("BTCUSDT", null).map((d) => d.id)).toEqual(["h-2"]);
    await t.clock.advance(500);
    expect(t.calls[1]?.ops).toEqual([expect.objectContaining({ op: "update", id: "h-2" })]);
    expect(t.status()).toEqual({ kind: "unsaved", retryable: false });
  });

  it("quota tells once per episode, naming every reverted create", async () => {
    const t = setup();
    t.store.create(input());
    t.store.create(input());
    t.queue.push(conflict("drawings_quota_exceeded", null));
    t.sync.flush();
    await flush();
    expect(t.notices).toEqual([{ kind: "quota_exceeded", symbol: "BTCUSDT", ids: ["h-2", "h-4"] }]);
  });

  it("version_conflict on a delete adopts the server row under its handle; undo adds no duplicate", async () => {
    const t = setup();
    const [a] = await confirmed(t, 1);
    if (a === undefined) throw new Error("setup");
    t.store.remove("BTCUSDT", [a]);
    t.state.items = [
      row("h-2", input("BTCUSDT", { label: "theirs" }), "2026-09-13T12:00:59.000001Z"),
    ];
    t.queue.push(conflict("version_conflict", 0));
    t.sync.flush();
    await flush();
    expect(t.notices).toEqual([{ kind: "changed_elsewhere", symbol: "BTCUSDT", ids: ["h-2"] }]);
    t.store.undo("BTCUSDT");
    await t.clock.advance(1_000);
    expect(t.store.selectPane("BTCUSDT", null).map((d) => d.id)).toEqual(["h-2"]);
    expect(t.calls.flatMap((c) => c.ops).filter((o) => o.op === "create")).toEqual([]);
  });

  it("an unknown rule or no operation index re-reads server truth", async () => {
    const t = setup();
    t.state.items = [row("s1", input())];
    t.queue.push(conflict("idempotency_key_reuse", null));
    t.store.create(input());
    t.sync.flush();
    await flush();
    expect(t.state.lists).toBe(1);
    expect(t.store.selectPane("BTCUSDT", null).map((d) => d.id)).toContain("s1");
  });
});

describe("drawing sync: load and teardown", () => {
  it("concurrent loads share one request; a failed load reports false", async () => {
    const t = setup();
    t.state.items = [row("s1", input())];
    const [x, y] = await Promise.all([t.sync.load("BTCUSDT"), t.sync.load("BTCUSDT")]);
    expect([x, y, t.state.lists]).toEqual([true, true, 1]);
    t.state.listOk = false;
    expect(await t.sync.load("BTCUSDT")).toBe(false);
  });

  it("a re-read during a pending or in-flight delete never brings the drawing back", async () => {
    const t = setup();
    const ids = (): string[] => t.store.selectPane("BTCUSDT", null).map((d) => d.id);
    const handle = t.store.create(input());
    t.sync.flush();
    await flush();
    const id = ids()[0] ?? "";
    t.state.items = [row(id, input())];
    t.store.remove("BTCUSDT", [handle]);
    expect(ids()).toEqual([]);
    expect(await t.sync.load("BTCUSDT")).toBe(true);
    expect(ids()).toEqual([]);
    let answer: (outcome: BatchOutcome) => void = () => undefined;
    t.queue.push(
      new Promise<BatchOutcome>((resolve) => {
        answer = resolve;
      }),
    );
    t.sync.flush();
    await flush();
    expect(t.calls.at(-1)?.ops).toEqual([expect.objectContaining({ op: "delete", id })]);
    expect(await t.sync.load("BTCUSDT")).toBe(true);
    expect(ids()).toEqual([]);
    answer({ kind: "ok", result: { created: [], updated: [], deleted: [id] } });
    await flush();
    expect(ids()).toEqual([]);
    t.state.items = [];
    expect(await t.sync.load("BTCUSDT")).toBe(true);
    expect(ids()).toEqual([]);
    expect(t.store.tokenOf(id)).toBeNull();
  });

  it("a resync landing while a delete is pending keeps it deleted, then sends it", async () => {
    const t = setup();
    const ids = (): string[] => t.store.selectPane("BTCUSDT", null).map((d) => d.id);
    const a = t.store.create(input());
    const b = t.store.create(input("BTCUSDT", { label: "b" }));
    t.sync.flush();
    await flush();
    const [idA, idB] = ids();
    t.state.items = t.store.selectPane("BTCUSDT", null).map((d) => row(d.id, d.input));
    let answer: (outcome: BatchOutcome) => void = () => undefined;
    t.queue.push(
      new Promise<BatchOutcome>((resolve) => {
        answer = resolve;
      }),
    );
    t.store.update("BTCUSDT", a, { label: "x" });
    t.sync.flush();
    await flush();
    t.store.remove("BTCUSDT", [b]);
    expect(ids()).toEqual([idA]);
    answer({ kind: "rejected", status: 403, code: "forbidden" });
    await flush();
    expect(t.state.lists).toBe(1);
    expect(ids()).toEqual([idA]);
    await t.clock.advance(500);
    expect(t.calls.at(-1)?.ops).toEqual([expect.objectContaining({ op: "delete", id: idB })]);
    expect(ids()).toEqual([idA]);
  });

  it("dispose unsubscribes from the store, clears timers and ignores a late answer", async () => {
    const t = setup();
    let release: (o: BatchOutcome) => void = () => undefined;
    t.queue.push(new Promise<BatchOutcome>((r) => (release = r)));
    t.store.create(input());
    t.sync.flush();
    await flush();
    t.store.create(input());
    expect(t.clock.size()).toBe(1);
    t.sync.dispose();
    expect(t.clock.size()).toBe(0);
    release({ kind: "retryable", status: 503 });
    await flush();
    t.store.create(input());
    await t.clock.advance(10_000);
    expect(t.calls).toHaveLength(1);
    expect(t.clock.size()).toBe(0);
    expect(await t.sync.load("BTCUSDT")).toBe(false);
  });

  it("dispose during a retry wait clears that timer too", async () => {
    const t = setup();
    t.queue.push({ kind: "retryable", status: 503 });
    t.store.create(input());
    t.sync.flush();
    await flush();
    expect(t.clock.size()).toBe(1);
    t.sync.dispose();
    expect(t.clock.size()).toBe(0);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("defaults to the real timers and clock", async () => {
    vi.useFakeTimers();
    const fake = fakeApi();
    const store = createDrawingStore();
    const sync = createDrawingSync({ store, api: fake.api });
    store.create(input());
    await vi.advanceTimersByTimeAsync(500);
    expect(fake.calls).toHaveLength(1);
    expect(fake.calls[0]?.key).toMatch(/^[0-9a-f-]{36}$/);
    sync.dispose();
  });
});
