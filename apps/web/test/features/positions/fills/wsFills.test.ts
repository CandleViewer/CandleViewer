/**
 * E29-S04 (#979) the feed, on fake timers: the `executions` subscription on the private lane with
 * no throttle, a drain every animation frame and a commit every 200 ms at most (5 Hz, D03 §3.9),
 * the REST backfill at first paint and after each snapshot (two pages of 500 at most, never
 * polled), the marks and their measure, S-02's 5 s budget and Retry, the 25-account cap, a
 * narrowing settled through the directory, and teardown.
 */
import { act } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AccountsOutcome, ExchangeAccount } from "../../../../src/features/positions/api";
import type { FillsApi } from "../../../../src/features/positions/fills/api";
import {
  createFillsStore,
  type FillsStore,
} from "../../../../src/features/positions/fills/fillsStore";
import {
  APPLY_MEASURE,
  BACKFILL_PAGES,
  COMMIT_INTERVAL_MS,
  FILLS_PANE_ID,
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
    const many = Array.from({ length: 27 }, (_, i) => ({
      ...accounts[0],
      id: `a1000000-0000-4000-8000-${(i + 1).toString().padStart(12, "0")}`,
      label: `A${i}`,
    })) as ExchangeAccount[];
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
    expect(store.getSnapshot()).toMatchObject({ status: "live", dedupeHits: 13 });
    expect(store.getSnapshot().rows).toHaveLength(14);
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
    accountsApi.listExchangeAccounts.mockResolvedValueOnce({
      kind: "ok",
      items: accounts.filter((a) => a.id !== SUB2),
    });
    handle()?.push(reset("narrowed"));
    await settle(COMMIT_INTERVAL_MS + FRAME_MS);
    expect(accountsApi.listExchangeAccounts).toHaveBeenCalledTimes(2);
    expect(store.getSnapshot().withdrawn.map((w) => w.label)).toEqual(["Sub-2"]);
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
});
