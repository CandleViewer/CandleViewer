/**
 * E42-S08 (#1137) §5.1: the statechart inspector's page at R-357 `/admin/statecharts` (BQ-1 as
 * ruled; E42-D05 §11 SI-1, SI-2). CMP-088's `h1` and its "as of" line, the kind counters, the
 * rowless lines, the latch banner, "Latched only", the machine grid and the machine view as the
 * query's state; every state of §5.1's table; the tab order, the focus moves and the page's polite
 * lines through the shell's announcer; no timer (BQ-7). Reads go through the real read layer and a
 * store of the test's own, against a stubbed `fetch` (no network, C-13.5).
 */
import { createRequire } from "node:module";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { JSX } from "react";
import { MemoryRouter, Route, Routes, useLocation, useNavigate } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { GatedAnnounceProvider } from "@candleviewer/ui";
import { clearAnnouncements, ShellAnnouncer } from "../../../../src/features/app-shell/announcer";
import { InShellProvider } from "../../../../src/features/app-shell/ScreenRoot";
import type { ReadTimers } from "../../../../src/features/admin/overview/adminReads";
import {
  EMPTY_SURFACE,
  INSPECTOR_SCREEN,
  InspectorPage,
  RENDER_MEASURE,
} from "../../../../src/features/admin/statecharts/InspectorPage";
import {
  readDetail,
  readExport,
  readList,
} from "../../../../src/features/admin/statecharts/inspectorReads";
import {
  createInspectorStore,
  inspector,
  type InspectorStore,
} from "../../../../src/features/admin/statecharts/inspectorStore";
import { ROUTE_MANIFEST } from "../../../../src/routes/manifest";
import { ROUTE_TITLES } from "../../../../src/routes/titles";
import { THEME_ANALYTICS_EVENT } from "../../../../src/shell/bootstrap/themeStore";
import {
  KILL_SWITCH_HASH,
  LATCHED_DETAIL,
  LATCHED_KEY,
  LATCHED_ROW,
  ORDER_EXPORT,
  ORDER_HASH,
  shortHash,
  WORLD_LATCHED_LIST,
  WORLD_LIST,
} from "./fixtures";

// axe-core is a transitive dependency of @axe-core/playwright (as in AdminArea.test.tsx).
const axe = createRequire(createRequire(import.meta.url).resolve("@axe-core/playwright"))(
  "axe-core",
) as { run: (el: Element, o?: object) => Promise<{ violations: { impact?: string | null }[] }> };

const LIST = "/api/v1/admin/statecharts?limit=200";
const LATCHED_LIST = "/api/v1/admin/statecharts?limit=200&degraded=true";
const DETAIL = `/api/v1/admin/statecharts/${encodeURIComponent(LATCHED_KEY)}?environment=demo`;
const EXPORT = "/api/v1/admin/statecharts/order/export";
const PAGE = "/admin/statecharts";
const OPEN = `${PAGE}?machine=${encodeURIComponent(LATCHED_KEY)}&env=demo`;
const NOW = Date.parse("2026-10-15T18:00:06Z");
const WAIT = { timeout: 5_000 } as const;

const TIMERS: ReadTimers = {
  setTimeout: (run, ms) => globalThis.setTimeout(run, ms),
  clearTimeout: (handle) => globalThis.clearTimeout(handle as ReturnType<typeof setTimeout>),
};

/** An answer, after `after` settles when it has one, or a request that never answers. */
type Reply =
  { readonly status?: number; readonly body: unknown; readonly after?: Promise<unknown> } | "hang";
interface Request {
  readonly path: string;
  readonly method: string;
  readonly signal: AbortSignal | undefined;
}

/** Answers each path with its reply (a `404` for any other), recording every request. */
function serve(replies: Readonly<Record<string, Reply>>): Request[] {
  const requests: Request[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
      const path = String(input);
      const signal = init.signal ?? undefined;
      requests.push({ path, method: (init.method ?? "GET").toUpperCase(), signal });
      const reply = replies[path] ?? { status: 404, body: { code: "not_found" } };
      if (reply === "hang") {
        return new Promise<Response>((_resolve, reject) => {
          signal?.addEventListener("abort", () =>
            reject(new DOMException("aborted", "AbortError")),
          );
        });
      }
      if (reply.after !== undefined) await reply.after;
      return new Response(JSON.stringify(reply.body), {
        status: reply.status ?? 200,
        headers: { "Content-Type": "application/json" },
      });
    }),
  );
  return requests;
}

/** A reply's gate: the request waits until the test opens it. */
function gate(): { readonly after: Promise<unknown>; readonly open: () => void } {
  let open = (): void => undefined;
  const after = new Promise<void>((resolve) => {
    open = resolve;
  });
  return { after, open };
}

const denials: (string | undefined)[] = [];
const storeFor = (): InspectorStore =>
  createInspectorStore({
    now: () => NOW,
    readList: (request, signal) => readList(request, signal, TIMERS),
    readDetail: (ref, signal) => readDetail(ref, signal, TIMERS),
    readExport: (kind, signal) => readExport(kind, signal, TIMERS),
    deny: (refId) => void denials.push(refId),
  });

