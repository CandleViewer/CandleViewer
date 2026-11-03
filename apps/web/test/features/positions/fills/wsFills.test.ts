/**
 * E29-S04 (#979) the feed, on fake timers: the `executions` subscription on the private lane with
 * no throttle, a drain every animation frame and a commit every 200 ms at most (5 Hz, D03 §3.9),
 * a security reset at once, the REST backfill at first paint and after each snapshot or settled
 * narrowing (two pages of 500 at most, at most one per interval, never polled) applied 200 fills
 * a frame, a failed read, the marks and their measure, S-02's 5 s budget and Retry, the 25-account
 * cap, the link, a narrowing settled through the directory, Retry after a revoke, and teardown.
 */
import { act } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AccountsOutcome, ExchangeAccount } from "../../../../src/features/positions/api";
import type { ExecutionsPage, FillsApi, Read } from "../../../../src/features/positions/fills/api";
import {
  createFillsStore,
  type FillsStore,
} from "../../../../src/features/positions/fills/fillsStore";
import {
  APPLY_MEASURE,
  APPLY_SLICE,
  BACKFILL_INTERVAL_MS,
  BACKFILL_PAGES,
  COMMIT_INTERVAL_MS,
  FILLS_PANE_ID,
  MAX_QUEUED,
  SNAPSHOT_BUDGET_MS,
  startFillsFeed,
  type FillsFeed,
} from "../../../../src/features/positions/fills/wsFills";
import {
  delta,
  fakeClient,
  fakeRaf,
  golden as positionsGolden,
  MAIN,
  reset,
  snap,
  SUB1,
  SUB2,
  type FakeClient,
} from "../support/fakes";
import { deltaBody, restItems, snapshotBody } from "./support/fills";

const accounts = positionsGolden<{ items: ExchangeAccount[] }>(
  "rest_list_exchange_accounts.json",
).items;
const FRAME_MS = 16;
const many = Array.from({ length: 27 }, (_, i) => ({
  ...accounts[0],
  id: `a1000000-0000-4000-8000-${(i + 1).toString().padStart(12, "0")}`,
  label: `A${i}`,
})) as ExchangeAccount[];
const sub2Left = { kind: "ok" as const, items: accounts.filter((a) => a.id !== SUB2) };

function fakeApi(hasMore = false): FillsApi & { queries: unknown[] } {
  const queries: unknown[] = [];
  return {
    queries,
    listExecutions: vi.fn(async (query, page) => {
      queries.push({ query, cursor: page?.cursor });
      return {
        kind: "ok" as const,
        value: { items: restItems(), nextCursor: hasMore ? "more" : null, hasMore },
      };
    }),
    getOrder: vi.fn(),
    getTradeGroup: vi.fn(),
    getInstrument: vi.fn(),
  };
}
const directory = (items: ExchangeAccount[] = accounts) => ({
  listExchangeAccounts: vi.fn(async (): Promise<AccountsOutcome> => ({ kind: "ok", items })),
});
const page = (items: unknown[], more = false): Read<ExecutionsPage> => ({
  kind: "ok",
  value: {
    items: items as ExecutionsPage["items"],
    nextCursor: more ? "more" : null,
    hasMore: more,
  },
});

/** Reads the test answers by hand: each call waits until `answer`, or for ever. */
function heldApi(): FillsApi & {
  calls: { signal: AbortSignal | undefined; answer: (out: Read<ExecutionsPage>) => void }[];
} {
  const calls: { signal: AbortSignal | undefined; answer: (out: Read<ExecutionsPage>) => void }[] =
    [];
  return {
    calls,
    listExecutions: (_query, _page, signal) =>
      new Promise((answer) => calls.push({ signal, answer })),
    getOrder: vi.fn(),
    getTradeGroup: vi.fn(),
    getInstrument: vi.fn(),
  };
}

/** `n` fills of one account, each its own exec id. */
const manyFills = (n: number): unknown[] => {
  const base = restItems()[1];
  return Array.from({ length: n }, (_, i) => ({
    ...base,
    id: `0e000000-0000-4000-8000-${i.toString(16).padStart(12, "0")}`,
    exec_id: `bulk-${i}`,
  }));
};

let ws: FakeClient;
let store: FillsStore;
let feed: FillsFeed | undefined;
const perf = { mark: vi.fn(), measure: vi.fn(), clearMarks: vi.fn(), clearMeasures: vi.fn() };

