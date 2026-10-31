/**
 * E29-S01 (#911) integration: the store, the feed and the real `positionsApi` behind a fake `fetch`
 * and fake topic handles (BQ-19: no MSW, no new dependency), read through the hooks a panel uses.
 * Three accounts, grouping (account, trade group), filter and clear, the empty state, a failed
 * snapshot and Retry, the Viewer, the locked chip, and the client half of manager scope (BQ-13:
 * the server refuses a filter naming an account outside the grants, audited; its tests are E29-T07's).
 */
import { act, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { generated } from "@candleviewer/protocol";
import {
  accountLine,
  createAccountSignals,
  useAccountSignals,
  type AccountSignalsStore,
} from "../../../src/features/positions/accountSignals";
import { positionsApi } from "../../../src/features/positions/api";
import { bindDeck, permissionLines } from "../../../src/features/positions/copy";
import { buildPositionsView } from "../../../src/features/positions/model/view";
import {
  getPanelState,
  resetPanelState,
  updateChips,
  updatePanelState,
  usePanelState,
} from "../../../src/features/positions/panelState";
import {
  createPositionsStore,
  usePositions,
  type PositionsStore,
} from "../../../src/features/positions/positionsStore";
import {
  COMMIT_INTERVAL_MS,
  lockoutChannel,
  SNAPSHOT_BUDGET_MS,
  startPositionsFeed,
  type PositionsFeed,
} from "../../../src/features/positions/wsPositions";
import {
  fakeClient,
  fakeRaf,
  golden,
  MAIN,
  snap,
  SUB1,
  SUB2,
  type FakeClient,
} from "./support/fakes";

type Positions = generated.ws.Positions;
const TICK = COMMIT_INTERVAL_MS + 16;

/** `fetch` as the server answers each read: the goldens, and the audited 403 for an account out of scope. */
function fakeFetch(scope: readonly string[] = [MAIN, SUB1, SUB2]) {
  const accounts = golden<{ items: { id: string }[]; meta: unknown }>(
    "rest_list_exchange_accounts.json",
  );
  const positions = golden<{ items: { exchange_account_id: string }[] }>(
    "rest_list_positions.json",
  );
  return vi.fn(async (input: RequestInfo | URL): Promise<Response> => {
    const url = new URL(String(input), "http://localhost");
    const json = (status: number, body: unknown): Response =>
      new Response(JSON.stringify(body), {
        status,
        headers: { "Content-Type": "application/json" },
      });
    if (url.pathname === "/api/v1/exchange-accounts") {
      const items = accounts.items.filter((a) => scope.includes(a.id));
      return json(200, {
        items,
        meta: { next_cursor: null, has_more: false, count: items.length },
      });
    }
    if (url.pathname === "/api/v1/positions") {
      const named = url.searchParams.getAll("exchange_account_ids");
      if (named.some((id) => !scope.includes(id))) {
        return json(403, {
          type: "https://candleviewer.local/errors/account_scope_denied",
          title: "x",
          status: 403,
          code: "account_scope_denied",
        });
      }
      const wanted = named.length > 0 ? named : scope;
      return json(200, {
        items: positions.items.filter((p) => wanted.includes(p.exchange_account_id)),
        aggregates: [],
      });
    }
    return json(404, {});
  });
}

const realised = (): null => null;

/** A test-only reader of the model, through the hooks a panel uses (PR 3 and PR 4 build the screen). */
function Panel({
  store,
  signals,
  role,
}: {
  store: PositionsStore;
  signals: AccountSignalsStore;
  role: "owner" | "viewer";
}) {
  const rows = usePositions(store, (s) => s.rows);
  const status = usePositions(store, (s) => s.status);
  const groupBy = usePanelState("groupBy");
  const chips = usePanelState("chips");
  const accounts = useAccountSignals(signals, (s) => s.accounts);
  const view = buildPositionsView({
    rows,
    chips,
    groupBy,
    sort: null,
    environment: "live",
    realisedToday: realised,
  });
  return (
    <section aria-label="Positions">
      <p role="status">{status}</p>
      {view.empty && <p>{bindDeck("blotter.ui.empty")}</p>}
      {view.filterEmpty && (
        <p>{bindDeck("blotter.ui.filter_empty", { "2": String(chips.length) })}</p>
      )}
      {view.groups.map((group) => {
        const signal =
          group.by === "account" && group.key !== null ? accounts.get(group.key) : undefined;
        return (
          <table key={group.key ?? "none"} aria-label={`group ${group.key ?? "none"}`}>
            <caption>{`${group.count} · uPnL ${group.unrealisedPnl ?? "—"} · net ${group.netSize ?? "—"}`}</caption>
            {signal?.lockout === "locked" && (
              <p>{bindDeck("blotter.ui.lockout_chip", { "00:00": "00:00" })}</p>
            )}
            {signal !== undefined && accountLine(signal, role) !== null && (
              <p>{accountLine(signal, role)?.line}</p>
            )}
            <tbody>
              {group.rows.map((r) => (
                <tr key={r.key}>
                  <th scope="row">{r.symbol}</th>
                  <td>{r.accountLabel}</td>
                  <td>{r.sideLabel}</td>
                </tr>
              ))}
            </tbody>
          </table>
        );
      })}
      <p>{`TOTAL ${view.totals.count} · uPnL ${view.totals.unrealisedPnl ?? "—"}`}</p>
    </section>
  );
}

let ws: FakeClient;
let store: PositionsStore;
let signals: AccountSignalsStore;
let feed: PositionsFeed | undefined;

async function settle(ms = 0): Promise<void> {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

async function open(role: "owner" | "viewer" = "owner", scope?: readonly string[]): Promise<void> {
  vi.stubGlobal("fetch", fakeFetch(scope));
  render(<Panel store={store} signals={signals} role={role} />);
  feed = startPositionsFeed({
    client: ws.client,
    store,
    signals,
    api: positionsApi,
    ...fakeRaf,
    now: () => Date.now(),
    performance: null,
  });
  await settle(TICK);
}

const groupNames = (): string[] =>
  screen.queryAllByRole("table").map((t) => t.getAttribute("aria-label") ?? "");

beforeEach(() => {
  vi.useFakeTimers();
  ws = fakeClient();
  store = createPositionsStore();
  signals = createAccountSignals();
  resetPanelState();
});
afterEach(() => {
  feed?.stop();
  feed = undefined;
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("Rows render the whole book: three accounts", () => {
  it("REST paints first, the WS snapshot replaces it, grouped by account with a TOTAL row", async () => {
    await open();
    expect(screen.getByRole("status")).toHaveTextContent("loading");
    expect(groupNames()).toEqual([`group ${MAIN}`, `group ${SUB1}`, `group ${SUB2}`]);
    ws.live("positions")[0]?.push(snap(golden("ws_positions_snapshot.json")));
    await settle(TICK);
    expect(screen.getByRole("status")).toHaveTextContent("live");
    const sub1 = screen.getByRole("table", { name: `group ${SUB1}` });
    expect(
      within(sub1)
        .getAllByRole("rowheader")
        .map((c) => c.textContent),
    ).toEqual(["BTCUSDT", "ETHUSDT"]);
    expect(within(sub1).getByText("2 · uPnL -118.8 · net —")).toBeInTheDocument();
    expect(
      within(screen.getByRole("table", { name: `group ${SUB2}` })).getAllByText("Long · hedge"),
    ).toHaveLength(2);
    expect(screen.getByText("TOTAL 5 · uPnL -205.84")).toBeInTheDocument();
  });
});

describe("Grouping by trade group", () => {
  it("group rows aggregate size and PnL and expand to per-account rows", async () => {
    await open();
    ws.live("positions")[0]?.push(snap(golden("ws_positions_contract_fields.json")));
    act(() => updatePanelState({ groupBy: "trade_group" }));
    await settle(TICK);
    const group = screen.getByRole("table", { name: "group 0c000000-0000-4000-8000-000000000001" });
    expect(within(group).getByText("2 · uPnL 10.7 · net 0.35")).toBeInTheDocument();
    expect(
      within(group)
        .getAllByRole("cell")
        .map((c) => c.textContent),
    ).toEqual(["Main", "Long", "Sub-1", "Long"]);
    expect(groupNames().at(-1)).toBe("group none");
  });
});

describe("filter and clear", () => {
  it("an Account chip narrows the view; Clear all restores it; a chip naming nothing is filter-empty", async () => {
    await open();
    ws.live("positions")[0]?.push(snap(golden("ws_positions_snapshot.json")));
    await settle(TICK);
    act(() => updateChips({ type: "add", chip: { kind: "account", value: SUB1 } }));
    expect(groupNames()).toEqual([`group ${SUB1}`]);
    expect(screen.getByText("TOTAL 2 · uPnL -118.8")).toBeInTheDocument();
    act(() => updateChips({ type: "add", chip: { kind: "symbol", value: "SOLUSDT" } }));
    expect(screen.getByText("No rows match 2 filters")).toBeInTheDocument();
    act(() => updateChips({ type: "clear" }));
    expect(groupNames()).toHaveLength(3);
    expect(getPanelState().chips).toEqual([]);
  });
});

describe("Empty state", () => {
  it("no open positions: the explicit empty state, and no error", async () => {
    await open();
    ws.live("positions")[0]?.push(snap({ positions: [] } satisfies Positions));
    await settle(TICK);
    expect(screen.getByText("No open positions")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("live");
    expect(screen.queryByRole("alert")).toBeNull();
  });
});

describe("a failed snapshot (S-02)", () => {
  it("no snapshot within the 5 s budget reads snapshot_failed; Retry loads it", async () => {
    await open();
    await settle(SNAPSHOT_BUDGET_MS);
    expect(screen.getByRole("status")).toHaveTextContent("snapshot_failed");
    act(() => feed?.retry());
    ws.live("positions")[0]?.push(snap(golden("ws_positions_snapshot.json")));
    await settle(TICK);
    expect(screen.getByRole("status")).toHaveTextContent("live");
  });
});

describe("the Viewer", () => {
  it("reads the same rows the server serves, under one notice of its two permission lines", async () => {
    await open("viewer");
    ws.live("positions")[0]?.push(snap(golden("ws_positions_snapshot.json")));
    await settle(TICK);
    expect(screen.getAllByRole("rowheader")).toHaveLength(5);
    expect(permissionLines(["positions:read", "orders:read"])).toEqual([
      "Your role can't change positions.",
      "Your role can't place orders.",
    ]);
    expect(permissionLines(["positions:write", "orders:write"])).toEqual([]);
  });
});

describe("the locked chip (B20, S-21)", () => {
  it("a locked risk lockout puts the chip on its account's group", async () => {
    await open();
    ws.live("positions")[0]?.push(snap(golden("ws_positions_snapshot.json")));
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
    await settle(TICK);
    const chip = "Locked · daily loss limit · until 00:00 UTC · closing and reducing still work";
    expect(
      within(screen.getByRole("table", { name: `group ${SUB2}` })).getByText(chip),
    ).toBeInTheDocument();
    expect(screen.getAllByText(chip)).toHaveLength(1);
  });

  it("an account notice shows its line on the group (BQ-14)", async () => {
    await open();
    ws.live("positions")[0]?.push(snap(golden("ws_positions_snapshot.json")));
    await settle(TICK);
    act(() => signals.applyNotice(golden("ws_system_account_notice.json"), 1));
    expect(
      within(screen.getByRole("table", { name: `group ${SUB1}` })).getByText(
        "acct.reconciling.line",
      ),
    ).toBeInTheDocument();
  });
});

describe("Manager scope is enforced server-side (the client half; BQ-13)", () => {
  it("a manager granted only B reads B's rows; a crafted filter naming A is refused, audited, with no rows", async () => {
    await open("owner", [SUB2]);
    expect(ws.live("positions")[0]?.spec.opts).toEqual({ exchange_account_ids: [SUB2] });
    expect(groupNames()).toEqual([`group ${SUB2}`]);
    expect(await positionsApi.listPositions({ accountIds: [MAIN] })).toEqual({
      kind: "account_scope_denied",
    });
  });
});