/** The current location, for the test to read: `?machine=…&env=…` is the page's query state. */
let here = "";
/** The current entry's state and key: what the page keeps in history, and whether it navigated. */
let hereState: unknown = null;
let hereKey = "";
function Here(): null {
  const location = useLocation();
  here = `${location.pathname}${location.search}`;
  hereState = location.state;
  hereKey = location.key;
  return null;
}

/** The browser's Forward, as a control the test can press. */
function Forward(): JSX.Element {
  const navigate = useNavigate();
  return (
    <button type="button" onClick={() => void navigate(1)}>
      Forward
    </button>
  );
}

/** The page as the shell holds it, inside a router whose history starts at `entries`. */
function show(entries: readonly string[] = [PAGE], store: InspectorStore = storeFor()) {
  const view = render(
    <GatedAnnounceProvider announce={() => undefined}>
      <MemoryRouter initialEntries={[...entries]} initialIndex={entries.length - 1}>
        <InShellProvider>
          <main>
            <Routes>
              <Route path={PAGE} element={<InspectorPage store={store} />} />
              <Route path="/journal" element={<h1>Journal</h1>} />
            </Routes>
          </main>
        </InShellProvider>
        <Here />
        <Forward />
      </MemoryRouter>
      <ShellAnnouncer />
    </GatedAnnounceProvider>,
  );
  return { store, view };
}

const WORLD: Readonly<Record<string, Reply>> = {
  [LIST]: { body: WORLD_LIST },
  [LATCHED_LIST]: { body: WORLD_LATCHED_LIST },
  [DETAIL]: { body: LATCHED_DETAIL },
  [EXPORT]: { body: ORDER_EXPORT },
};
/** The page alone: the shell's announcer, outside it, repeats some of its lines. */
const page = () => within(screen.getByRole("main"));
const grid = (): HTMLElement => screen.getByRole("grid", { name: "Machines" });
const counters = (): HTMLElement => screen.getByRole("table", { name: "Machines by kind" });
/** The grid's body rows once the list answered. */
const machineRows = async (): Promise<HTMLElement[]> => {
  await waitFor(() => expect(grid().querySelectorAll("tr[data-machine-row]").length).toBe(2), WAIT);
  return [...grid().querySelectorAll<HTMLElement>("tr[data-machine-row]")];
};
/** What assistive technology reads: the text without its `aria-hidden` parts. */
function spoken(node: Element): string {
  const copy = node.cloneNode(true) as Element;
  copy.querySelectorAll('[aria-hidden="true"]').forEach((hidden) => hidden.remove());
  return (copy.textContent ?? "").replace(/\s+/g, " ").trim();
}
const cellsOf = (row: Element): string[] =>
  [...row.querySelectorAll("th, td")].map((cell) => spoken(cell));
const polite = (): HTMLElement | null =>
  document.querySelector<HTMLElement>('[aria-live="polite"] p');

/** Every line the shell's polite region is handed from now on, in order: what is heard. */
function hearPolite(): string[] {
  const heard: string[] = [];
  const region = document.querySelector('[aria-live="polite"]');
  if (region === null) throw new Error("no polite region");
  let last: string | undefined;
  new MutationObserver(() => {
    const line = region.querySelector<HTMLElement>("p");
    const seq = line?.dataset["seq"];
    if (line === null || seq === undefined || seq === last) return;
    last = seq;
    heard.push(line.textContent ?? "");
  }).observe(region, { childList: true, subtree: true, characterData: true });
  return heard;
}

const analytics: Record<string, unknown>[] = [];
const onAnalytics = (event: Event): void => {
  analytics.push((event as CustomEvent<Record<string, unknown>>).detail);
};

beforeEach(() => {
  denials.length = 0;
  analytics.length = 0;
  here = "";
  hereState = null;
  hereKey = "";
  clearAnnouncements();
  window.addEventListener(THEME_ANALYTICS_EVENT, onAnalytics);
});

afterEach(() => {
  window.removeEventListener(THEME_ANALYTICS_EVENT, onAnalytics);
  clearAnnouncements();
  inspector.reset();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  // A test's own `performance.measure`, whatever its assertions did (the prototype's is restored).
  Reflect.deleteProperty(performance, "measure");
});

describe("R-357: the route (BQ-1)", () => {
  it("test_route_r357_is_admin_statecharts_owner_only_and_hidden_as_404", () => {
    const entry = ROUTE_MANIFEST.find((e) => e.id === "R-357");
    expect(entry).toEqual({
      id: "R-357",
      path: "/admin/statecharts",
      access: { roles: ["owner"], denyAs: "404" },
      owner: null,
    });
    expect(ROUTE_TITLES["R-357"]).toBe("Statechart inspector");
  });
});

describe("the page frame (BQ-1)", () => {
  it("test_page_frame_has_the_one_h1_and_the_utc_line_while_loading", () => {
    const requests = serve({ [LIST]: "hang" });
    show();
    expect(screen.getByRole("heading", { level: 1 })).toHaveAccessibleName("Statechart inspector");
    expect(document.querySelectorAll('[data-cmp="CMP-088"]')).toHaveLength(1);
    expect(screen.getByText("All times UTC")).toBeInTheDocument();
    expect(counters()).toHaveAttribute("aria-busy", "true");
    expect(grid()).toHaveAttribute("aria-busy", "true");
    expect(requests.map((r) => r.path)).toEqual([LIST]);
  });

  it("test_page_screen_id_is_one_proposed_placeholder_never_a_held_slot", () => {
    serve({ [LIST]: "hang" });
    show();
    expect(INSPECTOR_SCREEN).toBe("SCR-PROPOSED");
    expect(document.querySelector(`[data-scr="${INSPECTOR_SCREEN}"]`)).not.toBeNull();
    expect(INSPECTOR_SCREEN).not.toMatch(/SCR-13[89]/);
  });
});

