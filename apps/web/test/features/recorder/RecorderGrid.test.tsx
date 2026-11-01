/**
 * E16-S01, SCR-140's recorded-symbols grid (E16-D02 §1, §4–§6, §9.1, §10; E16-D06 §13 "A blocked Stop" and "The
 * Why? popover", KB-02, KB-04, KB-06, FM-01 to FM-06, T2-01, T2-02, SR-14; BQ-9, BQ-10) over a stubbed `apiFetch`
 * (no network, C-13.5). Presses are `fireEvent`s (user-event is no web dependency): a browser's Enter on a button
 * is its keydown, then its click; a held key's repeat is a keydown with `repeat: true`.
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
import { rowData, type GridSort, type RowContext } from "../../../src/features/recorder/grid";
import type { RecorderRow } from "../../../src/features/recorder/model";
import { RecorderGrid, type RecorderGridProps } from "../../../src/features/recorder/RecorderGrid";
import { CONTEXT, D02_ROWS, NOW, row } from "./gridFixtures";
import { problem } from "./fixtures";

const axe = createRequire(createRequire(import.meta.url).resolve("@axe-core/playwright"))(
  "axe-core",
) as { run: (el: Element, o?: object) => Promise<{ violations: { impact?: string | null }[] }> };

const CHART = "Recording stops 30 min after the last chart closes.";
const reply = (status: number, body?: unknown): Response =>
  new Response(body === undefined ? null : JSON.stringify(body), { status });
const sent = (n = 0) => {
  const [url, init] = apiFetch.mock.calls[n] ?? [];
  const body = typeof init?.body === "string" ? (JSON.parse(init.body) as unknown) : undefined;
  return {
    url,
    method: init?.method,
    body,
    idemp: new Headers(init?.headers).get("Idempotency-Key"),
  };
};
const button = (name: string | RegExp): HTMLButtonElement =>
  screen.getByRole("button", { name }) as HTMLButtonElement;
/** The stop confirmation's Stop recording, found in the dialog (a whole-page role query is slow). */
const confirmStop = (): HTMLElement =>
  within(screen.getByRole("alertdialog")).getByRole("button", { name: "Stop recording" });
/** Lets the stubbed fetch and React's updates settle. */
const settle = () => act(async () => void (await Promise.resolve()));
/** CMP-044's guard ignores a press in its first 400 ms (E30-D03 D3 (2)). */
const pastGuard = () => act(() => void vi.advanceTimersByTime(500));

interface HarnessProps extends Partial<Omit<RecorderGridProps, "rows">> {
  readonly rows?: readonly RecorderRow[];
}

function Harness({ rows = D02_ROWS, ...props }: HarnessProps): JSX.Element {
  const [filters, setFilters] = useState<readonly FilterBarFilter[]>([]);
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<GridSort | undefined>(undefined);
  return (
    <RecorderGrid
      rows={rows}
      context={CONTEXT}
      listed={new Map()}
      frameAtMs={NOW}
      filters={filters}
      onFiltersChange={setFilters}
      query={query}
      onQueryChange={setQuery}
      sort={sort}
      onSortChange={setSort}
      say={() => undefined}
      readBack={() => undefined}
      {...props}
    />
  );
}

let reported: unknown[] = [];
const onAnalytics = (event: Event): void => void reported.push((event as CustomEvent).detail);
beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date", "performance"], now: NOW });
  reported = [];
  window.addEventListener("cv:analytics", onAnalytics);
});
afterEach(() => {
  window.removeEventListener("cv:analytics", onAnalytics);
  apiFetch.mockReset();
  vi.useRealTimers();
});