function start(
  api: FillsApi = fakeApi(),
  extra: Partial<Parameters<typeof startFillsFeed>[0]> = {},
): FillsFeed {
  feed = startFillsFeed({
    client: ws.client,
    store,
    api,
    accounts: directory(),
    ...fakeRaf,
    now: () => Date.now(),
    performance: perf,
    ...extra,
  });
  return feed;
}
const settle = async (ms = 0): Promise<void> => {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
};
const handle = () => ws.live("executions")[0];
/** A feed on `heldApi()`'s reads, its directory settled: call 0 is first paint's read. */
async function startHeld(): Promise<ReturnType<typeof heldApi>> {
  const api = heldApi();
  start(api);
  await settle();
  return api;
}

beforeEach(() => {
  vi.useFakeTimers();
  ws = fakeClient();
  store = createFillsStore();
  for (const fn of Object.values(perf)) fn.mockReset();
});
afterEach(() => {
  feed?.stop();
  feed = undefined;
  vi.useRealTimers();
});

describe("the subscription", () => {
  it("consumes executions on the private lane for the directory's accounts, with no throttle", async () => {
    start();
    await settle();
    expect(handle()?.spec).toEqual({
      ch: "executions",
      paneId: FILLS_PANE_ID,
      priority: "private",
      opts: { exchange_account_ids: [MAIN, SUB1, SUB2] },
    });
  });

  it("past 25 accounts it names the first 25; the backfill names them too", async () => {
    const api = fakeApi();
    start(api, { accounts: directory(many) });
    await settle();
    const ids = (handle()?.spec.opts as { exchange_account_ids: string[] }).exchange_account_ids;
    expect(ids).toHaveLength(25);
    handle()?.push(snap(snapshotBody()));
    await settle(FRAME_MS);
    const last = api.queries.at(-1) as { query: { accountIds?: string[] } };
    expect(last.query.accountIds).toEqual(ids);
  });

  it("an account past 25 never shows, though a first-paint read brought its fills", async () => {
    const over = [many[25]?.id, many[26]?.id];
    const api = fakeApi();
    vi.mocked(api.listExecutions).mockResolvedValueOnce(
      page(
        restItems().map((item, n) =>
          n < 7 ? { ...item, exchange_account_id: over[n % 2] } : item,
        ),
      ),
    );
    start(api, { accounts: directory(many) });
    await settle(FRAME_MS + COMMIT_INTERVAL_MS);
    const shown = new Set(store.getSnapshot().rows.map((r) => r.accountId));
    expect(shown.size).toBeGreaterThan(0);
    expect(over.some((id) => id !== undefined && shown.has(id))).toBe(false);
  });

  it("the store hears the effective options once a sub_ok, never every frame", async () => {
    const setEffective = vi.spyOn(store, "setEffective");
    start();
    await settle();
    handle()?.setEffective({ exchange_account_ids: [MAIN, SUB1, SUB2] });
    await settle(FRAME_MS * 10);
    expect(setEffective).toHaveBeenCalledTimes(1);
  });

  it("a link that goes offline reads offline", async () => {
    start();
    await settle();
    handle()?.push(snap(snapshotBody()));
    await settle(FRAME_MS);
    ws.setLink({ kind: "offline", cause: "offline" });
    await settle(COMMIT_INTERVAL_MS + FRAME_MS);
    expect(store.getSnapshot().status).toBe("offline");
  });
});

