/**
 * E29-S01 (#911) the feed, on fake timers: the subscriptions it makes, the 10 Hz commit tick, the
 * "Live update latency" scenario proven deterministically (BQ-21: an arrival is on the screen within
 * one 100 ms tick and one frame), the `state.apply` / `paint` marks with the `ws_frame_apply_seconds`
 * measure, S-02's 5 s budget and Retry, the link-down REST fallback (one read, never a poll), and
 * a narrowing's re-subscribe.
 */
import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { generated } from "@candleviewer/protocol";
import { createAccountSignals } from "../../../src/features/positions/accountSignals";
import type {
  AccountsOutcome,
  ExchangeAccount,
  PositionsApi,
  PositionsOutcome,
  Position,
} from "../../../src/features/positions/api";
import {
  createPositionsStore,
  usePositions,
  type PositionsStore,
} from "../../../src/features/positions/positionsStore";
import {
  APPLY_MEASURE,
  COMMIT_INTERVAL_MS,
  lockoutChannel,
  MARK_PREFIX,
  MAX_MEASURES,
  POSITIONS_PANE_ID,
  SNAPSHOT_BUDGET_MS,
  startPositionsFeed,
  type PositionsFeed,
} from "../../../src/features/positions/wsPositions";
import {
  delta,
  fakeClient,
  fakeRaf,
  golden,
  MAIN,
  reset,
  snap,
  SUB1,
  SUB2,
  type FakeClient,
} from "./support/fakes";

type Positions = generated.ws.Positions;
const snapshot = golden<Positions>("ws_positions_snapshot.json");
const deltas = golden<{ case: string; body: Positions }[]>("ws_positions_deltas.json");
const update = deltas.find((d) => d.case === "update")?.body as Positions;
const accounts = golden<{ items: ExchangeAccount[] }>("rest_list_exchange_accounts.json").items;
const restItems = golden<{ items: Position[] }>("rest_list_positions.json").items;

function fakeApi(over: Partial<PositionsApi> = {}): PositionsApi & { calls: string[] } {
  const calls: string[] = [];
  return {
    calls,
    listPositions: vi.fn(async (): Promise<PositionsOutcome> => {
      calls.push("positions");
      return { kind: "ok", items: restItems, aggregates: [] };
    }),
    listExchangeAccounts: vi.fn(async (): Promise<AccountsOutcome> => {
      calls.push("accounts");
      return { kind: "ok", items: accounts };
    }),
    ...over,
  };
}

let ws: FakeClient;
let store: PositionsStore;
let feed: PositionsFeed | undefined;
const perf = { mark: vi.fn(), measure: vi.fn(), clearMarks: vi.fn(), clearMeasures: vi.fn() };