describe("Feature: A blocked Stop (E16-D06 §13; T2-01, SR-14, FM-18)", () => {
  it("Scenario: named, aria-disabled, the lock leading, the reason its description; Enter sends nothing and says it once", () => {
    const say = vi.fn();
    const { container } = render(<Harness say={say} />);
    const stop = button("Not available Stop recording SOLUSDT");
    expect(stop).toHaveAttribute("aria-disabled", "true");
    expect(stop.disabled).toBe(false);
    expect(stop).toHaveAccessibleDescription(CHART);
    expect(stop.firstElementChild).toContainElement(
      within(stop).getByRole("img", { name: "Not available" }),
    );
    act(() => stop.focus());
    fireEvent.keyDown(stop, { key: "Enter" });
    fireEvent.click(stop);
    // A held Enter's repeats press nothing (G-T2.3): the atom swallows them.
    expect(fireEvent.keyDown(stop, { key: "Enter", repeat: true })).toBe(false);
    expect(stop).toHaveFocus();
    expect(say.mock.calls).toEqual([[CHART]]);
    expect(apiFetch).not.toHaveBeenCalled();
    // The page's one voice took it: the grid holds no live region of its own (the summary stays silent).
    expect(container.querySelectorAll("[aria-live], [role=status], [role=alert]")).toHaveLength(0);
    expect(reported).toEqual([]);
  });

  it("each refusal and reason picks its §8.5 sentence", () => {
    const rows = [
      row("AUSDT", { reason: "chart_open", stopBlockedReason: "chart_open" }),
      row("BUSDT", { stopBlockedReason: "chart_open" }),
      row("CUSDT", { reason: "position_open", stopBlockedReason: "position_open" }),
      row("DUSDT", { stopBlockedReason: "position_open" }),
    ];
    render(<Harness rows={rows} />);
    const reasons = ["A", "B", "C", "D"].map((s) =>
      button(`Not available Stop recording ${s}USDT`).getAttribute("aria-describedby"),
    );
    expect(reasons.map((id) => document.getElementById(id ?? "")?.textContent)).toEqual([
      CHART,
      "Stop is available once the last chart closes.",
      "Recording continues while a position is open.",
      "Stop is unavailable while a position is open.",
    ]);
  });
});