describe("REST: at first paint and after each snapshot, never polled (BQ-9)", () => {
  it("one read at first paint, one after a snapshot, each at most two pages of 500", async () => {
    const api = fakeApi(true); // a server that always has more: the page bound stops it
    start(api);
    await settle();
    expect(api.queries).toHaveLength(BACKFILL_PAGES);
    handle()?.push(snap(snapshotBody()));
    await settle(FRAME_MS);
    expect(api.queries).toHaveLength(2 * BACKFILL_PAGES);
    expect(api.queries.map((q) => (q as { cursor?: string }).cursor)).toEqual([
      undefined,
      "more",
      undefined,
      "more",
    ]);
    await settle(10_000);
    expect(api.queries).toHaveLength(2 * BACKFILL_PAGES);
  });

  it("the backfill and the stream meet in one list: each fill once", async () => {
    start();
    await settle();
    handle()?.push(snap(snapshotBody()), delta(deltaBody()));
    await settle(COMMIT_INTERVAL_MS + FRAME_MS);
    expect(store.getSnapshot().status).toBe("live");
    expect(store.getSnapshot().rows).toHaveLength(14);
  });

  it("the dedupe counter settles at the 13 fills both sources brought, however many backfills", async () => {
    start();
    await settle();
    handle()?.push(snap(snapshotBody()), delta(deltaBody()));
    await settle(BACKFILL_INTERVAL_MS);
    handle()?.push(snap(snapshotBody())); // a re-snapshot, and its backfill
    await settle(COMMIT_INTERVAL_MS + FRAME_MS);
    expect(store.getSnapshot().dedupeHits).toBe(13);
  });

  it("a snapshot's backfill reads at most once an interval; one asked inside reads at its end", async () => {
    const api = fakeApi();
    start(api);
    await settle();
    handle()?.push(snap(snapshotBody()));
    await settle(FRAME_MS);
    expect(api.queries).toHaveLength(2);
    for (let i = 0; i < 3; i += 1) {
      handle()?.push(snap(snapshotBody()));
      await settle(FRAME_MS);
    }
    expect(api.queries).toHaveLength(2);
    await settle(BACKFILL_INTERVAL_MS);
    expect(api.queries).toHaveLength(3);
  });

  it("the backfills asked inside one interval share one owed read, and the reads stop after it", async () => {
    const api = fakeApi();
    start(api);
    await settle();
    for (let i = 0; i < 4; i += 1) {
      handle()?.push(snap(snapshotBody()));
      await settle(FRAME_MS);
    }
    await settle(BACKFILL_INTERVAL_MS);
    const afterOwed = api.queries.length;
    expect(afterOwed).toBe(3); // first paint, the first snapshot's, the one owed at the interval's end
    await settle(BACKFILL_INTERVAL_MS * 3);
    expect(api.queries).toHaveLength(afterOwed); // never polled (BQ-9)
  });

  it("a settled narrowing reads REST again, to bring back who stayed", async () => {
    const api = fakeApi();
    const accountsApi = directory();
    start(api, { accounts: accountsApi });
    await settle();
    handle()?.push(snap(snapshotBody()));
    await settle(BACKFILL_INTERVAL_MS);
    accountsApi.listExchangeAccounts.mockResolvedValueOnce(sub2Left);
    handle()?.push(reset("narrowed"));
    await settle(FRAME_MS * 3 + COMMIT_INTERVAL_MS);
    expect(api.queries).toHaveLength(3);
    expect(new Set(store.getSnapshot().rows.map((r) => r.accountId))).toEqual(
      new Set([MAIN, SUB1]),
    );
  });

  it("a read superseded by a newer one still applies: the store is a set", async () => {
    const api = await startHeld();
    handle()?.push(snap(snapshotBody()));
    await settle(FRAME_MS);
    api.calls[1]?.answer(page([]));
    api.calls[0]?.answer(page(restItems()));
    await settle(FRAME_MS + COMMIT_INTERVAL_MS);
    const execs = store.getSnapshot().rows.map((r) => r.execId.slice(-4));
    expect(execs).toContain("0014"); // the ADL fill only the first read held
  });

  it("a failed read is readFailed; the live rows stay", async () => {
    const api = fakeApi();
    vi.mocked(api.listExecutions).mockResolvedValue({ kind: "unavailable" });
    start(api);
    await settle();
    handle()?.push(snap(snapshotBody()));
    await settle(FRAME_MS + COMMIT_INTERVAL_MS);
    expect(store.getSnapshot()).toMatchObject({ status: "live", readFailed: true });
    expect(store.getSnapshot().rows).toHaveLength(12);
  });

  it("an older read that fails after a newer one succeeded leaves readFailed false", async () => {
    const api = await startHeld();
    handle()?.push(snap(snapshotBody()));
    await settle(FRAME_MS); // call 0 is first paint's read, which hangs; call 1 the snapshot's
    api.calls[1]?.answer(page(restItems()));
    await settle(FRAME_MS + COMMIT_INTERVAL_MS);
    expect(store.getSnapshot().readFailed).toBe(false);
    api.calls[0]?.answer({ kind: "unavailable" });
    await settle(FRAME_MS + COMMIT_INTERVAL_MS);
    expect(store.getSnapshot().readFailed).toBe(false);
  });

  it("a failed second page keeps the first: its fills apply, and the read is readFailed", async () => {
    const api = fakeApi();
    vi.mocked(api.listExecutions)
      .mockResolvedValueOnce(page(restItems(), true))
      .mockResolvedValueOnce({ kind: "unavailable" });
    start(api);
    await settle(FRAME_MS + COMMIT_INTERVAL_MS);
    expect(store.getSnapshot()).toMatchObject({ readFailed: true });
    expect(store.getSnapshot().rows).toHaveLength(14);
  });

  it("Retry after a failed read reads again, and a live feed is not made again", async () => {
    const api = fakeApi();
    vi.mocked(api.listExecutions)
      .mockResolvedValueOnce({ kind: "unavailable" })
      .mockResolvedValueOnce({ kind: "unavailable" });
    start(api);
    await settle();
    handle()?.push(snap(snapshotBody()));
    await settle(FRAME_MS + COMMIT_INTERVAL_MS);
    const live = handle();
    feed?.retry();
    await settle(FRAME_MS + COMMIT_INTERVAL_MS);
    expect(store.getSnapshot()).toMatchObject({ readFailed: false });
    expect(store.getSnapshot().rows).toHaveLength(14);
    expect(live?.released).toBe(false);
  });
});