describe("SI-1: the list as served", { timeout: 30_000 }, () => {
  it("test_page_counters_read_each_kind_with_its_served_counts", async () => {
    serve(WORLD);
    show();
    await machineRows();
    const rows = within(counters()).getAllByRole("row").slice(1).map(cellsOf);
    expect(rows).toEqual([
      ["kill_switch (B18)", "DEMO", "1", "clear 1", "0", "0", "not received"],
      ["order (B1)", "DEMO", "1", "triggered 1", "2", "1", "not received"],
      ["position_protection (B8)", "DEMO", "1", "naked 1", "1", "1", "not received"],
    ]);
    // "— not received", never 0: the dash is drawn, the words are read (D02 D4; Q-24).
    const dropped = within(counters()).getAllByRole("row")[2]?.lastElementChild;
    expect(dropped?.textContent).toBe("— not received");
    expect(page().getByText("Metrics unavailable — metrics timed out after 300 ms")).toBeVisible();
    expect(page().getByText("All times UTC · as of 18:00:05")).toBeInTheDocument();
  });

  /** The world with the order's served dropped receipts count, and `metrics` as given. */
  const withDropped = (metrics: unknown) => ({
    ...WORLD,
    [LIST]: {
      body: {
        ...WORLD_LIST,
        kinds: WORLD_LIST.kinds.map((k, i) => (i === 1 ? { ...k, dropped_receipts: 4 } : k)),
        metrics,
      },
    },
  });

  it("test_page_counters_draw_a_served_dropped_receipts_count_as_its_number", async () => {
    // AC1's "dropped_receipts counts visible": the metrics source answered, so the count shows.
    serve(withDropped({ status: "ok", generated_at: "2026-10-15T18:00:05Z" }));
    show();
    await machineRows();
    const order = within(counters()).getAllByRole("row")[2] as HTMLElement;
    expect(cellsOf(order)).toEqual(["order (B1)", "DEMO", "1", "triggered 1", "2", "1", "4"]);
    expect(page().queryByText(/^Metrics unavailable/)).toBeNull();
  });

  it("test_page_counters_read_a_count_beside_a_metrics_slice_not_ok_as_not_received", async () => {
    // A count beside a failed metrics slice is not shown: "— not received", never the number.
    serve(withDropped(WORLD_LIST.metrics));
    show();
    await machineRows();
    const order = within(counters()).getAllByRole("row")[2] as HTMLElement;
    expect(order.lastElementChild?.textContent).toBe("— not received");
  });

  it("test_page_counters_kind_column_is_13em_wide_for_its_longest_label", async () => {
    // "position_protection (B8)" whole at 1280 (A-1137-08); the other columns share the rest.
    serve(WORLD);
    show();
    await machineRows();
    const widths = [...counters().querySelectorAll("col")].map((col) => col.style.width);
    expect(widths).toEqual(["13em", "", "", "", "", "", ""]);
  });

  it("test_page_counters_by_state_and_not_received_wrap_in_their_cells", async () => {
    // The counters are no grid, so a cut would have no echo: their words wrap (A-1137-d02, d05).
    serve(WORLD);
    show();
    await machineRows();
    const order = within(counters()).getAllByRole("row")[2] as HTMLElement;
    for (const words of ["triggered 1", "not received"]) {
      expect(within(order).getByText(words).style.whiteSpace, words).toBe("normal");
    }
    // Its headers wrap too, by the rule `inspector.css` scopes to this class.
    expect(counters().closest(".cv-inspector-counters")).not.toBeNull();
  });

  it("test_page_grid_reads_each_machine_as_served_the_latch_in_words_and_octagon", async () => {
    serve(WORLD);
    show();
    const [clear, latched] = await machineRows();
    expect(cellsOf(clear as HTMLElement)).toEqual([
      "kill_switch",
      "kill_switch (B18)",
      "DEMO",
      "clear",
      shortHash(KILL_SWITCH_HASH),
      "0",
      "",
      "0",
      "18:00:00 UTC",
    ]);
    expect(cellsOf(latched as HTMLElement)).toEqual([
      LATCHED_KEY,
      "order (B1)",
      "DEMO",
      "triggered",
      shortHash(ORDER_HASH),
      "2",
      "Latched — chain trips: 2",
      "2",
      "18:00:02 UTC",
    ]);
    // The octagon is a glyph beside the words, never the only signal; rows keep the served order.
    expect(latched?.querySelector('svg[aria-hidden="true"]')).not.toBeNull();
    expect(clear?.querySelector("svg")).toBeNull();
  });

  it("test_page_grid_reads_the_served_latch_never_chain_trips", async () => {
    // C-2.21: a row's latch is its served `degraded`, whatever its `chain_trips` says.
    const tripped = { ...WORLD_LIST.items[0], chain_trips: 3, degraded: false };
    const zero = { ...LATCHED_ROW, chain_trips: 0, degraded: true };
    serve({ ...WORLD, [LIST]: { body: { ...WORLD_LIST, items: [tripped, zero] } } });
    show();
    const [first, second] = await machineRows();
    expect(cellsOf(first as HTMLElement).slice(5, 7)).toEqual(["3", ""]);
    expect(first?.querySelector("svg")).toBeNull();
    expect(cellsOf(second as HTMLElement).slice(5, 7)).toEqual(["0", "Latched — chain trips: 0"]);
    expect(second?.querySelector('svg[aria-hidden="true"]')).not.toBeNull();
  });

  it("test_page_grid_cells_hold_their_content_in_one_node_beside_their_label", async () => {
    // A stacked card puts a cell's label and its content apart: two nodes would tear (A-1137-09).
    serve(WORLD);
    show();
    const [, latched] = await machineRows();
    for (const cell of (latched as HTMLElement).querySelectorAll("td")) {
      const content = [...cell.childNodes].filter(
        (node) => !(node instanceof HTMLElement && node.classList.contains("cv-table__cell-label")),
      );
      expect(
        content.map((node) => node.nodeName),
        cell.textContent ?? "",
      ).toEqual(["SPAN"]);
    }
  });

  it("test_page_grid_state_cell_wraps_a_long_served_name", async () => {
    // "engaged_incomplete" runs past its column at 1280: the name wraps in its cell (A-1137-d02).
    serve(WORLD);
    show();
    const [, latched] = await machineRows();
    expect(within(latched as HTMLElement).getByText("triggered").style.whiteSpace).toBe("normal");
  });

  it("test_page_grid_shows_that_enter_opens_a_machine_and_describes_its_rows_with_it", async () => {
    // The cue is visible to a sighted keyboard user, and still each row header's description.
    serve(WORLD);
    show();
    const [, latched] = await machineRows();
    const hint = page().getByText("Enter opens a machine.");
    expect(hint.closest(".cv-visually-hidden")).toBeNull();
    expect(hint.compareDocumentPosition(grid()) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(latched?.querySelector("th")).toHaveAccessibleDescription("Enter opens a machine.");
  });

  it("test_page_rowless_kind_is_a_line_never_a_row", async () => {
    serve(WORLD);
    show();
    const rows = await machineRows();
    const line = page().getByText(
      "position_protection (B8) · DEMO: 1 latched — this kind has no public id yet, so it can't be opened or acknowledged here",
    );
    expect(line.querySelector('svg[aria-hidden="true"]')).not.toBeNull();
    expect(rows.some((row) => row.textContent?.includes("position_protection"))).toBe(false);
  });

  it("test_page_latch_banner_is_a_static_danger_callout", async () => {
    serve(WORLD);
    show();
    await machineRows();
    const banner = page()
      .getByText("A latched machine refuses order-path commands until its latch is acknowledged.")
      .closest('[data-cmp="CMP-028"]');
    expect(banner).toHaveAttribute("data-tone", "danger");
    expect(banner?.querySelector('[role="alert"], [role="status"], [aria-live]')).toBeNull();
  });

  it("test_page_a_null_deferred_depth_reads_not_recorded", async () => {
    const items = [{ ...WORLD_LIST.items[0], deferred_depth: null }, WORLD_LIST.items[1]];
    serve({ ...WORLD, [LIST]: { body: { ...WORLD_LIST, items } } });
    show();
    const [clear] = await machineRows();
    const deferred = clear?.querySelectorAll("td")[6];
    expect(deferred?.textContent).toBe("—not recorded");
    expect(spoken(deferred as Element)).toBe("not recorded");
  });

  it("test_page_more_rows_than_one_page_say_so", async () => {
    const meta = { next_cursor: "c1", has_more: true, count: 2 };
    serve({ ...WORLD, [LIST]: { body: { ...WORLD_LIST, meta } } });
    show();
    await machineRows();
    expect(
      page().getByText("Showing the first 200 machines. Turn on Latched only to narrow the list."),
    ).toBeVisible();
  });

  it("test_page_says_none_of_its_rows_and_owns_no_live_region", async () => {
    serve(WORLD);
    const { view } = show();
    const [, latched] = await machineRows();
    await act(async () => undefined);
    expect(polite()).toHaveTextContent(/^Metrics unavailable/); // its one SI-2 inset line
    const main = view.container.querySelector("main") as HTMLElement;
    const LIVE = "[aria-live], [role='status'], [role='alert']";
    expect(main.querySelector(LIVE)).toBeNull();
    // A machine open too: its timeline's table says nothing of its own (C-1137-03).
    fireEvent.keyDown(latched?.querySelector("th") as HTMLElement, { key: "Enter" });
    await screen.findByRole("table", { name: "Events, newest first" }, WAIT);
    expect(main.querySelector(LIVE)).toBeNull();
  });
});

describe("Latched only (CMP-004)", { timeout: 30_000 }, () => {
  it("test_page_latched_only_reads_degraded_true_as_a_switch", async () => {
    const requests = serve(WORLD);
    show();
    await machineRows();
    const toggle = screen.getByRole("switch", { name: "Latched only" });
    expect(toggle).toHaveAttribute("aria-checked", "false");
    fireEvent.click(toggle);
    await waitFor(
      () => expect(grid().querySelectorAll("tr[data-machine-row]")).toHaveLength(1),
      WAIT,
    );
    expect(screen.getByRole("switch", { name: "Latched only" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
    expect(requests.map((r) => r.path)).toEqual([LIST, LATCHED_LIST]);
  });

  it("test_page_latched_only_with_none_latched_says_so_once", async () => {
    // Metrics read, so no inset line is said first (a second line waits out the region's budget).
    const all = { ...WORLD_LIST, metrics: { status: "ok" } };
    const none = { ...all, items: [], meta: { next_cursor: null, has_more: false, count: 0 } };
    serve({ ...WORLD, [LIST]: { body: all }, [LATCHED_LIST]: { body: none } });
    show();
    await machineRows();
    fireEvent.click(screen.getByRole("switch", { name: "Latched only" }));
    expect(await page().findByText("No machine is latched.", {}, WAIT)).toBeVisible();
    await waitFor(() => expect(polite()).toHaveTextContent("No machine is latched."), WAIT);
  });

  it("test_page_latched_only_keeps_the_counters_while_its_rows_load_and_says_its_result_once", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const latchedRows = gate();
    serve({ ...WORLD, [LATCHED_LIST]: { after: latchedRows.after, body: WORLD_LATCHED_LIST } });
    show();
    const heard = hearPolite();
    await machineRows();
    await waitFor(() => expect(polite()).toHaveTextContent(/^Metrics unavailable/), WAIT);
    fireEvent.click(screen.getByRole("switch", { name: "Latched only" }));
    // While the latched rows are read: none of the other filter's, and the kinds, the banner and
    // "as of", the same on every filter, stay (A-1137-06).
    expect(grid()).toHaveAttribute("aria-busy", "true");
    expect(grid().querySelectorAll("tr[data-machine-row]")).toHaveLength(0);
    expect(counters()).not.toHaveAttribute("aria-busy");
    expect(within(counters()).getAllByRole("row")).toHaveLength(4);
    expect(
      page().getByText(
        "A latched machine refuses order-path commands until its latch is acknowledged.",
      ),
    ).toBeInTheDocument();
    expect(page().getByText("All times UTC · as of 18:00:05")).toBeInTheDocument();
    act(() => latchedRows.open());
    await waitFor(
      () => expect(grid().querySelectorAll("tr[data-machine-row]")).toHaveLength(1),
      WAIT,
    );
    await act(async () => void (await vi.advanceTimersByTimeAsync(6_000)));
    // One result for the filter, and the metrics line never again: its condition never ended.
    expect(heard).toEqual([
      "Metrics unavailable — metrics timed out after 300 ms",
      "1 latched machine listed.",
    ]);
    fireEvent.click(screen.getByRole("switch", { name: "Latched only" }));
    await waitFor(
      () => expect(grid().querySelectorAll("tr[data-machine-row]")).toHaveLength(2),
      WAIT,
    );
    await act(async () => void (await vi.advanceTimersByTimeAsync(6_000)));
    expect(heard.slice(2)).toEqual(["2 machines listed."]);
  });

  it("test_page_a_recovery_is_said_once_never_again_when_the_filter_changes", async () => {
    // The first read fails, Retry, then Latched only on and off (C-1137-d02, A-1137-d01).
    vi.useFakeTimers({ shouldAdvanceTime: true });
    serve({ [LIST]: { status: 503, body: { code: "unavailable" } } });
    show();
    const heard = hearPolite();
    /** One region budget and a little more: each line lands in its own render. */
    const step = (): Promise<void> =>
      act(async () => {
        await vi.advanceTimersByTimeAsync(5_100);
      });
    await waitFor(
      () => expect(polite()).toHaveTextContent("The machine list can't be read right now."),
      WAIT,
    );
    serve(WORLD);
    fireEvent.click(within(grid()).getByRole("button", { name: "Retry" }));
    await machineRows();
    await step();
    await step();
    expect(heard).toEqual([
      "The machine list can't be read right now.",
      "The machine list loaded.",
      "Metrics unavailable — metrics timed out after 300 ms",
    ]);
    const rows = (n: number) =>
      waitFor(() => expect(grid().querySelectorAll("tr[data-machine-row]")).toHaveLength(n), WAIT);
    fireEvent.click(screen.getByRole("switch", { name: "Latched only" }));
    await rows(1);
    await step();
    fireEvent.click(screen.getByRole("switch", { name: "Latched only" }));
    await rows(2);
    await step();
    await step();
    // Each filter's result once; the recovery never again.
    expect(heard.slice(3)).toEqual(["1 latched machine listed.", "2 machines listed."]);
  });

  it("test_page_a_filters_failed_first_page_keeps_the_counters_and_retries_its_rows", async () => {
    serve({ ...WORLD, [LATCHED_LIST]: { status: 503, body: { code: "unavailable" } } });
    show();
    await machineRows();
    fireEvent.click(screen.getByRole("switch", { name: "Latched only" }));
    const retry = await within(grid()).findByRole("button", { name: "Retry" }, WAIT);
    expect(grid().querySelectorAll("tr[data-machine-row]")).toHaveLength(0);
    expect(within(counters()).getAllByRole("row")).toHaveLength(4);
    serve(WORLD);
    fireEvent.click(retry);
    await waitFor(
      () => expect(grid().querySelectorAll("tr[data-machine-row]")).toHaveLength(1),
      WAIT,
    );
  });
});

describe("SI-2 and §5.1's other states", { timeout: 30_000 }, () => {
  it("test_page_unreadable_snapshots_read_machine_unreadable_once_with_no_tables", async () => {
    const body = {
      items: [],
      kinds: [],
      meta: { next_cursor: null, has_more: false, count: 0 },
      snapshots: { status: "unavailable", detail: "snapshots: no provider wired" },
      metrics: { status: "ok" },
    };
    serve({ [LIST]: { body } });
    show();
    expect(
      await page().findByText("Machine snapshots can't be read right now.", {}, WAIT),
    ).toBeVisible();
    expect(screen.queryByRole("grid")).toBeNull();
    expect(screen.queryByRole("table")).toBeNull();
    await waitFor(
      () => expect(polite()).toHaveTextContent("Machine snapshots can't be read right now."),
      WAIT,
    );
    expect(analytics).toEqual([
      { name: "empty_state_shown", surface: EMPTY_SURFACE, reason: "unreadable" },
    ]);
  });

  it("test_page_nothing_running_reads_machine_empty_once", async () => {
    const body = {
      items: [],
      kinds: [],
      meta: { next_cursor: null, has_more: false, count: 0 },
      snapshots: { status: "ok" },
      metrics: { status: "ok" },
    };
    serve({ [LIST]: { body } });
    show();
    expect(await page().findByText("No machine has a saved snapshot yet.", {}, WAIT)).toBeVisible();
    // Under the `h1` with no section of its own: an `h2`, no skipped level (A-1137-05).
    expect(
      page().getByRole("heading", { level: 2, name: "No machine has a saved snapshot yet." }),
    ).toBeInTheDocument();
    await waitFor(
      () => expect(polite()).toHaveTextContent("No machine has a saved snapshot yet."),
      WAIT,
    );
    expect(analytics).toEqual([
      { name: "empty_state_shown", surface: EMPTY_SURFACE, reason: "no_snapshots" },
    ]);
  });

  it("test_page_a_failed_seal_reads_its_line_above_the_rows_served", async () => {
    const snapshots = { status: "error", detail: "snapshot seal did not verify" };
    serve({ ...WORLD, [LIST]: { body: { ...WORLD_LIST, snapshots } } });
    show();
    await machineRows();
    const line = page().getByText("A snapshot's seal didn't verify, so its machine isn't listed.");
    expect(line.compareDocumentPosition(grid()) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("test_page_a_failed_first_read_offers_retry_then_draws_the_rows", async () => {
    const requests = serve({ [LIST]: { status: 503, body: { code: "unavailable" } } });
    show();
    expect(
      await page().findByText("The machine list can't be read right now.", {}, WAIT),
    ).toBeVisible();
    await waitFor(
      () => expect(polite()).toHaveTextContent("The machine list can't be read right now."),
      WAIT,
    );
    serve(WORLD);
    fireEvent.click(within(grid()).getByRole("button", { name: "Retry" }));
    expect(await machineRows()).toHaveLength(2);
    expect(requests.map((r) => r.path)).toEqual([LIST]);
  });

  it("test_page_a_failed_reread_keeps_the_rows_with_its_line", async () => {
    serve(WORLD);
    show();
    await machineRows();
    serve({ [LIST]: { status: 503, body: { code: "unavailable" } } });
    fireEvent.click(screen.getByRole("button", { name: "Re-read" }));
    expect(
      await page().findByText("The machine list can't be read right now.", {}, WAIT),
    ).toBeVisible();
    expect(await machineRows()).toHaveLength(2);
  });

  it.each([404, 501])("test_page_a_%i_list_reads_not_available_here", async (status) => {
    serve({ [LIST]: { status, body: { code: "x" } } });
    show();
    expect(
      await page().findByText("The machine list isn't available on this server.", {}, WAIT),
    ).toBeVisible();
    expect(
      page().getByRole("heading", {
        level: 2,
        name: "The machine list isn't available on this server.",
      }),
    ).toBeInTheDocument();
  });

  it("test_page_the_first_reads_retry_leaves_focus_on_its_heading_and_says_it_loaded", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    serve({ [LIST]: { status: 503, body: { code: "unavailable" } } });
    show();
    await waitFor(
      () => expect(polite()).toHaveTextContent("The machine list can't be read right now."),
      WAIT,
    );
    const retry = within(grid()).getByRole("button", { name: "Retry" });
    serve(WORLD);
    act(() => retry.focus());
    fireEvent.click(retry); // Enter on a native button
    await machineRows();
    // The Retry went with its read: focus waits on the section's heading (A-1137-02).
    expect(document.activeElement).not.toBe(document.body);
    expect(screen.getByRole("heading", { level: 2, name: "Machines" })).toHaveFocus();
    await act(async () => void (await vi.advanceTimersByTimeAsync(6_000)));
    expect(polite()).toHaveTextContent("The machine list loaded.");
  });

  it("test_page_a_failed_rereads_retry_leaves_focus_on_its_heading_and_says_it_loaded", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    serve(WORLD);
    show();
    await machineRows();
    serve({ [LIST]: { status: 503, body: { code: "unavailable" } } });
    fireEvent.click(screen.getByRole("button", { name: "Re-read" }));
    await page().findByText("The machine list can't be read right now.", {}, WAIT);
    const retry = page().getByRole("button", { name: "Retry" });
    serve(WORLD);
    act(() => retry.focus());
    fireEvent.click(retry);
    await waitFor(
      () => expect(page().queryByText("The machine list can't be read right now.")).toBeNull(),
      WAIT,
    );
    expect(document.activeElement).not.toBe(document.body);
    expect(screen.getByRole("heading", { level: 2, name: "Machines" })).toHaveFocus();
    await act(async () => void (await vi.advanceTimersByTimeAsync(6_000)));
    expect(polite()).toHaveTextContent("The machine list loaded.");
  });

  it("test_page_a_403_withdraws_the_area_and_asks_nothing_more", async () => {
    const requests = serve({ [LIST]: { status: 403, body: { instance: "urn:cv:req:7" } } });
    show();
    expect(
      await screen.findByRole("heading", { level: 1, name: "Your access changed" }, WAIT),
    ).toBeInTheDocument();
    expect(denials).toEqual(["urn:cv:req:7"]);
    expect(screen.queryByRole("grid")).toBeNull();
    expect(requests).toHaveLength(1);
  });

  it("test_page_no_timer_ten_minutes_pass_and_nothing_is_read", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const requests = serve(WORLD);
    show();
    await machineRows();
    await act(async () => void (await vi.advanceTimersByTimeAsync(10 * 60_000)));
    expect(requests.map((r) => r.path)).toEqual([LIST]);
  });

  it("test_page_measures_its_first_render_once", async () => {
    const measure = vi.fn();
    Object.defineProperty(performance, "measure", { value: measure, configurable: true });
    serve(WORLD);
    show();
    await machineRows();
    await waitFor(() => expect(measure).toHaveBeenCalledTimes(1), WAIT);
    expect(measure.mock.calls[0]?.[0]).toBe(RENDER_MEASURE);
    fireEvent.click(screen.getByRole("button", { name: "Re-read" }));
    await act(async () => undefined);
    expect(measure).toHaveBeenCalledTimes(1);
  });
});

describe("the machine view as the page's query state (§5.2)", { timeout: 30_000 }, () => {
  it("test_page_enter_on_a_row_opens_its_machine_and_focuses_its_heading", async () => {
    serve(WORLD);
    show();
    const [, latched] = await machineRows();
    const cell = latched?.querySelector<HTMLElement>("th") as HTMLElement;
    act(() => cell.focus());
    fireEvent.keyDown(cell, { key: "Enter" });
    const heading = await screen.findByRole(
      "heading",
      { level: 2, name: `${LATCHED_KEY} · DEMO` },
      WAIT,
    );
    expect(here).toBe(OPEN);
    await waitFor(() => expect(heading).toHaveFocus(), WAIT);
    expect(await screen.findByRole("heading", { name: "Transitions" }, WAIT)).toBeInTheDocument();
  });

  it("test_page_a_held_enter_opens_once_and_a_press_opens_too", async () => {
    serve(WORLD);
    show();
    const [clear, latched] = await machineRows();
    fireEvent.keyDown(latched?.querySelector("th") as HTMLElement, { key: "Enter", repeat: true });
    expect(here).toBe(PAGE);
    fireEvent.click(clear?.querySelector("td") as HTMLElement);
    expect(here).toBe(`${PAGE}?machine=kill_switch&env=demo`);
  });

  it("test_page_back_to_machines_closes_the_view_and_returns_focus_to_its_row", async () => {
    serve(WORLD);
    show();
    const [, latched] = await machineRows();
    fireEvent.keyDown(latched?.querySelector("th") as HTMLElement, { key: "Enter" });
    const back = await screen.findByRole("button", { name: "Back to machines" }, WAIT);
    act(() => back.focus());
    fireEvent.click(back);
    await waitFor(() => expect(here).toBe(PAGE), WAIT);
    expect(screen.queryByRole("heading", { level: 2, name: /· DEMO$/ })).toBeNull();
    const row = grid().querySelector(`tr[data-machine-row="${LATCHED_KEY}@demo"]`);
    await waitFor(() => expect(row?.contains(document.activeElement)).toBe(true), WAIT);
  });

  it("test_page_a_deep_link_opens_the_machine_and_back_replaces_it_with_the_list", async () => {
    serve(WORLD);
    show(["/journal", OPEN]);
    const heading = await screen.findByRole(
      "heading",
      { level: 2, name: `${LATCHED_KEY} · DEMO` },
      WAIT,
    );
    expect(heading).not.toHaveFocus(); // a deep link moves no focus
    fireEvent.click(screen.getByRole("button", { name: "Back to machines" }));
    await waitFor(() => expect(here).toBe(PAGE), WAIT); // the list in its place, not the journal
  });

  it("test_page_a_machine_opened_from_another_replaces_its_entry_and_its_row_finds_its_heading", async () => {
    serve(WORLD);
    show();
    const [clear, latched] = await machineRows();
    fireEvent.keyDown(latched?.querySelector("th") as HTMLElement, { key: "Enter" });
    await waitFor(() => expect(here).toBe(OPEN), WAIT);
    // From the open view, another row: its entry replaces the first one's (C-1137-05 (c)).
    const other = clear?.querySelector("th") as HTMLElement;
    fireEvent.keyDown(other, { key: "Enter" });
    const heading = await screen.findByRole(
      "heading",
      { level: 2, name: "kill_switch · DEMO" },
      WAIT,
    );
    expect(here).toBe(`${PAGE}?machine=kill_switch&env=demo`);
    await waitFor(() => expect(heading).toHaveFocus(), WAIT);
    await waitFor(() => expect(hereState).toEqual({ cvInspectorOpened: true }), WAIT);
    // The open machine's row again: focus goes back to its heading, and nothing navigates.
    const entry = hereKey;
    act(() => other.focus());
    fireEvent.keyDown(other, { key: "Enter" });
    expect(heading).toHaveFocus();
    await act(async () => undefined);
    expect(hereKey).toBe(entry);
    // Back to machines pops the one entry: the list, not the machine opened first.
    fireEvent.click(screen.getByRole("button", { name: "Back to machines" }));
    await waitFor(() => expect(here).toBe(PAGE), WAIT);
  });

  it("test_page_the_focus_flag_moves_focus_once_never_again_on_forward", async () => {
    serve(WORLD);
    show();
    const [, latched] = await machineRows();
    fireEvent.keyDown(latched?.querySelector("th") as HTMLElement, { key: "Enter" });
    const name = `${LATCHED_KEY} · DEMO`;
    const heading = await screen.findByRole("heading", { level: 2, name }, WAIT);
    await waitFor(() => expect(heading).toHaveFocus(), WAIT);
    // Used once, the flag is gone from the entry: it keeps only that the list opened it.
    await waitFor(() => expect(hereState).toEqual({ cvInspectorOpened: true }), WAIT);
    fireEvent.click(screen.getByRole("button", { name: "Back to machines" }));
    await waitFor(() => expect(here).toBe(PAGE), WAIT);
    // Browser Forward reopens the machine and moves no focus (A-1137-12).
    const forward = screen.getByRole("button", { name: "Forward" });
    act(() => forward.focus());
    fireEvent.click(forward);
    await waitFor(() => expect(here).toBe(OPEN), WAIT);
    await screen.findByRole("heading", { level: 2, name }, WAIT);
    await act(async () => undefined);
    expect(forward).toHaveFocus();
  });

  it("test_page_a_query_off_its_pattern_is_ignored_and_asks_nothing", async () => {
    const requests = serve(WORLD);
    show([`${PAGE}?machine=${encodeURIComponent("../users")}&env=prod`]);
    await machineRows();
    expect(screen.queryByRole("heading", { level: 2, name: /·/ })).toBeNull();
    expect(requests.map((r) => r.path)).toEqual([LIST]);
  });
});

describe("tab order and axe", { timeout: 60_000 }, () => {
  it("test_page_tab_order_is_reread_then_latched_only_then_the_grid_once", async () => {
    serve(WORLD);
    const { view } = show();
    await machineRows();
    const page = view.container.querySelector("main") as HTMLElement;
    const stops = [
      ...page.querySelectorAll<HTMLElement>("button, a[href], input, [tabindex]"),
    ].filter((node) => node.tabIndex >= 0 && !node.closest("[aria-hidden='true']"));
    expect(stops).toHaveLength(3);
    expect(stops[0]).toBe(screen.getByRole("button", { name: "Re-read" }));
    expect(stops[1]).toBe(screen.getByRole("switch", { name: "Latched only" }));
    expect(grid().contains(stops[2] as HTMLElement)).toBe(true); // the grid's one roving stop
  });

  it("test_page_reread_keeps_focus_where_it_is_and_says_nothing", async () => {
    const requests = serve(WORLD);
    show();
    await machineRows();
    await act(async () => undefined);
    const said = polite()?.dataset["seq"];
    const reread = screen.getByRole("button", { name: "Re-read" });
    act(() => reread.focus());
    fireEvent.click(reread);
    await waitFor(() => expect(requests.filter((r) => r.path === LIST)).toHaveLength(2), WAIT);
    await act(async () => undefined);
    expect(reread).toHaveFocus();
    expect(polite()?.dataset["seq"]).toBe(said);
  });

  it.each(["dark", "light"])("test_page_has_no_serious_axe_violation_in_%s", async (theme) => {
    document.documentElement.setAttribute("data-theme", theme);
    serve(WORLD);
    show([OPEN]);
    await machineRows();
    await screen.findByRole("heading", { name: "Transitions" }, WAIT);
    // jsdom has no layout: contrast is the real-browser collectors' (e2e/a11y) and inspector-pairs'.
    const res = await axe.run(document.body, { rules: { "color-contrast": { enabled: false } } });
    document.documentElement.removeAttribute("data-theme");
    expect(res.violations.filter((v) => v.impact === "serious" || v.impact === "critical")).toEqual(
      [],
    );
  });
});