describe("Feature: The Why? popover (E16-D06 §13; KB-04, FM-05, FM-06, F-03)", () => {
  it("Scenario: it opens on Keep recording, read by role; Esc returns focus to Why?", () => {
    render(<Harness />);
    const why = button("Why is SOLUSDT recorded?");
    act(() => why.focus());
    fireEvent.click(why);
    const popover = screen.getByRole("dialog", { name: "Recorded automatically" });
    expect(popover).toHaveTextContent(
      "SOLUSDT's chart has been open since 10:13 UTC; recording started 60 s later, at 10:14.",
    );
    expect(button("Keep recording SOLUSDT")).toHaveFocus();
    fireEvent.keyDown(document.activeElement ?? document.body, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(why).toHaveFocus();
    expect(reported).toEqual([{ name: "recorder.auto_review_opened", source: "why" }]);
  });

  it("Scenario: Keep recording adds the symbol with its own settings and returns focus to Why?", async () => {
    const onWritten = vi.fn();
    apiFetch.mockResolvedValueOnce(
      reply(200, { id: "id-solusdt", symbol: "SOLUSDT", reason: "manual", state: "recording" }),
    );
    render(<Harness onWritten={onWritten} />);
    const why = button("Why is SOLUSDT recorded?");
    fireEvent.click(why);
    fireEvent.click(button("Keep recording SOLUSDT"));
    await settle();
    expect(why).toHaveFocus();
    expect(sent()).toMatchObject({
      url: "/api/v1/recording/symbols",
      method: "POST",
      body: {
        symbol: "SOLUSDT",
        streams: ["trades", "orderbook_delta", "tickers", "liquidations"],
        depth: 50,
        pinned: false,
        retention_days: 30,
      },
    });
    expect(onWritten).toHaveBeenCalledWith({
      kind: "added",
      row: expect.objectContaining({ symbol: "SOLUSDT", reason: "manual" }),
    });
  });
});

describe("Stop and its confirmation (D02 §6.2, §6.3; KB-06, FM-04)", () => {
  it("opens on Keep recording, the default; the body names the grace and the retention", () => {
    render(<Harness />);
    fireEvent.click(button("Stop recording ETHUSDT"));
    const dialog = screen.getByRole("alertdialog", { name: "Stop recording ETHUSDT?" });
    expect(within(dialog).getByRole("button", { name: "Keep recording" })).toHaveFocus();
    expect(dialog).toHaveTextContent(
      "ETHUSDT keeps recording for 30 min, then stops, unless a chart, a position, a rule or an alert needs it.",
    );
    expect(dialog).toHaveTextContent("(30 days; forever when pinned)");
  });

  it("Keep recording closes it, sends nothing and returns focus to Stop", () => {
    render(<Harness />);
    const stop = button("Stop recording ETHUSDT");
    act(() => stop.focus());
    fireEvent.click(stop);
    const dialog = screen.getByRole("alertdialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Keep recording" }));
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(stop).toHaveFocus();
    expect(apiFetch).not.toHaveBeenCalled();
  });

  it("Stop recording sends one DELETE by the row's id, closes, returns focus and reports the stop", async () => {
    const onWritten = vi.fn();
    apiFetch.mockResolvedValueOnce(reply(204));
    render(<Harness onWritten={onWritten} />);
    const stop = button("Stop recording ETHUSDT");
    act(() => stop.focus());
    fireEvent.click(stop);
    pastGuard();
    fireEvent.click(confirmStop());
    await settle();
    expect(apiFetch).toHaveBeenCalledTimes(1);
    expect(sent()).toMatchObject({ url: "/api/v1/recording/symbols/id-ethusdt", method: "DELETE" });
    expect(sent().idemp).toMatch(/^[0-9a-f-]{36}$/);
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(stop).toHaveFocus();
    expect(reported).toEqual([
      { name: "recorder.symbol_stopped", symbol: "ETHUSDT", reason: "manual" },
    ]);
    expect(onWritten).toHaveBeenCalledWith({ kind: "stopped", symbol: "ETHUSDT" });
  });

  it("a 409 shows the T4 at the confirm, loading until the next frame, then T2 with the row's reason", async () => {
    apiFetch.mockResolvedValueOnce(reply(409, problem(409, "conflict")));
    const { rerender } = render(<Harness />);
    fireEvent.click(button("Stop recording ETHUSDT"));
    pastGuard();
    fireEvent.click(confirmStop());
    await settle();
    const dialog = screen.getByRole("alertdialog");
    expect(dialog).toHaveTextContent("Not stopped: the server refused it. (conflict)");
    expect(dialog).not.toHaveTextContent("server detail, never rendered");
    expect(within(dialog).getByRole("button", { name: /Stop recording/ })).toHaveAttribute(
      "aria-busy",
      "true",
    );
    // The next frame names the row's chart: the confirm turns T2 with §8.5's reason, and nothing is sent again.
    const blocked = D02_ROWS.map((r) =>
      r.symbol === "ETHUSDT" ? { ...r, stopBlockedReason: "chart_open" as const } : r,
    );
    rerender(<Harness rows={blocked} frameAtMs={NOW + 1_000} />);
    await settle();
    const confirm = within(screen.getByRole("alertdialog")).getByRole("button", {
      name: /Stop recording/,
    });
    expect(confirm).toHaveAttribute("aria-disabled", "true");
    expect(confirm).toHaveAccessibleDescription("Stop is available once the last chart closes.");
    expect(apiFetch).toHaveBeenCalledTimes(1);
  });

  it("a 409 and then a stale page return the confirm to T1", async () => {
    apiFetch.mockResolvedValueOnce(reply(409, problem(409, "conflict")));
    const { rerender } = render(<Harness />);
    fireEvent.click(button("Stop recording ETHUSDT"));
    pastGuard();
    fireEvent.click(confirmStop());
    await settle();
    rerender(<Harness context={{ ...CONTEXT, stale: true }} />);
    await settle();
    const confirm = within(screen.getByRole("alertdialog")).getByRole("button", {
      name: /Stop recording/,
    });
    expect(confirm).not.toHaveAttribute("aria-busy");
    expect(confirm).not.toHaveAttribute("aria-disabled");
  });

  it("a row the list has not caught up with is looked up by symbol before its stop", async () => {
    apiFetch
      .mockResolvedValueOnce(
        reply(200, {
          items: [{ id: "e1-new", symbol: "NEWUSDT", reason: "chart_open", state: "recording" }],
          meta: { count: 1, has_more: false },
        }),
      )
      .mockResolvedValueOnce(reply(204));
    render(<Harness rows={[row("NEWUSDT", { id: null })]} />);
    fireEvent.click(button("Stop recording NEWUSDT"));
    pastGuard();
    fireEvent.click(confirmStop());
    await settle();
    await settle();
    // The whole list, page by page (C-5309-10 (a)): `22`'s largest page first.
    expect(sent(0)).toMatchObject({ url: "/api/v1/recording/symbols?limit=500", method: "GET" });
    expect(sent(1)).toMatchObject({ url: "/api/v1/recording/symbols/e1-new", method: "DELETE" });
  });
});