describe("REST applies 200 fills a frame at most, inside the measure (m5)", () => {
  it("a read of 1,000 fills applies in five frames of 200, each measured", async () => {
    const api = fakeApi();
    vi.mocked(api.listExecutions).mockResolvedValueOnce(page(manyFills(1_000)));
    const applyRest = vi.spyOn(store, "applyRest");
    start(api);
    await settle(FRAME_MS * 6);
    expect(applyRest.mock.calls.map(([items]) => items.length)).toEqual([200, 200, 200, 200, 200]);
    expect(perf.measure).toHaveBeenCalledTimes(5);
  });

  it("a frame's WS items count first: a snapshot's 12 leave 188 for REST", async () => {
    const api = fakeApi();
    vi.mocked(api.listExecutions).mockResolvedValueOnce(page(manyFills(400)));
    const applyRest = vi.spyOn(store, "applyRest");
    start(api);
    await settle();
    handle()?.push(snap(snapshotBody()));
    await settle(FRAME_MS);
    expect(applyRest.mock.calls.map(([items]) => items.length)).toEqual([APPLY_SLICE - 12]);
  });

  it("the queue holds the bound's worth across reads; what is over waits for the next backfill", async () => {
    const api = await startHeld();
    const applyRest = vi.spyOn(store, "applyRest");
    handle()?.push(snap({ executions: [] }));
    await settle(FRAME_MS); // call 0 is first paint's read, call 1 the snapshot's
    const perRead = Math.ceil(MAX_QUEUED * 0.6); // two of them are more than the bound
    api.calls[0]?.answer(page(manyFills(perRead)));
    api.calls[1]?.answer(page(manyFills(perRead)));
    await settle(FRAME_MS * (MAX_QUEUED / APPLY_SLICE + 10));
    expect(applyRest.mock.calls.flatMap(([items]) => items)).toHaveLength(MAX_QUEUED);
  });
});

