/**
 * E16-S01 PR 3, SCR-140's row detail (E16-D02 §4.1, §6.3, §6.7; E16-D06 KB-03, FM-07, RG-09, T2-01, T2-02, SR-14)
 * through the grid that hosts it, over a stubbed `apiFetch` (no network, C-13.5). Presses are `fireEvent`s: a
 * browser's click on a focused control, Esc as the layer stack hears it.
 */
import { createRequire } from "node:module";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { useState, type JSX } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { apiFetch } = vi.hoisted(() => ({
  apiFetch: vi.fn<(url: string, init?: RequestInit) => Promise<Response>>(),
}));
vi.mock("../../../src/lib/http/csrfFetch", () => ({ apiFetch }));

import type { FilterBarFilter } from "@candleviewer/ui";
import type { GridSort } from "../../../src/features/recorder/grid";
import type {
  RecordedSymbol,
  RecorderFrame,
  RecorderRow,
} from "../../../src/features/recorder/model";
import {
  RecorderGrid,
  type GridWrite,
  type RecorderGridProps,
} from "../../../src/features/recorder/RecorderGrid";
import type { Gap } from "../../../src/features/recorder/useRecorderData";
import { problem, stepUpRequired } from "./fixtures";
import { CONTEXT, D02_ROWS, NOW, row } from "./gridFixtures";
import { POLICY } from "./modelFixtures";

const axe = createRequire(createRequire(import.meta.url).resolve("@axe-core/playwright"))(
  "axe-core",
) as { run: (el: Element, o?: object) => Promise<{ violations: { impact?: string | null }[] }> };

const CHART = "Recording stops 30 min after the last chart closes.";
const reply = (status: number, body?: unknown): Response =>
  new Response(body === undefined ? null : JSON.stringify(body), { status });
const sent = (n = 0) => {
  const [url, init] = apiFetch.mock.calls[n] ?? [];
  const body = typeof init?.body === "string" ? (JSON.parse(init.body) as unknown) : undefined;
  return { url, method: init?.method, body };
};
const settle = () => act(async () => void (await Promise.resolve()));
/** CMP-044's guard ignores a press in its first 400 ms (E30-D03 D3 (2)). */
const pastGuard = () => act(() => void vi.advanceTimersByTime(500));
/** A press as a browser makes it: focus, then the click. */
const press = (control: HTMLElement): void => {
  act(() => control.focus());
  fireEvent.click(control);
};
const escape = (): void =>
  void fireEvent.keyDown(document.activeElement ?? document.body, { key: "Escape" });
/** A first mount transforms the screen's whole module graph: slow under load, never a flake (C-9.3). */
const CASE = { timeout: 30_000 } as const;
const drawer = (symbol: string): HTMLElement =>
  screen.getByRole("dialog", { name: `${symbol} recording` });

/** The newest frame: BTCUSDT's health (D02 §6.7) and an incident on it. */
const FRAME: RecorderFrame = {
  overall: "healthy",
  policy: POLICY,
  symbols: [
    {
      symbol: "BTCUSDT",
      state: "recording",
      reason: "manual",
      pinned: true,
      lag_ms: 42,
      rows_last_hour: 41_220_118,
      resyncs_last_hour: 1,
      dropped_messages: 1204,
      disk_bytes: 34.8e9,
      last_event_at_ms: NOW - 1_000,
    },
  ],
};
const GAPS: readonly Gap[] = [
  {
    symbol: "BTCUSDT",
    fromMs: Date.parse("2026-09-14T10:14:03Z"),
    toMs: Date.parse("2026-09-14T10:14:41Z"),
    reason: "seq_jump",
  },
  {
    symbol: "ETHUSDT",
    fromMs: Date.parse("2026-09-14T08:00:00Z"),
    toMs: Date.parse("2026-09-14T08:01:00Z"),
    reason: null,
  },
];
const LISTED: ReadonlyMap<string, RecordedSymbol> = new Map([
  [
    "BTCUSDT",
    {
      id: "id-btcusdt",
      symbol: "BTCUSDT",
      reason: "manual",
      state: "recording",
      streams: ["trades", "orderbook_delta", "tickers", "liquidations"],
    },
  ],
]);