describe("Keep recording and Record again (D02 §4.1)", () => {
  const lingering = row("DOGEUSDT", {
    reason: "chart_open",
    state: "lingering",
    lingerUntilMs: NOW + 24 * 60_000,
    retentionDays: 90,
  });

  it("a lingering row's Keep recording adds it at once with its own settings", async () => {
    apiFetch.mockResolvedValueOnce(
      reply(200, { id: "id-dogeusdt", symbol: "DOGEUSDT", reason: "manual", state: "recording" }),
    );
    render(
      <Harness
        rows={[lingering]}
        listed={
          new Map([
            [
              "DOGEUSDT",
              {
                id: "id-dogeusdt",
                symbol: "DOGEUSDT",
                reason: "chart_open",
                state: "recording",
                streams: ["trades"],
              },
            ],
          ])
        }
      />,
    );
    expect(screen.getByText("Recording · stops in 24 min")).toBeInTheDocument();
    fireEvent.click(button("Keep recording DOGEUSDT"));
    await settle();
    expect(sent()).toMatchObject({
      method: "POST",
      body: {
        symbol: "DOGEUSDT",
        streams: ["trades"],
        depth: 200,
        pinned: false,
        retention_days: 90,
      },
    });
  });

  it("Record again adds a stopped row; at the limit it is T2 and sends nothing (T2-02)", async () => {
    const say = vi.fn();
    apiFetch.mockResolvedValueOnce(
      reply(200, { id: "id-adausdt", symbol: "ADAUSDT", reason: "manual", state: "starting" }),
    );
    const { rerender } = render(<Harness say={say} />);
    fireEvent.click(button("Record ADAUSDT again"));
    await settle();
    expect(sent()).toMatchObject({ method: "POST", body: { symbol: "ADAUSDT" } });
    const capped = D02_ROWS.map((r) =>
      r.symbol === "ADAUSDT" ? { ...r, recordAgainBlockedReason: "symbol_cap" as const } : r,
    );
    rerender(<Harness say={say} rows={capped} />);
    const again = button("Not available Record ADAUSDT again");
    expect(again).toHaveAccessibleDescription("The symbol limit is reached.");
    fireEvent.click(again);
    expect(say.mock.calls).toEqual([["The symbol limit is reached."]]);
    expect(apiFetch).toHaveBeenCalledTimes(1);
  });

  it("Keep recording is busy while its add is in flight; a second press sends nothing (C-5309-13)", async () => {
    let answer: (response: Response) => void = () => undefined;
    apiFetch.mockImplementationOnce(() => new Promise<Response>((resolve) => (answer = resolve)));
    render(<Harness rows={[lingering]} />);
    const keep = button("Keep recording DOGEUSDT");
    fireEvent.click(keep);
    await settle();
    expect(keep).toHaveAttribute("aria-busy", "true");
    fireEvent.click(keep);
    expect(apiFetch).toHaveBeenCalledTimes(1);
    answer(reply(200, { id: "id-dogeusdt", symbol: "DOGEUSDT", reason: "manual" }));
    await settle();
    await settle();
    expect(keep).not.toHaveAttribute("aria-busy");
  });

  it("a refused re-add shows its words at the point of action and says them once", async () => {
    const say = vi.fn();
    apiFetch.mockResolvedValueOnce(reply(422, problem(422, "validation_failed")));
    render(<Harness say={say} rows={[lingering]} />);
    const keep = button("Keep recording DOGEUSDT");
    act(() => keep.focus());
    fireEvent.click(keep);
    await settle();
    const words = "Not started: the server refused it. (validation_failed)";
    expect(say.mock.calls).toEqual([[words]]);
    expect(document.querySelector(".cv-table__echo:not([hidden])")).toHaveTextContent(words);
  });
});