describe("a drain every animation frame, a commit every 200 ms (5 Hz, D03 §3.9)", () => {
  it("frames arriving every frame are drained each frame and committed at most 5 times a second", async () => {
    start();
    await settle(FRAME_MS);
    const h = handle();
    if (h === undefined) throw new Error("no handle");
    const read = vi.spyOn(h, "read");
    h.push(snap({ executions: [] }));
    const commits = vi.fn();
    store.subscribe(commits);
    const [fill] = deltaBody().executions;
    for (let i = 0; i < 60; i += 1) {
      h.push(
        delta({ executions: [{ ...fill, exec_id: `live-${i}`, ts_ms: 1_792_677_800_000 + i }] }),
      );
      await settle(FRAME_MS);
    }
    await settle(COMMIT_INTERVAL_MS);
    expect(read.mock.calls.length).toBeGreaterThanOrEqual(60); // every frame drains
    const elapsed = 60 * FRAME_MS + COMMIT_INTERVAL_MS;
    expect(commits.mock.calls.length).toBeLessThanOrEqual(
      Math.ceil(elapsed / COMMIT_INTERVAL_MS) + 1,
    );
    expect(commits.mock.calls.length).toBeGreaterThanOrEqual(2);
    const live = store.getSnapshot().rows.filter((r) => r.execId.startsWith("live-"));
    expect(live).toHaveLength(60); // none lost
  });

  it("a committed frame writes the apply-to-paint measure for executions; an idle one none", async () => {
    start();
    await settle(COMMIT_INTERVAL_MS * 2);
    perf.measure.mockReset();
    handle()?.push(snap(snapshotBody()));
    await settle(COMMIT_INTERVAL_MS + FRAME_MS);
    expect(perf.measure).toHaveBeenCalledWith(
      APPLY_MEASURE,
      expect.objectContaining({ detail: { topic: "executions" } }),
    );
    await settle(COMMIT_INTERVAL_MS * 2); // the snapshot's backfill lands and commits
    perf.measure.mockReset();
    await settle(COMMIT_INTERVAL_MS * 3);
    expect(perf.measure).not.toHaveBeenCalled();
  });
});