interface HarnessProps extends Partial<Omit<RecorderGridProps, "rows">> {
  readonly rows?: readonly RecorderRow[];
}

function Harness({ rows = D02_ROWS, ...props }: HarnessProps): JSX.Element {
  const [filters, setFilters] = useState<readonly FilterBarFilter[]>([]);
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<GridSort | undefined>(undefined);
  const [detail, setDetail] = useState<string | null>(null);
  return (
    <RecorderGrid
      rows={rows}
      context={{ ...CONTEXT, gaps: new Map([["BTCUSDT", 1]]) }}
      listed={LISTED}
      frameAtMs={NOW}
      filters={filters}
      onFiltersChange={setFilters}
      query={query}
      onQueryChange={setQuery}
      sort={sort}
      onSortChange={setSort}
      say={() => undefined}
      readBack={() => undefined}
      onOpenDetail={setDetail}
      detail={detail}
      onDetailClose={() => setDetail(null)}
      frame={FRAME}
      status={null}
      gaps={GAPS}
      {...props}
    />
  );
}

/** Opens a row's detail as a user does: a press on its symbol. */
function openDetail(symbol: string): HTMLElement {
  const opener = screen.getByRole("button", { name: symbol });
  press(opener);
  return opener;
}

// jsdom lays nothing out: CMP-009 scrolls its active option into view.
const scroll = Element.prototype.scrollIntoView;
beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date", "performance", "setTimeout", "clearTimeout"], now: NOW });
  Element.prototype.scrollIntoView = vi.fn();
});
afterEach(() => {
  Element.prototype.scrollIntoView = scroll;
  apiFetch.mockReset();
  vi.useRealTimers();
});