describe("Sort, filters and search (BQ-10; D02 §9.1; KB-02, FM-01, FM-02)", () => {
  const order = (): string[] =>
    screen.getAllByRole("rowheader").map((cell) => cell.textContent ?? "");

  it("is the grid Recorded symbols; rows read as D02H table 3; Symbol, Since and Size sort", () => {
    render(<Harness />);
    const grid = screen.getByRole("grid", { name: "Recorded symbols" });
    expect(
      within(grid).getByRole("row", {
        name: "BTCUSDT, manual, recording since 1 Sep 2026, 34.8 GB, keep forever on",
      }),
    ).toBeInTheDocument();
    const sortable = within(grid)
      .getAllByRole("columnheader")
      .filter((th) => th.hasAttribute("aria-sort"))
      .map((th) => th.textContent);
    expect(sortable).toEqual(["Symbol", "Since", "Size"]);
  });

  it("a sort orders the rows once; new values never re-sort or move focus (FM-01)", () => {
    const { rerender } = render(<Harness />);
    fireEvent.click(button("Size"));
    fireEvent.click(button("Size"));
    expect(order()).toEqual(["BTCUSDT", "ETHUSDT", "ADAUSDT", "XRPUSDT", "SOLUSDT"]);
    const stop = button("Stop recording ETHUSDT");
    act(() => stop.focus());
    const grown = D02_ROWS.map((r) => (r.symbol === "SOLUSDT" ? { ...r, diskBytes: 90e9 } : r));
    rerender(<Harness rows={grown} />);
    expect(order()).toEqual(["BTCUSDT", "ETHUSDT", "ADAUSDT", "XRPUSDT", "SOLUSDT"]);
    expect(stop).toHaveFocus();
    expect(button("Stop recording ETHUSDT")).toBe(stop);
  });

  it("a row that joins comes last; a focused row that leaves hands focus to the next (FM-02)", () => {
    const { rerender } = render(<Harness />);
    const btc = screen.getAllByRole("rowheader")[0] as HTMLElement;
    act(() => btc.focus());
    rerender(<Harness rows={[...D02_ROWS.slice(1), row("AAVEUSDT")]} />);
    expect(order()).toEqual(["ETHUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "AAVEUSDT"]);
    expect(screen.getAllByRole("rowheader")[0]).toHaveFocus();
  });

  it("the Reason: Auto chip shows the auto rows; the bar's sentence goes to the page's voice", () => {
    const say = vi.fn();
    render(
      <Harness
        say={say}
        filters={[{ field: "reason", value: "auto" }]}
        onFiltersChange={vi.fn()}
      />,
    );
    expect(order()).toEqual(["SOLUSDT", "XRPUSDT"]);
    expect(screen.getByRole("group", { name: "Active filters" })).toHaveTextContent("Reason: Auto");
  });

  it("Add filter's menu applies a value; the bar's sentence and the count are one line (D-5309-02)", async () => {
    const say = vi.fn();
    render(<Harness say={say} />);
    fireEvent.click(button("Add filter"));
    fireEvent.click(screen.getByRole("menuitem", { name: "Pinned" }));
    fireEvent.click(screen.getByRole("menuitemcheckbox", { name: "Yes" }));
    await settle();
    expect(order()).toEqual(["BTCUSDT"]);
    // Merged, so the count can never overwrite the bar's sentence in the shell's one polite region.
    expect(say.mock.calls).toEqual([["Filter added: Pinned: Yes. 1 of 5 symbols."]]);
  });

  it("a settled query says the count once, and only when the rows it shows changed (D-5309-02)", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "Date", "performance"], now: NOW });
    const say = vi.fn();
    render(<Harness say={say} />);
    const search = screen.getByRole("searchbox", { name: "Filter symbols" });
    for (const value of ["e", "et", "eth"]) fireEvent.change(search, { target: { value } });
    await act(async () => void (await vi.advanceTimersByTimeAsync(499)));
    expect(say).not.toHaveBeenCalled(); // never per keystroke
    await act(async () => void (await vi.advanceTimersByTimeAsync(1)));
    expect(say.mock.calls).toEqual([["1 of 5 symbols."]]);
    fireEvent.change(search, { target: { value: "ethusdt" } }); // the same row
    await act(async () => void (await vi.advanceTimersByTimeAsync(500)));
    expect(say).toHaveBeenCalledTimes(1);
    fireEvent.change(search, { target: { value: "zzz" } });
    await act(async () => void (await vi.advanceTimersByTimeAsync(500)));
    // None shown: the deck's filter class, as its `empty.announce.enter` says it ("{heading} {cause}").
    expect(say.mock.calls.at(-1)).toEqual([
      "No symbols match these filters. Widen or clear a filter to see symbols.",
    ]);
  });

  it("rows that arrive after the grid mounted are what its first search is counted against (C-5309-d01)", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "Date", "performance"], now: NOW });
    const say = vi.fn();
    const { rerender } = render(<Harness say={say} rows={[]} loading />); // the first reads are in flight
    rerender(<Harness say={say} rows={D02_ROWS} />); // ... and then the rows are there
    say.mockClear(); // the table's own line for its rows is not the count
    const search = screen.getByRole("searchbox", { name: "Filter symbols" });
    fireEvent.change(search, { target: { value: "usdt" } }); // every row: nothing changed from what was shown
    await act(async () => void (await vi.advanceTimersByTimeAsync(500)));
    expect(say).not.toHaveBeenCalled();
    fireEvent.change(search, { target: { value: "zzz" } }); // none: five rows became none
    await act(async () => void (await vi.advanceTimersByTimeAsync(500)));
    expect(say.mock.calls).toEqual([
      ["No symbols match these filters. Widen or clear a filter to see symbols."],
    ]);
  });

  it("a search is judged against the rows as they are now, not as they were when it was last counted (C-5309-d01)", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "Date", "performance"], now: NOW });
    const say = vi.fn();
    const { rerender } = render(<Harness say={say} />);
    const search = screen.getByRole("searchbox", { name: "Filter symbols" });
    fireEvent.change(search, { target: { value: "eth" } });
    await act(async () => void (await vi.advanceTimersByTimeAsync(500)));
    expect(say.mock.calls).toEqual([["1 of 5 symbols."]]);
    // A row the search matches joins: "eth" shows two now, though nobody was told. Narrowing it to one says so.
    rerender(<Harness say={say} rows={[...D02_ROWS, row("ETHFIUSDT")]} />);
    say.mockClear(); // (the table's own line, if it speaks the joined row)
    fireEvent.change(search, { target: { value: "ethusdt" } });
    await act(async () => void (await vi.advanceTimersByTimeAsync(500)));
    expect(say.mock.calls).toEqual([["1 of 6 symbols."]]);
  });

  it("nothing matching shows filtered-empty; Clear filters clears the query and the chips (C-5309-06)", () => {
    render(<Harness />);
    const search = screen.getByRole("searchbox", { name: "Filter symbols" });
    fireEvent.change(search, { target: { value: "zzz" } });
    expect(screen.getByRole("heading", { name: "No symbols match these filters" })).toBeVisible();
    expect(screen.getByText("Widen or clear a filter to see symbols.")).toBeVisible();
    act(() => button("Clear filters").focus());
    fireEvent.click(button("Clear filters"));
    expect(search).toHaveValue("");
    expect(order()).toHaveLength(5);
    expect(search).toHaveFocus(); // never <body>: the button went with the empty state
  });

  it("the search box filters by symbol", () => {
    render(<Harness />);
    fireEvent.change(screen.getByRole("searchbox", { name: "Filter symbols" }), {
      target: { value: "eth" },
    });
    expect(order()).toEqual(["ETHUSDT"]);
  });

  it("loading draws skeleton rows with aria-busy", () => {
    render(<Harness rows={[]} loading />);
    expect(screen.getByRole("grid", { name: /Recorded symbols/ })).toHaveAttribute(
      "aria-busy",
      "true",
    );
  });

  it("has no serious axe violation", { timeout: 20_000 }, async () => {
    const { container } = render(<Harness />);
    vi.useRealTimers();
    const res = await axe.run(container, { rules: { "color-contrast": { enabled: false } } });
    const serious = res.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
    expect(serious).toEqual([]);
  });
});

