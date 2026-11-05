// E15-S03 (#476) PR-1: the workspace mount. Gherkin "Progressive loading, not a blocking wait" and
// "A delisted symbol degrades one pane only" (its "can still be saved" leg is PR-2's), the unknown
// kind, the SR-E15-15 re-check at mount, the restore announcement and its analytics, the failure
// states and axe. Symbols resolve against the recorded instruments (C-13.5): LUNAUSDT is Closed.
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { resolve } from "node:path";
import { useEffect, type JSX } from "react";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { WorkspaceHost, type HostDeps } from "../../../src/features/workspace/WorkspaceHost";
import {
  getWorkspace,
  READ_TIMEOUT_MS,
  type ApiResult,
  type WorkspaceDetail,
} from "../../../src/features/workspace/api/workspacesApi";
import { createDefaultPaneRegistry } from "../../../src/features/workspace/dock/paneRegistry";
import { createSymbolStatus } from "../../../src/features/workspace/mount/symbolStatus";
import { readLastUsed, writeLastUsed } from "../../../src/features/workspace/current/resolveTarget";
import type { InstrumentIndex, Lookup } from "../../../src/features/symbol-search/instrumentIndex";
import * as search from "../../../src/features/symbol-search/searchSession";
import { resetShellState, setShellState, type Me } from "../../../src/shell/bootstrap/store";

const { apiFetch } = vi.hoisted(() => ({ apiFetch: vi.fn<typeof fetch>() }));
vi.mock("../../../src/lib/http/csrfFetch", async (actual) => ({
  ...(await actual<object>()),
  apiFetch,
}));

const axe = createRequire(createRequire(import.meta.url).resolve("@axe-core/playwright"))(
  "axe-core",
) as { run: (el: Element) => Promise<{ violations: { impact?: string | null }[] }> };

const PAGE = "../../../../../packages/fixtures/bybit/2026-10-05/rest/instruments_after.json";
const LISTED = new Map(
  (
    JSON.parse(readFileSync(resolve(import.meta.dirname, PAGE), "utf8")) as {
      result: { list: { symbol: string; status: string }[] };
    }
  ).result.list.map((i) => [i.symbol, i.status] as const),
);
/** `lookupSymbol`'s answer on the fixture page: Trading listed, Closed by status, else a 404. */
const answerOf = (symbol: string): Lookup => {
  const status = LISTED.get(symbol);
  if (status === undefined) return { kind: "not_listed", symbol };
  const instrument = { symbol, status } as Extract<Lookup, { kind: "status" }>["instrument"];
  return { kind: status === "Trading" ? "listed" : "status", symbol, instrument };
};

const USER = "0190a000-0000-7000-8000-0000000000aa";
const WS = "0190a000-0000-7000-8000-000000000001";
const [A, B] = ["0190a000-0000-7000-8000-00000000000a", "0190a000-0000-7000-8000-00000000000b"];
type P = readonly [kind: string, symbol: string | null, interval?: string];
const FOUR: P[] = [
  ["chart", "BTCUSDT", "time:1"],
  ["chart", "ETHUSDT", "time:240"],
  ["dom", "SOLUSDT"],
  ["oi", "LUNAUSDT"],
];
const PRESET = ["", "1x1", "2x1", "1+3", "2x2"];

/** The fields the host reads; the rest of `22`'s `Layout` is not consulted. */
const layout = (id: string, panes: P[], extra: object = {}) => ({
  id,
  is_default: false,
  grid_preset: PRESET[panes.length],
  grid_spec: null,
  panes: panes.map(([kind, symbol, interval], slot) => ({
    slot_index: slot,
    pane_kind: kind,
    symbol,
    interval_code: interval ?? null,
  })),
  ...extra,
});
const ok = (...layouts: object[]): ApiResult<WorkspaceDetail> =>
  ({ ok: true, etag: null, value: { id: WS, name: "Scalping", layouts } }) as never;

function harness(
  answers: ApiResult<WorkspaceDetail>[],
  extra: Partial<HostDeps> = {},
  held = false,
) {
  const pending = new Map<string, () => void>();
  const reports: Readonly<Record<string, unknown>>[] = [];
  let t = 1_000;
  const next = (): ApiResult<WorkspaceDetail> =>
    (answers.length > 1 ? answers.shift() : answers[0]) as ApiResult<WorkspaceDetail>;
  const get = vi.fn(() => Promise.resolve(next()));
  const deps: HostDeps = {
    get,
    registry: createDefaultPaneRegistry(),
    symbols: () =>
      createSymbolStatus((symbol) =>
        held
          ? new Promise((done) => pending.set(symbol, () => done(answerOf(symbol))))
          : Promise.resolve(answerOf(symbol)),
      ),
    now: () => (t += 400),
    report: (d) => reports.push(d),
    ...extra,
  };
  const answer = (symbol: string) => act(async () => pending.get(symbol)?.());
  return { deps, reports, get, answer };
}