describe("Feature: The row detail (E16-D02 §6.7; KB-03, FM-07, RG-09)", CASE, () => {
  it("opens from the row's symbol as a modal dialog named for it, on its heading; Esc returns focus to the row", () => {
    render(<Harness />);
    const opener = openDetail("BTCUSDT");
    const dialog = drawer("BTCUSDT");
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(
      within(dialog).getByRole("heading", { level: 2, name: "BTCUSDT recording" }),
    ).toHaveFocus();
    escape();
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(opener).toHaveFocus();
    expect(apiFetch).not.toHaveBeenCalled();
  });

  it("reads Status, Health, Cost and the row's gaps of the last 24 h from the newest frame", () => {
    render(<Harness />);
    openDetail("BTCUSDT");
    const dialog = drawer("BTCUSDT");
    for (const name of ["Status", "Health", "Cost", "Gaps (last 24 h)"]) {
      expect(within(dialog).getByRole("heading", { level: 3, name })).toBeInTheDocument();
    }
    const value = (label: string): string =>
      within(dialog).getByText(label, { selector: "dt" }).nextElementSibling?.textContent ?? "";
    expect(value("State")).toBe("Recording · 1 gap in 24 h");
    expect(value("Reason")).toBe("Manual");
    expect(value("Started")).toBe("2026-09-01 09:00 UTC");
    expect(value("Streams")).toBe("Trades, Order-book deltas, Tickers, Liquidations");
    expect(value("Lag")).toBe("42 ms");
    expect(value("Rows in the last hour")).toBe("41 220 118");
    expect(value("Resyncs in the last hour")).toBe("1");
    expect(value("Last write")).toBe("10:31:01 UTC");
    expect(value("Dropped messages")).toBe("1 204 messages dropped (incident)");
    expect(value("Size")).toBe("34.8 GB");
    expect(value("Rate (7-day trend)")).toBe("0.71 GB a day");
    expect(within(dialog).getByRole("meter", { name: "Share of budget" })).toHaveAttribute(
      "aria-valuetext",
      "17 % of budget",
    );
    const gaps = within(dialog).getByRole("table", { name: "Gaps (last 24 h)" });
    expect(within(gaps).getAllByRole("row")).toHaveLength(2); // the header and BTCUSDT's one gap
    expect(gaps).toHaveTextContent("10:14:03");
    expect(gaps).not.toHaveTextContent("08:00:00");
    // The Owner's controls: Depth, Retention and Keep forever, then the action and Purge… (KB-03).
    expect(within(dialog).getByRole("combobox", { name: "Depth" })).toHaveTextContent("200");
    expect(within(dialog).getByRole("combobox", { name: "Retention" })).toHaveTextContent(
      "Forever",
    );
    expect(within(dialog).getByRole("switch", { name: "Keep BTCUSDT data forever" })).toBeChecked();
    expect(within(dialog).getByRole("button", { name: "Stop recording BTCUSDT" })).toBeEnabled();
  });

  it("a blocked Stop carries its reason inline (2a): Enter sends nothing and says it once", () => {
    const say = vi.fn();
    render(<Harness say={say} />);
    openDetail("SOLUSDT");
    const dialog = drawer("SOLUSDT");
    const stop = within(dialog).getByRole("button", {
      name: "Not available Stop recording SOLUSDT",
    });
    expect(stop).toHaveAttribute("aria-disabled", "true");
    expect(stop).toHaveAccessibleDescription(CHART);
    expect(within(dialog).getByText(CHART)).toBeVisible();
    press(stop);
    expect(stop).toHaveFocus();
    expect(say.mock.calls).toEqual([[CHART]]);
    expect(apiFetch).not.toHaveBeenCalled();
  });

  it("Stop opens its confirmation over the drawer; Keep recording returns focus to Stop, the drawer still open", () => {
    render(<Harness />);
    openDetail("ETHUSDT");
    const stop = within(drawer("ETHUSDT")).getByRole("button", { name: "Stop recording ETHUSDT" });
    press(stop);
    const confirm = screen.getByRole("alertdialog", { name: "Stop recording ETHUSDT?" });
    press(within(confirm).getByRole("button", { name: "Keep recording" }));
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(stop).toHaveFocus();
    expect(drawer("ETHUSDT")).toBeInTheDocument();
    expect(apiFetch).not.toHaveBeenCalled();
  });

  it("Depth sends updateRecordedSymbol with the depth alone and merges the answer", async () => {
    const written: GridWrite[] = [];
    apiFetch.mockResolvedValueOnce(
      reply(200, {
        id: "id-btcusdt",
        symbol: "BTCUSDT",
        reason: "manual",
        state: "recording",
        depth: 50,
      }),
    );
    render(<Harness onWritten={(write) => written.push(write)} />);
    openDetail("BTCUSDT");
    const depth = within(drawer("BTCUSDT")).getByRole("combobox", { name: "Depth" });
    fireEvent.click(depth);
    fireEvent.click(screen.getByRole("option", { name: "50" }));
    await settle();
    expect(sent()).toMatchObject({
      url: "/api/v1/recording/symbols/id-btcusdt",
      method: "PATCH",
      body: { depth: 50 },
    });
    expect(written).toEqual([{ kind: "updated", row: expect.objectContaining({ depth: 50 }) }]);
  });

  it("a refused depth shows under the select with its code, never the problem's words", async () => {
    apiFetch.mockResolvedValueOnce(
      reply(
        422,
        problem(422, "validation_failed", {
          errors: [{ field: "depth", message: "server message" }],
        }),
      ),
    );
    render(<Harness />);
    openDetail("BTCUSDT");
    const dialog = drawer("BTCUSDT");
    const depth = within(dialog).getByRole("combobox", { name: "Depth" });
    fireEvent.click(depth);
    fireEvent.click(screen.getByRole("option", { name: "500" }));
    await settle();
    await settle();
    expect(depth).toHaveAccessibleDescription(
      expect.stringContaining("Not changed: the server refused it. (validation_failed)"),
    );
    expect(depth).toHaveTextContent("200");
    expect(dialog).not.toHaveTextContent("server message");
  });

  it("a stopped row: its end, the retention's erosion and Record again", () => {
    render(
      <Harness
        context={{
          ...CONTEXT,
          stoppedAtMs: new Map([["ADAUSDT", Date.parse("2026-09-12T09:00:00Z")]]),
        }}
      />,
    );
    openDetail("ADAUSDT");
    const dialog = drawer("ADAUSDT");
    expect(dialog).toHaveTextContent(
      "Stopped 12 Sep · gone by 12 Oct · data erodes daily under the 30-day retention",
    );
    expect(within(dialog).getByRole("button", { name: "Record ADAUSDT again" })).toBeEnabled();
  });

  it("a refused entry has no control: Depth and Retention read a dash, no switch", () => {
    const refused = row("DOGEUSDT", {
      id: null,
      reason: "chart_open",
      state: "refused",
      refusal: "symbol_cap",
      depth: null,
      retentionDays: null,
    });
    render(<Harness rows={[...D02_ROWS, refused]} />);
    openDetail("DOGEUSDT");
    const dialog = drawer("DOGEUSDT");
    expect(within(dialog).queryByRole("combobox")).toBeNull();
    expect(within(dialog).queryByRole("switch")).toBeNull();
    expect(
      within(dialog).getByText("Depth", { selector: "dt" }).nextElementSibling,
    ).toHaveTextContent("—");
    expect(within(dialog).queryByRole("button", { name: /Stop|Record|Keep/ })).toBeNull();
  });

  it("has no serious axe violation, open", { timeout: 20_000 }, async () => {
    render(<Harness />);
    openDetail("BTCUSDT");
    vi.useRealTimers();
    const res = await axe.run(drawer("BTCUSDT"), {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(res.violations.filter((v) => v.impact === "serious" || v.impact === "critical")).toEqual(
      [],
    );
  });
});

it("past CMP-044's guard, the drawer's Stop sends the stop by the row's id", CASE, async () => {
  apiFetch.mockResolvedValueOnce(reply(204));
  render(<Harness />);
  openDetail("ETHUSDT");
  press(within(drawer("ETHUSDT")).getByRole("button", { name: "Stop recording ETHUSDT" }));
  pastGuard();
  press(within(screen.getByRole("alertdialog")).getByRole("button", { name: "Stop recording" }));
  await settle();
  expect(sent()).toMatchObject({ url: "/api/v1/recording/symbols/id-ethusdt", method: "DELETE" });
});

describe(
  "the row detail's focus and structure (A-5347-03, A-5347-06; C-5347-06, C-5347-08; FM-02, FM-07)",
  CASE,
  () => {
    /** The row's controls gone: the frame lists it untracked now (no id: an `idle` entry). */
    const untracked = (symbol: string): RecorderRow[] =>
      D02_ROWS.map((r) => (r.symbol === symbol ? { ...r, id: null } : r));

    it("closed after its row left, focus goes to the grid's next row, never body (FM-02, FM-07)", () => {
      const view = render(<Harness />);
      openDetail("ETHUSDT");
      expect(drawer("ETHUSDT")).toBeInTheDocument();
      view.rerender(<Harness rows={D02_ROWS.filter((r) => r.symbol !== "ETHUSDT")} />);
      escape();
      expect(screen.queryByRole("dialog")).toBeNull();
      const now = document.activeElement;
      expect(now).not.toBe(document.body);
      expect(now?.closest("table")).not.toBeNull();
    });

    it("the control that held focus goes with its row's controls: focus moves to the drawer's heading", () => {
      const view = render(<Harness />);
      openDetail("ETHUSDT");
      const depth = within(drawer("ETHUSDT")).getByRole("combobox", { name: "Depth" });
      act(() => depth.focus());
      view.rerender(<Harness rows={untracked("ETHUSDT")} />);
      expect(within(drawer("ETHUSDT")).queryByRole("combobox", { name: "Depth" })).toBeNull();
      expect(
        within(drawer("ETHUSDT")).getByRole("heading", { level: 2, name: "ETHUSDT recording" }),
      ).toHaveFocus();
    });

    it("no gaps: one plain line, no heading of its own; no region landmarks inside the dialog", () => {
      render(<Harness />);
      openDetail("SOLUSDT");
      const dialog = drawer("SOLUSDT");
      expect(within(dialog).getByText("No gaps in the last 24 h.")).toBeVisible();
      expect(within(dialog).queryByRole("heading", { name: "No rows to show" })).toBeNull();
      // The drawer's title and its four section headings, nothing else.
      expect(within(dialog).getAllByRole("heading")).toHaveLength(5);
      expect(within(dialog).queryAllByRole("region")).toEqual([]);
    });

    it("a gap on an earlier UTC day carries its date, as the page's gap table does", () => {
      const yesterday: Gap = {
        symbol: "BTCUSDT",
        fromMs: Date.parse("2026-09-13T23:10:00Z"),
        toMs: Date.parse("2026-09-13T23:12:30Z"),
        reason: "ws_disconnect",
      };
      render(<Harness gaps={[...GAPS, yesterday]} />);
      openDetail("BTCUSDT");
      const gaps = within(drawer("BTCUSDT")).getByRole("table", { name: "Gaps (last 24 h)" });
      expect(gaps).toHaveTextContent("2026-09-13 23:10:00");
      expect(gaps).toHaveTextContent("10:14:03");
      expect(gaps).not.toHaveTextContent("2026-09-14 10:14:03");
    });

    it("a detail with no row to show is closed, never opened later by itself when the symbol arrives", () => {
      let open: (symbol: string) => void = () => undefined;
      function Opener(props: HarnessProps): JSX.Element {
        const [detail, setDetail] = useState<string | null>(null);
        open = setDetail;
        return <Harness {...props} detail={detail} onDetailClose={() => setDetail(null)} />;
      }
      const view = render(<Opener />);
      act(() => open("DOGEUSDT"));
      expect(screen.queryByRole("dialog")).toBeNull();
      view.rerender(<Opener rows={[...D02_ROWS, row("DOGEUSDT")]} />);
      expect(screen.queryByRole("dialog")).toBeNull();
    });

    it("a challenged depth write renews as itself: the new request is that depth, never an earlier action", async () => {
      apiFetch.mockResolvedValueOnce(reply(403, stepUpRequired));
      apiFetch.mockResolvedValue(
        reply(200, { id: "id-btcusdt", symbol: "BTCUSDT", reason: "manual", state: "recording" }),
      );
      render(<Harness />);
      openDetail("BTCUSDT");
      fireEvent.click(within(drawer("BTCUSDT")).getByRole("combobox", { name: "Depth" }));
      fireEvent.click(screen.getByRole("option", { name: "50" }));
      await settle();
      await settle();
      // `22` challenges no depth write today; were it to, its SCR-006 is the drawer's, live inside it (A-5347-d01).
      const challenge = screen.getByRole("alertdialog", { name: "Confirm with two-factor" });
      expect(drawer("BTCUSDT")).toContainElement(challenge);
      act(() => void vi.advanceTimersByTime(5 * 60_000)); // the challenge expires
      fireEvent.click(
        within(drawer("BTCUSDT")).getByRole("button", { name: "Request a new confirmation" }),
      );
      await settle();
      await settle();
      const patches = apiFetch.mock.calls.filter(([, init]) => init?.method === "PATCH");
      expect(patches).toHaveLength(2);
      expect(JSON.parse(String(patches[1]?.[1]?.body))).toEqual({ depth: 50 });
    });

    it("Record again challenged from the drawer: SCR-006 opens inside it on its Password, and the grant re-sends the first key (A-5347-d01)", async () => {
      // `22` challenges any add whose body names `pinned` or `retention_days`, as a re-add's does.
      const stopped = D02_ROWS.map((r) =>
        r.symbol === "BTCUSDT" ? { ...r, state: "stopped" as const } : r,
      );
      apiFetch
        .mockResolvedValueOnce(reply(403, stepUpRequired))
        .mockResolvedValueOnce(reply(200, { action_class: "recorder" }))
        .mockResolvedValueOnce(
          reply(200, {
            id: "id-btcusdt",
            symbol: "BTCUSDT",
            reason: "manual",
            state: "recording",
            pinned: true,
          }),
        );
      const written: GridWrite[] = [];
      render(<Harness rows={stopped} onWritten={(write) => written.push(write)} />);
      openDetail("BTCUSDT");
      const dialog = drawer("BTCUSDT");
      press(within(dialog).getByRole("button", { name: "Record BTCUSDT again" }));
      for (let i = 0; i < 3; i += 1) await settle();
      expect(sent(0)).toMatchObject({
        url: "/api/v1/recording/symbols",
        method: "POST",
        body: { symbol: "BTCUSDT", pinned: true, retention_days: null },
      });
      // Found by role with no `hidden`: live, inside the modal drawer, focus on its first field (E09-D06).
      const challenge = screen.getByRole("alertdialog", { name: "Confirm with two-factor" });
      expect(dialog).toContainElement(challenge);
      const password = within(challenge).getByLabelText("Password");
      expect(password).toHaveFocus();
      fireEvent.change(password, { target: { value: "pw" } });
      fireEvent.change(within(challenge).getByLabelText("Authenticator code"), {
        target: { value: "123456" },
      });
      fireEvent.click(within(challenge).getByRole("button", { name: "Confirm" }));
      for (let i = 0; i < 6; i += 1) await settle();
      const adds = apiFetch.mock.calls.filter(
        ([url, init]) => url === "/api/v1/recording/symbols" && init?.method === "POST",
      );
      const key = (n: number): string | null =>
        new Headers(adds[n]?.[1]?.headers).get("Idempotency-Key");
      expect(adds).toHaveLength(2);
      expect(key(1)).not.toBeNull();
      expect(key(1)).toBe(key(0));
      expect(written).toEqual([
        { kind: "added", row: expect.objectContaining({ symbol: "BTCUSDT" }) },
      ]);
      expect(drawer("BTCUSDT")).toBeInTheDocument();
    });

    it("the drawer's Record again is busy while its add is on the wire: a second press sends nothing (A-5347-d04)", async () => {
      let release: (response: Response) => void = () => undefined;
      apiFetch.mockImplementationOnce(
        () =>
          new Promise<Response>((resolve) => {
            release = resolve;
          }),
      );
      render(<Harness />);
      openDetail("ADAUSDT");
      const again = within(drawer("ADAUSDT")).getByRole("button", {
        name: "Record ADAUSDT again",
      });
      expect(again).not.toHaveAttribute("aria-busy");
      press(again);
      await settle();
      expect(again).toHaveAttribute("aria-busy", "true");
      press(again);
      await settle();
      expect(apiFetch).toHaveBeenCalledTimes(1);
      release(
        reply(200, { id: "id-adausdt", symbol: "ADAUSDT", reason: "manual", state: "recording" }),
      );
      await settle();
      await settle();
      expect(again).not.toHaveAttribute("aria-busy");
    });

    it("a one-day retention reads as one day in the Retention select (C-5347-d06)", () => {
      render(
        <Harness
          rows={D02_ROWS.map((r) => (r.symbol === "ETHUSDT" ? { ...r, retentionDays: 1 } : r))}
        />,
      );
      openDetail("ETHUSDT");
      const retention = within(drawer("ETHUSDT")).getByRole("combobox", { name: "Retention" });
      expect(retention).toHaveTextContent(/^1 day$/);
      fireEvent.click(retention);
      expect(screen.getByRole("option", { name: "7 days" })).toBeInTheDocument();
    });

    it("Purge… is offered only for a symbol the purge dialog can name", () => {
      const refused = row("DOGEUSDT", {
        id: null,
        reason: "chart_open",
        state: "refused",
        refusal: "symbol_cap",
        depth: null,
        retentionDays: null,
        diskBytes: null,
      });
      const purge = { busy: false, open: vi.fn(), symbols: ["BTCUSDT"] };
      render(<Harness rows={[...D02_ROWS, refused]} purge={purge} />);
      openDetail("DOGEUSDT");
      expect(within(drawer("DOGEUSDT")).queryByRole("button", { name: "Purge…" })).toBeNull();
      escape();
      openDetail("BTCUSDT");
      expect(within(drawer("BTCUSDT")).getByRole("button", { name: "Purge…" })).toBeInTheDocument();
    });
  },
);