describe("the column plan follows the grid's width (D02 §1; D-5309-03)", () => {
  /** A ResizeObserver the test fires: the grid and CMP-049 each measure with one. */
  class FakeObserver {
    readonly targets: Element[] = [];
    disconnected = false;
    constructor(readonly callback: ResizeObserverCallback) {
      observers.push(this);
    }
    observe(target: Element): void {
      this.targets.push(target);
    }
    unobserve(): void {}
    disconnect(): void {
      this.disconnected = true;
    }
  }
  const observers: FakeObserver[] = [];
  beforeEach(() => {
    observers.length = 0;
    vi.stubGlobal("ResizeObserver", FakeObserver);
    const real = window.getComputedStyle.bind(window);
    vi.spyOn(window, "getComputedStyle").mockImplementation((el, pseudo) =>
      el instanceof HTMLElement &&
      (el.dataset["cmp"] === "CMP-049" || el.dataset["cvPlan"] !== undefined)
        ? ({ fontSize: "16px" } as CSSStyleDeclaration)
        : real(el, pseudo),
    );
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });
  /** Every live observer sees `width` px; twice, so one a re-render opened measures it too, as a browser's does. */
  const resize = async (width: number): Promise<void> => {
    for (let round = 0; round < 2; round += 1) {
      await act(async () => {
        for (const observer of observers.filter((o) => !o.disconnected)) {
          const entries = observer.targets.map(
            (target) => ({ target, contentRect: { width } }) as unknown as ResizeObserverEntry,
          );
          observer.callback(entries, observer as unknown as ResizeObserver);
        }
      });
    }
  };
  const headers = (): (string | null)[] =>
    screen.getAllByRole("columnheader").map((h) => h.textContent);
  const layout = (): string | null | undefined =>
    document.querySelector('[data-cmp="CMP-049"]')?.getAttribute("data-layout");

  it("all nine at 1152 px, the narrow seven at 992, all nine stacked into cards below that", async () => {
    render(<Harness />);
    await resize(1152);
    expect(headers()).toContain("Since");
    expect(layout()).toBeNull();
    await resize(992);
    expect(headers()).not.toContain("Since");
    expect(headers()).not.toContain("Depth");
    expect(layout()).toBeNull();
    expect(screen.getByRole("row", { name: /^ETHUSDT/ })).not.toHaveTextContent("2026-09-04");
    await resize(900);
    expect(headers()).toContain("Since"); // the cards drop no field (D02 §1)
    expect(layout()).toBe("stacked");
  });
});

it("a time past Date's range reads as none, never a RangeError (C-5309-13)", () => {
  const far = row("FARUSDT", { lastEventAtMs: 9e15, lingerUntilMs: 9e15, state: "lingering" });
  expect(rowData(far, { ...CONTEXT, stoppedAtMs: new Map([["FARUSDT", 9e15]]) })).toMatchObject({
    lastEventAt: null,
    lingerUntil: null,
    stoppedAt: null,
  });
});

it("the cells read the context they are given (stale rows keep their words)", () => {
  const stale: RowContext = { ...CONTEXT, stale: true };
  render(<Harness context={stale} />);
  expect(screen.getAllByText("stale")).toHaveLength(5);
});