function start(
  api: PositionsApi = fakeApi(),
  extra: Partial<Parameters<typeof startPositionsFeed>[0]> = {},
): PositionsFeed {
  feed = startPositionsFeed({
    client: ws.client,
    store,
    api,
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
const positionsHandle = () => ws.live("positions")[0];

beforeEach(() => {
  vi.useFakeTimers();
  ws = fakeClient();
  store = createPositionsStore();
  perf.mark.mockReset();
  perf.measure.mockReset();
  perf.clearMarks.mockReset();
  perf.clearMeasures.mockReset();
});
afterEach(() => {
  feed?.stop();
  feed = undefined;
  vi.useRealTimers();
});

describe("subscriptions", () => {
  it("consumes positions and wallet for the directory's accounts, private first, and B20 per account", async () => {
    start();
    await settle();
    const [positions] = ws.live("positions");
    expect(positions?.spec).toEqual({
      ch: "positions",
      opts: { exchange_account_ids: [MAIN, SUB1, SUB2] },
      paneId: POSITIONS_PANE_ID,
      priority: "private",
    });
    expect(ws.live("wallet")[0]?.spec.opts).toEqual({ exchange_account_ids: [MAIN, SUB1, SUB2] });
    expect(ws.handles.filter((h) => h.ch.startsWith("machines.")).map((h) => h.ch)).toEqual([
      lockoutChannel(MAIN),
      lockoutChannel(SUB1),
      lockoutChannel(SUB2),
    ]);
    expect(ws.handles.every((h) => h.spec.priority === "private")).toBe(true);
  });

  it("a first connect is not a loss: no fallback read, not offline", async () => {
    ws.setState({ link: { kind: "connecting" } });
    const api = fakeApi();
    start(api);
    await settle(COMMIT_INTERVAL_MS + 16);
    expect(api.calls.filter((c) => c === "positions")).toHaveLength(1); // first paint only
    expect(store.getSnapshot().status).toBe("loading");
  });

  it("names at most 25 accounts; the rest are over the cap", async () => {
    const many = Array.from({ length: 27 }, (_, i) => ({
      ...(accounts[0] as ExchangeAccount),
      id: `a1000000-0000-4000-8000-${String(i + 100).padStart(12, "0")}`,
      label: `Acct ${i}`,
    }));
    start(fakeApi({ listExchangeAccounts: async () => ({ kind: "ok", items: many }) }));
    await settle(COMMIT_INTERVAL_MS + 16);
    expect(
      (positionsHandle()?.spec.opts as { exchange_account_ids: string[] }).exchange_account_ids,
    ).toHaveLength(25);
    expect(store.getSnapshot().overCap).toHaveLength(2);
  });

  it("no accounts: nothing to subscribe to", async () => {
    start(fakeApi({ listExchangeAccounts: async () => ({ kind: "ok", items: [] }) }));
    await settle(COMMIT_INTERVAL_MS + 16);
    expect(ws.handles).toEqual([]);
    expect(store.getSnapshot().status).toBe("no_accounts");
  });
});

describe("the 10 Hz tick", () => {
  it("REST is first paint, then the snapshot; frames wait for the tick and commit once", async () => {
    start();
    await settle(COMMIT_INTERVAL_MS + 16);
    expect(store.getSnapshot()).toMatchObject({ status: "loading", source: "rest" });
    const listener = vi.fn();
    store.subscribe(listener);
    positionsHandle()?.push(snap(snapshot), delta(update), delta(update));
    expect(listener).not.toHaveBeenCalled(); // never applied on arrival (C9)
    await settle(COMMIT_INTERVAL_MS + 16);
    expect(listener).toHaveBeenCalledTimes(1);
    expect(store.getSnapshot()).toMatchObject({ status: "live", source: "ws" });
    await settle(COMMIT_INTERVAL_MS * 5);
    expect(listener).toHaveBeenCalledTimes(1); // nothing new: no commit
  });

  it("marks state.apply and paint, and measures ws_frame_apply_seconds for a tick that applied frames", async () => {
    start();
    await settle(COMMIT_INTERVAL_MS + 16);
    expect(perf.mark).not.toHaveBeenCalled(); // an idle tick writes nothing
    positionsHandle()?.push(snap(snapshot));
    await settle(COMMIT_INTERVAL_MS + 16);
    expect(perf.mark.mock.calls.map(([name]) => name)).toEqual([
      `${MARK_PREFIX}state.apply`,
      `${MARK_PREFIX}paint`,
    ]);
    expect(perf.measure).toHaveBeenCalledTimes(1);
    const [name, options] = perf.measure.mock.calls[0] ?? [];
    expect(name).toBe(APPLY_MEASURE);
    expect(options).toEqual({
      start: expect.any(Number),
      end: expect.any(Number),
      detail: { topic: "positions" },
    });
    expect(perf.clearMarks).toHaveBeenCalledWith(`${MARK_PREFIX}state.apply`);
  });

  it("keeps a bounded number of measures in the timeline (MAX_MEASURES by default)", async () => {
    expect(MAX_MEASURES).toBe(1_000);
    start(fakeApi(), { maxMeasures: 3 });
    await settle(COMMIT_INTERVAL_MS + 16); // past a frame: each push below gets its own tick
    for (let i = 0; i < 7; i += 1) {
      positionsHandle()?.push(delta(update));
      await settle(COMMIT_INTERVAL_MS);
    }
    expect(perf.measure).toHaveBeenCalledTimes(7);
    expect(perf.clearMeasures).toHaveBeenCalledTimes(2);
    expect(perf.clearMeasures).toHaveBeenCalledWith(APPLY_MEASURE);
  });

  it("a measure that throws never stops the feed; no performance, no marks", async () => {
    start(fakeApi(), {
      performance: {
        mark: () => undefined,
        measure: () => {
          throw new Error("x");
        },
      },
    });
    await settle();
    positionsHandle()?.push(snap(snapshot));
    await settle(COMMIT_INTERVAL_MS + 16);
    expect(store.getSnapshot().status).toBe("live");
  });
});

function Probe({ positions }: { positions: PositionsStore }) {
  const rows = usePositions(positions, (s) => s.rows);
  return (
    <ul aria-label="positions">
      {rows.map((r) => (
        <li key={r.key}>{`${r.accountLabel ?? ""} ${r.symbol} mark ${r.mark ?? "—"}`}</li>
      ))}
    </ul>
  );
}

describe("Live update latency: a position event on the WS positions topic updates the row within 200 ms", () => {
  it("an arrival just after a tick is on the screen within one tick and one frame (116 ms)", async () => {
    render(<Probe positions={store} />);
    start();
    await settle();
    positionsHandle()?.push(snap(snapshot));
    await settle(COMMIT_INTERVAL_MS + 16);
    expect(screen.getByText("Main BTCUSDT mark 64012")).toBeInTheDocument();
    // the worst phase: the event lands right after a tick drained the handle
    positionsHandle()?.push(delta(update));
    await settle(COMMIT_INTERVAL_MS - 1);
    expect(screen.queryByText("Main BTCUSDT mark 64112")).toBeNull();
    await settle(16 + 1);
    expect(screen.getByText("Main BTCUSDT mark 64112")).toBeInTheDocument();
    expect(COMMIT_INTERVAL_MS + 16).toBeLessThan(200);
  });
});

describe("S-02: the snapshot budget and Retry", () => {
  it("no snapshot within 5 s fails; Retry re-subscribes and a snapshot loads", async () => {
    start();
    await settle(SNAPSHOT_BUDGET_MS - 100);
    expect(store.getSnapshot().status).not.toBe("snapshot_failed");
    await settle(200);
    expect(store.getSnapshot().status).toBe("snapshot_failed");
    const old = positionsHandle();
    feed?.retry();
    await settle(COMMIT_INTERVAL_MS + 16);
    expect(old?.released).toBe(true);
    expect(store.getSnapshot().status).toBe("loading");
    positionsHandle()?.push(snap(snapshot));
    await settle(COMMIT_INTERVAL_MS + 16);
    expect(store.getSnapshot().status).toBe("live");
  });

  it("a snapshot inside the budget disarms it", async () => {
    start();
    await settle();
    positionsHandle()?.push(snap(snapshot));
    await settle(SNAPSHOT_BUDGET_MS * 2);
    expect(store.getSnapshot().status).toBe("live");
  });

  it("a directory that cannot be read fails, and Retry reads it again", async () => {
    const outcomes: AccountsOutcome[] = [{ kind: "unavailable" }, { kind: "ok", items: accounts }];
    start(
      fakeApi({ listExchangeAccounts: async () => outcomes.shift() ?? { kind: "unavailable" } }),
    );
    await settle(COMMIT_INTERVAL_MS + 16);
    expect(store.getSnapshot().status).toBe("snapshot_failed");
    expect(ws.handles).toEqual([]);
    feed?.retry();
    await settle(COMMIT_INTERVAL_MS + 16);
    expect(ws.live("positions")).toHaveLength(1);
  });
});

describe("the link-down fallback (BQ-18)", () => {
  it("one REST read per link-down episode, never a poll", async () => {
    const api = fakeApi();
    start(api);
    await settle();
    positionsHandle()?.push(snap(snapshot));
    await settle(COMMIT_INTERVAL_MS + 16);
    expect(api.calls.filter((c) => c === "positions")).toHaveLength(1); // first paint
    // the reducer's loss: an outage from the `up` link, then the attempts
    ws.setState({
      link: { kind: "reconnecting", attempt: 1, nextAttemptAtMs: 0 },
      outage: { sinceMs: 1, lastDataMs: null },
    });
    positionsHandle()?.push(reset("reconnect"));
    await settle(10_000);
    expect(api.calls.filter((c) => c === "positions")).toHaveLength(2);
    expect(store.getSnapshot()).toMatchObject({ status: "offline", source: "rest" });
    ws.setState({ link: { kind: "connecting" } }); // a reconnect attempt: still the same episode
    await settle(COMMIT_INTERVAL_MS + 16);
    expect(api.calls.filter((c) => c === "positions")).toHaveLength(2);
    ws.setState({ link: { kind: "up" }, outage: null });
    await settle(COMMIT_INTERVAL_MS + 16);
    ws.setState({ link: { kind: "offline", cause: "offline" } });
    await settle(COMMIT_INTERVAL_MS + 16);
    expect(api.calls.filter((c) => c === "positions")).toHaveLength(3);
  });
});

describe("a narrowing (23 §9.5) re-subscribes and names who left (SR-E29-11)", () => {
  it("the new sub_ok's effective list drops the withdrawn account with its F-02 line", async () => {
    const signals = createAccountSignals();
    start(fakeApi(), { signals });
    await settle();
    const first = positionsHandle();
    first?.setEffective({ exchange_account_ids: [MAIN, SUB1, SUB2] });
    first?.push(snap(snapshot));
    await settle(COMMIT_INTERVAL_MS + 16);
    first?.push(reset("narrowed"));
    await settle(COMMIT_INTERVAL_MS + 16);
    expect(first?.released).toBe(true);
    expect(store.getSnapshot().rows).toEqual([]);
    const second = positionsHandle();
    expect(second).not.toBe(first);
    second?.setEffective({ exchange_account_ids: [MAIN, SUB1] });
    second?.push(
      snap({ positions: snapshot.positions.filter((p) => p.exchange_account_id !== SUB2) }),
    );
    await settle(COMMIT_INTERVAL_MS + 16);
    expect(store.getSnapshot().withdrawn).toEqual([{ accountId: SUB2, label: "Sub-2" }]);
    expect(store.getSnapshot().rows).toHaveLength(3);
  });
});

describe("B20 frames reach the signals; stop releases everything", () => {
  it("the locked chip's state, then stop", async () => {
    const signals = createAccountSignals();
    const api = fakeApi();
    start(api, { signals });
    await settle();
    ws.live(lockoutChannel(SUB2))[0]?.push(
      snap({
        machine_kind: "risk_lockout",
        state: "locked",
        tags: ["trading_blocked"],
        degraded: false,
        machine_hash: "0".repeat(64),
        environment: "live",
        updated_at_ms: 1,
      }),
    );
    await settle(COMMIT_INTERVAL_MS + 16);
    expect(signals.getSnapshot().accounts.get(SUB2)?.lockout).toBe("locked");
    feed?.stop();
    feed?.stop();
    expect(ws.handles.every((h) => h.released)).toBe(true);
    expect(store.getSnapshot().status).toBe("idle");
    expect(signals.getSnapshot().accounts.size).toBe(0);
    const listener = vi.fn();
    store.subscribe(listener);
    await settle(1_000);
    expect(listener).not.toHaveBeenCalled();
    feed?.retry(); // a stopped feed does nothing
    expect(ws.handles.filter((h) => !h.released)).toEqual([]);
  });
});