describe("S-02, Retry, a narrowing and teardown", () => {
  it("no snapshot within 5 s is Could not load; Retry subscribes again", async () => {
    start();
    await settle(SNAPSHOT_BUDGET_MS + COMMIT_INTERVAL_MS);
    expect(store.getSnapshot().status).toBe("snapshot_failed");
    const first = handle();
    feed?.retry();
    await settle(FRAME_MS + COMMIT_INTERVAL_MS);
    expect(first?.released).toBe(true);
    expect(ws.live("executions")).toHaveLength(1);
    expect(store.getSnapshot().status).toBe("loading");
  });

  it("a narrowing re-reads the directory, which names who left", async () => {
    const accountsApi = directory();
    start(fakeApi(), { accounts: accountsApi });
    await settle();
    handle()?.push(snap(snapshotBody()));
    await settle(FRAME_MS);
    accountsApi.listExchangeAccounts.mockResolvedValueOnce(sub2Left);
    handle()?.push(reset("narrowed"));
    await settle(COMMIT_INTERVAL_MS + FRAME_MS);
    expect(accountsApi.listExchangeAccounts).toHaveBeenCalledTimes(2);
    expect(store.getSnapshot().withdrawn.map((w) => w.label)).toEqual(["Sub-2"]);
  });

  /** A narrowing whose directory read fails; its snapshot serves Main and Sub-1, not Sub-2. */
  async function narrowingLost(): Promise<ReturnType<typeof directory>> {
    const accountsApi = directory();
    start(fakeApi(), { accounts: accountsApi });
    await settle();
    handle()?.push(snap(snapshotBody()));
    await settle(BACKFILL_INTERVAL_MS);
    accountsApi.listExchangeAccounts.mockResolvedValueOnce({ kind: "unavailable" });
    const served = snapshotBody().executions.filter((i) => i.exchange_account_id !== SUB2);
    handle()?.push(reset("narrowed"), snap({ executions: served }));
    await settle(COMMIT_INTERVAL_MS * 2); // the reset is published at once, the failure next
    return accountsApi;
  }
  const shows = (id: string): boolean => store.getSnapshot().rows.some((r) => r.accountId === id);

  it("a narrowing whose directory read fails is Could not load while Sub-2 waits", async () => {
    await narrowingLost();
    expect(store.getSnapshot()).toMatchObject({ status: "live", readFailed: true });
    expect(shows(SUB2)).toBe(false);
  });

  it("Retry then reads the directory again, and the narrowing it settles brings Sub-2 back", async () => {
    const accountsApi = await narrowingLost();
    feed?.retry();
    await settle(BACKFILL_INTERVAL_MS + COMMIT_INTERVAL_MS * 2);
    expect(accountsApi.listExchangeAccounts).toHaveBeenCalledTimes(3);
    expect(store.getSnapshot().readFailed).toBe(false);
    expect(shows(SUB2)).toBe(true);
  });

  it("a narrowing that settles after its failed directory read is no longer Could not load", async () => {
    await narrowingLost();
    handle()?.push(snap(snapshotBody())); // it serves Sub-2 as well: the narrowing settles
    await settle(COMMIT_INTERVAL_MS * 2);
    expect(store.getSnapshot().readFailed).toBe(false);
  });

  it("a directory read that fails after a snapshot settled its narrowing shows nothing", async () => {
    const accountsApi = directory();
    start(fakeApi(), { accounts: accountsApi });
    await settle();
    accountsApi.listExchangeAccounts.mockResolvedValueOnce({ kind: "unavailable" });
    handle()?.push(snap(snapshotBody()), reset("narrowed"), snap(snapshotBody()));
    await settle(COMMIT_INTERVAL_MS * 2);
    expect(store.getSnapshot().readFailed).toBe(false);
  });

  it("a revocation clears the published rows at once, inside the 200 ms window", async () => {
    start();
    await settle(COMMIT_INTERVAL_MS * 2);
    handle()?.push(snap(snapshotBody()));
    await settle(FRAME_MS);
    expect(store.getSnapshot().rows.length).toBeGreaterThan(0);
    handle()?.push(reset("revoked"));
    await settle(FRAME_MS);
    expect(store.getSnapshot()).toMatchObject({ status: "revoked", rows: [] });
  });

  it("Retry after a revoke drops the answers of reads issued before it", async () => {
    const api = await startHeld();
    handle()?.push(reset("revoked"));
    await settle(FRAME_MS);
    feed?.retry();
    api.calls[0]?.answer(page(restItems())); // asked before the Retry: it never reaches the rows
    handle()?.push(snap({ executions: [] })); // the new subscription's snapshot asks the next read
    await settle(FRAME_MS);
    api.calls[1]?.answer(page(restItems().slice(0, 2))); // asked after it: these two apply
    await settle(FRAME_MS + COMMIT_INTERVAL_MS);
    expect([api.calls[0]?.signal?.aborted, store.getSnapshot().all.length]).toEqual([true, 2]);
  });

  it("Retry after a revoke drops the answers still waiting for a frame", async () => {
    const api = await startHeld();
    api.calls[0]?.answer(page(manyFills(2 * APPLY_SLICE)));
    handle()?.push(reset("revoked")); // the frame takes 200 of the 400; 200 wait
    await settle(FRAME_MS);
    feed?.retry();
    handle()?.push(snap({ executions: [] })); // the new subscription's snapshot asks the next read
    await settle(FRAME_MS);
    api.calls[1]?.answer(page(restItems().slice(0, 2))); // asked after the Retry: these two apply
    await settle(FRAME_MS + COMMIT_INTERVAL_MS);
    expect(store.getSnapshot().all).toHaveLength(2);
  });

  it("Retry after a revoke drops a read whose second page it aborted, its first page too", async () => {
    const api = await startHeld();
    api.calls[0]?.answer(page(restItems(), true)); // page 1 answers and page 2 is asked
    handle()?.push(reset("revoked"));
    await settle(FRAME_MS);
    feed?.retry();
    api.calls[1]?.answer({ kind: "unavailable" }); // the aborted page 2: the read ends ok with page 1
    await settle(FRAME_MS + COMMIT_INTERVAL_MS);
    expect(store.getSnapshot()).toMatchObject({ all: [], readFailed: false });
  });

  it("stop releases the subscription and drains no more", async () => {
    start();
    await settle(FRAME_MS);
    const h = handle();
    feed?.stop();
    feed = undefined;
    expect(h?.released).toBe(true);
    const read = h === undefined ? undefined : vi.spyOn(h, "read");
    await settle(COMMIT_INTERVAL_MS);
    expect(read).not.toHaveBeenCalled();
    expect(store.getSnapshot().status).toBe("idle");
  });

  it("stop leaves no timer behind: the 5 s budget is cleared", async () => {
    start();
    await settle();
    expect(vi.getTimerCount()).toBeGreaterThan(0);
    feed?.stop();
    expect(vi.getTimerCount()).toBe(0);
  });

  it("stop leaves no timer behind: a backfill owed for the interval's end is cleared", async () => {
    start();
    await settle();
    handle()?.push(snap(snapshotBody()));
    await settle(FRAME_MS);
    handle()?.push(snap(snapshotBody()));
    await settle(FRAME_MS);
    feed?.stop();
    expect(vi.getTimerCount()).toBe(0);
  });

  it("stop aborts a read in flight", async () => {
    const api = await startHeld();
    feed?.stop();
    expect(api.calls[0]?.signal?.aborted).toBe(true);
  });
});