const host = (deps: HostDeps) =>
  render(
    <MemoryRouter>
      <WorkspaceHost workspaceId={WS} deps={deps} />
    </MemoryRouter>,
  );
const press = (button: HTMLElement): void => {
  button.focus(); // reached as a keyboard user reaches it; Enter itself is the e2e's (no jsdom)
  expect(button).toHaveFocus();
  fireEvent.click(button);
};
const me = (role: string): Me => ({ role, user: { id: USER } }) as unknown as Me;
/** The host's one polite region (the "Opening…" status before it has none). */
const said = (): HTMLElement =>
  document.querySelector<HTMLElement>('[role="status"][aria-atomic="true"]') ?? document.body;

beforeEach(() => {
  localStorage.clear();
  setShellState({ me: me("manager"), environment: "demo" });
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
  apiFetch.mockReset();
  resetShellState();
  search.resetSymbolSearch();
});

describe("WorkspaceHost: restore", () => {
  it("test_restore_progressive_skeleton_named_frames_before_data_then_each_pane_fills_alone", async () => {
    const h = harness([ok(layout(A, FOUR))], {}, true);
    host(h.deps);
    expect(screen.getByRole("status")).toHaveTextContent("Opening your workspace…");
    // The frame: regions named by kind, symbol, spelled interval and environment (D03 D-5).
    const chart = await screen.findByRole("region", { name: "Chart, BTCUSDT 1 minute, Demo" });
    for (const name of ["Chart, ETHUSDT 4 hours, Demo", "DOM, SOLUSDT, Demo", "OI, LUNAUSDT"]) {
      expect(screen.getByRole("region", { name })).toBeVisible();
    }
    expect(said()).toHaveTextContent("Loading Scalping, 4 panels.");
    const skeleton = { name: "Chart, BTCUSDT 1 minute, Demo, loading" };
    expect(within(chart).getByRole("group", skeleton)).toHaveAttribute("aria-busy", "true");
    expect(screen.getAllByRole("group", { name: /, loading$/ })).toHaveLength(4);
    // One pane fills in on its own; the others still wait, and nothing says ready yet.
    await h.answer("BTCUSDT");
    expect(within(chart).queryByRole("group", { name: /loading/ })).toBeNull();
    expect(screen.getAllByRole("group", { name: /, loading$/ })).toHaveLength(3);
    expect(said()).toHaveTextContent("Loading Scalping, 4 panels.");
    for (const s of ["ETHUSDT", "SOLUSDT", "LUNAUSDT"]) await h.answer(s);
    expect(screen.queryAllByRole("group", { name: /, loading$/ })).toHaveLength(0);
  });

  it("test_restore_delisted_symbol_degrades_one_pane_and_the_others_stay_interactive", async () => {
    const h = harness([ok(layout(A, FOUR))]);
    host(h.deps);
    const oi = await screen.findByRole("region", { name: "OI, LUNAUSDT" });
    const cp21 = "LUNAUSDT is no longer listed. This panel can't load it.";
    expect(await within(oi).findByText(cp21)).toBeVisible();
    for (const name of ["Chart, BTCUSDT 1 minute, Demo", "DOM, SOLUSDT, Demo"]) {
      const region = screen.getByRole("region", { name });
      expect(within(region).queryByText(/no longer listed/)).toBeNull();
      expect(within(region).getByRole("button", { name: /^Close / })).toBeEnabled();
    }
    // The restore speaks once, with its failure; analytics carry counts and closed sets only.
    expect(said()).toHaveTextContent(
      "Workspace ready: 3 of 4 panels. 1 panel couldn't load: OI, LUNAUSDT.",
    );
    expect(h.reports).toEqual([
      { name: "workspace.pane_error", reason: "delisted" },
      { name: "workspace.restore_completed", ms: 400, paneCount: 4, failedPanes: 1 },
    ]);
    const { violations } = await axe.run(document.body);
    expect(violations.filter((v) => v.impact === "serious" || v.impact === "critical")).toEqual([]);
    press(within(oi).getByRole("button", { name: "Close panel" }));
    expect(screen.getAllByRole("region")).toHaveLength(3);
    expect(screen.getByRole("region", { name: "DOM, SOLUSDT, Demo" })).toHaveFocus();
  });

  it("test_restore_a_pane_closed_before_it_settles_is_not_waited_for", async () => {
    const h = harness([ok(layout(A, FOUR.slice(0, 2)))], {}, true);
    host(h.deps);
    const eth = await screen.findByRole("region", { name: "Chart, ETHUSDT 4 hours, Demo" });
    press(within(eth).getByRole("button", { name: /^Close / }));
    await h.answer("BTCUSDT");
    expect(said()).toHaveTextContent("Workspace ready: Scalping, 1 panel.");
    expect(h.reports).toMatchObject([{ paneCount: 1, failedPanes: 0 }]);
  });

  it("test_restore_change_symbol_rebinds_the_delisted_pane_through_symbol_search", async () => {
    host(harness([ok(layout(A, [["oi", "LUNAUSDT"]]))]).deps);
    await waitFor(() => expect(said()).toHaveTextContent("Workspace ready"));
    expect(screen.queryByRole("button", { name: "Change symbol…" })).toBeNull(); // no index yet
    const index = { start: () => undefined, stop: () => undefined } as unknown as InstrumentIndex;
    act(() => void search.startSymbolSearch(index)); // stopped by resetSymbolSearch
    press(await screen.findByRole("button", { name: "Change symbol…" }));
    const { open, opener } = search.getSymbolSearchState();
    expect(open).toBe(true);
    expect(opener?.target).toMatchObject({ pane: "OI", symbol: "LUNAUSDT", armed: false });
    act(() => opener?.open("BTCUSDT", "target"));
    expect(await screen.findByRole("region", { name: "OI, BTCUSDT" })).toBeVisible();
    await waitFor(() => expect(screen.queryByText(/no longer listed/)).toBeNull());
    expect(search.getSymbolSearchState().opener).toBeNull();
  });

  it("test_restore_unknown_kind_is_an_error_pane_not_an_exception", async () => {
    const h = harness([
      ok(
        layout(A, [
          ["chart", "BTCUSDT", "time:D"],
          ["heatmap_3d", null],
        ]),
      ),
    ]);
    host(h.deps);
    const unknown = await screen.findByRole("region", { name: "Panel" });
    expect(within(unknown).getByText(/^This panel type isn't supported in this/)).toBeVisible();
    expect(screen.getByRole("region", { name: "Chart, BTCUSDT 1 day, Demo" })).toBeVisible();
    await waitFor(() =>
      expect(h.reports[0]).toEqual({ name: "workspace.pane_error", reason: "unknown_kind" }),
    );
  });

  it("test_restore_rechecks_an_owner_only_kind_at_mount_for_a_manager", async () => {
    const mounted: string[] = [];
    function Journal({ paneId }: { paneId: string }): JSX.Element {
      useEffect(() => void mounted.push(paneId), [paneId]);
      return <p>journal body</p>;
    }
    const registry = createDefaultPaneRegistry();
    registry.register("journal", {
      label: "Journal",
      component: Journal,
      minWidth: 0,
      minHeight: 0,
    });
    const extra = { registry, ownerOnlyKinds: new Set(["journal"]) };
    const stored = ok(
      layout(A, [
        ["journal", null],
        ["tape", "BTCUSDT"],
      ]),
    );
    const view = host(harness([stored], extra).deps);
    const journal = await screen.findByRole("region", { name: "Journal" });
    expect(within(journal).getByText("Only the owner can open this panel.")).toBeVisible();
    await waitFor(() => expect(said()).toHaveTextContent("Workspace ready: Scalping, 1 panel."));
    expect(mounted).toEqual([]);
    view.unmount();
    setShellState({ me: me("owner") });
    host(harness([stored], extra).deps);
    expect(await screen.findByText("journal body")).toBeVisible();
    expect(mounted).toHaveLength(1);
  });
});

describe("WorkspaceHost: the layout opened and the failure states", () => {
  it("test_open_prefers_the_last_used_layout_then_the_default_and_records_it", async () => {
    const a = layout(A, [["tape", "BTCUSDT"]], { is_default: true });
    const b = layout(B, [["cvd", "ETHUSDT"]]);
    const first = host(harness([ok(a, b)]).deps);
    expect(await screen.findByRole("region", { name: "Tape, BTCUSDT" })).toBeVisible();
    expect(readLastUsed(USER)).toEqual({ workspaceId: WS, layoutId: A });
    first.unmount();
    writeLastUsed(USER, { workspaceId: WS, layoutId: B });
    host(harness([ok(a, b)]).deps);
    expect(await screen.findByRole("region", { name: "CVD, ETHUSDT" })).toBeVisible();
  });

  it("test_open_unavailable_offers_try_again_which_reads_once_more", async () => {
    const h = harness([{ ok: false, failure: { kind: "unavailable" } }, ok(layout(A, FOUR))]);
    host(h.deps);
    expect(await screen.findByText("Couldn't open this workspace.")).toBeVisible();
    press(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("region", { name: "DOM, SOLUSDT, Demo" })).toBeVisible();
    expect(h.get).toHaveBeenCalledTimes(2);
  });

  it("test_open_not_found_refused_layout_and_no_layout_states", async () => {
    const gone = host(harness([{ ok: false, failure: { kind: "not_found" } }]).deps);
    expect(await screen.findByRole("heading", { level: 1 })).toBeVisible(); // the uniform 404
    expect(screen.queryByRole("region")).toBeNull();
    gone.unmount();
    const view = host(harness([ok(layout(A, FOUR, { grid_preset: "9x9" }))]).deps);
    expect(await screen.findByText("This layout couldn't be opened.")).toBeVisible();
    view.unmount();
    host(harness([ok()]).deps);
    const empty = "No layout yet — start from a preset or blank canvas";
    expect(await screen.findByText(empty)).toBeVisible();
  });

  it("test_open_a_timed_out_restore_renders_the_error_pane_with_try_again", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    const hung = (_: unknown, init?: RequestInit): Promise<Response> =>
      new Promise((_, fail) => init?.signal?.addEventListener("abort", () => fail(new Error())));
    const detail = (ok(layout(A, FOUR)) as { value: unknown }).value;
    apiFetch.mockImplementationOnce(hung).mockResolvedValueOnce(Response.json(detail));
    host(harness([], { get: getWorkspace }).deps);
    expect(screen.getByRole("status")).toHaveTextContent("Opening your workspace…");
    await act(() => vi.advanceTimersByTimeAsync(READ_TIMEOUT_MS));
    vi.useRealTimers();
    expect(screen.getByText("Couldn't open this workspace.")).toBeVisible();
    press(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("region", { name: "DOM, SOLUSDT, Demo" })).toBeVisible();
    expect(apiFetch).toHaveBeenCalledTimes(2);
  });

  it("test_open_403_is_the_t2_sentence_alone_and_a_422_offers_no_retry", async () => {
    const forbidden = { ok: false, failure: { kind: "forbidden", code: "forbidden" } } as const;
    const view = host(harness([forbidden]).deps);
    expect(await screen.findByText("Your role can't see workspaces.")).toBeVisible();
    expect(screen.queryByRole("button")).toBeNull(); // E09-D09 §8 sentence form: CMP-026, no button
    // CMP-026 (a static block under its heading), not CMP-027's alert-style panel.
    expect(screen.getByRole("heading", { name: "Workspaces unavailable" })).toBeVisible();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.queryByText("Couldn't open this workspace.")).toBeNull();
    const { violations } = await axe.run(document.body);
    expect(violations.filter((v) => v.impact === "serious" || v.impact === "critical")).toEqual([]);
    view.unmount();
    host(harness([{ ok: false, failure: { kind: "invalid", code: null, rule: null } }]).deps);
    expect(await screen.findByText("This workspace can't be opened as saved.")).toBeVisible();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("test_open_429_says_its_wait_and_offers_try_again_once_the_wait_has_passed", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    const limited = { ok: false, failure: { kind: "rate_limited", retryAfterS: 7 } } as const;
    const h = harness([limited, ok(layout(A, FOUR))]);
    host(h.deps);
    await act(() => vi.advanceTimersByTimeAsync(0)); // the answer, and its wait starts
    expect(screen.getByText("Too many requests — try again in 7 s.")).toBeVisible();
    await act(() => vi.advanceTimersByTimeAsync(6_999));
    expect(screen.queryByRole("button", { name: "Try again" })).toBeNull();
    await act(() => vi.advanceTimersByTimeAsync(1));
    vi.useRealTimers();
    press(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("region", { name: "DOM, SOLUSDT, Demo" })).toBeVisible();
    expect(h.get).toHaveBeenCalledTimes(2);
  });

  it("test_open_429_wait_is_clamped_to_an_hour_before_the_timer", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    const huge = { ok: false, failure: { kind: "rate_limited", retryAfterS: 2 ** 31 } } as const;
    host(harness([huge]).deps);
    await act(() => vi.advanceTimersByTimeAsync(0));
    await act(() => vi.advanceTimersByTimeAsync(3_599_999)); // not at once, as an unclamped timer would
    expect(screen.queryByRole("button", { name: "Try again" })).toBeNull();
    await act(() => vi.advanceTimersByTimeAsync(1));
    vi.useRealTimers();
    expect(screen.getByRole("button", { name: "Try again" })).toBeEnabled();
  });

  it("test_open_a_rejected_read_is_never_left_loading", async () => {
    host(harness([], { get: () => Promise.reject(new Error("boom")) }).deps);
    expect(await screen.findByText("Couldn't open this workspace.")).toBeVisible();
    expect(screen.getByRole("button", { name: "Try again" })).toBeEnabled();
  });
});
