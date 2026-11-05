/**
 * E42-S06 (#1084) part 1b: SCR-143 at R-350 inside the admin area (E42-D05 §5; the plan's §3–§5):
 * a region per component and the fixed tiles, the tab order, the reads on mount and Re-read only,
 * a frame that renders its own tile alone (the ticket's integration test), the outage it survives,
 * the detail view's focus, and a `403`. CMP-178 is wrapped to count each tile's renders.
 */
import { createRequire } from "node:module";
import { createElement, type JSX } from "react";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type * as Ui from "@candleviewer/ui";
import { InShellProvider } from "../../../../src/features/app-shell/ScreenRoot";
import { clearAnnouncements } from "../../../../src/features/app-shell/announcer";
import { healthStore } from "../../../../src/features/admin/health/healthStore";
import { AdminArea } from "../../../../src/features/admin/shell/AdminArea";
import { adminReads } from "../../../../src/features/admin/overview/readStore";
import {
  applySystemUpdate,
  resetShellState,
  setShellState,
  type Me,
} from "../../../../src/shell/bootstrap/store";

const renders = vi.hoisted(() => new Map<string, number>());
vi.mock("@candleviewer/ui", async (importOriginal) => {
  const ui = await importOriginal<typeof Ui>();
  function CountedTile(props: Ui.SystemHealthTileProps): JSX.Element {
    renders.set(props.label, (renders.get(props.label) ?? 0) + 1);
    return createElement(ui.SystemHealthTile, props);
  }
  return { ...ui, SystemHealthTile: CountedTile };
});

// axe-core is a transitive dependency of @axe-core/playwright (as in AdminArea.test.tsx).
const axe = createRequire(createRequire(import.meta.url).resolve("@axe-core/playwright"))(
  "axe-core",
) as { run: (el: Element, o?: object) => Promise<{ violations: { impact?: string | null }[] }> };

const AT = "2026-10-22T14:02:11Z";
const HEALTH = "/api/v1/admin/health";
const healthy = (name: string, latency_ms: number) => ({ name, state: "healthy", latency_ms });
const page = (items: unknown[]) => ({
  items,
  meta: { has_more: false, count: items.length, next_cursor: null },
});
const GAP = {
  ...{ id: "i-1", component: "recorder", severity: "error", status: "open" },
  ...{ title: "recorder gap on BTCUSDT", first_seen_at: AT, last_seen_at: AT },
};
const BODIES: Readonly<Record<string, unknown>> = {
  [HEALTH]: {
    ...{ overall: "healthy", version: "1.4.0" },
    components: [healthy("postgres", 3), healthy("oms", 1), healthy("recorder", 42)],
  },
  "/api/v1/admin/incidents?status=open&limit=100": page([GAP]),
  "/api/v1/admin/incidents?status=acknowledged&limit=100": page([]),
  "/api/v1/admin/statecharts?kind=position_protection": { kinds: [], snapshots: {} },
};
let paths: string[];
let replies: Map<string, { status: number; body: unknown }>;

beforeEach(() => {
  paths = [];
  replies = new Map();
  renders.clear();
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      paths.push(path);
      const body = BODIES[path];
      const reply = replies.get(path) ?? { status: body === undefined ? 404 : 200, body };
      return new Response(JSON.stringify(reply.body ?? {}), { status: reply.status });
    }),
  );
  setShellState({ me: { role: "owner" } as unknown as Me, environment: "demo" });
});

afterEach(() => {
  healthStore.reset();
  adminReads.reset();
  resetShellState();
  clearAnnouncements();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

function open(path = "/admin/health"): ReturnType<typeof render> {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <InShellProvider>
        <AdminArea routeId="R-350" owner={null} />
      </InShellProvider>
    </MemoryRouter>,
  );
}
const tile = (name: string): HTMLElement => screen.getByRole("region", { name });
const settled = (): Promise<void> =>
  waitFor(() => expect(document.querySelector('[aria-busy="true"]')).toBeNull());

describe("SCR-143 System health", () => {
  it("test_page_renders_a_region_per_component_and_the_fixed_tiles_with_no_serious_axe", async () => {
    const view = open();
    await settled();
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("System health");
    expect(within(tile("Postgres (postgres)")).getByText("3").closest("p")?.textContent).toContain(
      "probe 3 ms",
    );
    expect(tile("Clock").textContent).toContain("not measured (time sync not deployed)");
    expect(tile("Algo engine").textContent).toContain("Not reported yet");
    expect(tile("Chart engine (this session)").textContent).toContain(
      "No chart open in this window",
    );
    expect(screen.getByText("Incidents (1 open)")).toBeTruthy();
    expect(screen.getByText(/^Overall: healthy · as of \d\d:\d\d:\d\d$/)).toBeTruthy();
    // jsdom has no layout: contrast is the Playwright axe run's.
    const rules = { "color-contrast": { enabled: false } };
    const { violations } = await axe.run(view.container, { rules });
    expect(violations.filter((v) => v.impact === "serious" || v.impact === "critical")).toEqual([]);
  });

  it("test_page_mounting_leaves_focus_where_the_shell_put_it", async () => {
    open();
    await settled();
    expect(document.activeElement).toBe(document.body);
  });

  it("test_page_tab_order_runs_from_re_read_through_each_tiles_heading_link", async () => {
    const view = open();
    await settled();
    const stops = [...view.container.querySelectorAll("a, button")].map((el) => el.textContent);
    const from = stops.indexOf("Re-read");
    expect(stops.slice(from, from + 4)).toEqual([
      "Re-read",
      "Postgres (postgres)",
      "Order manager (oms)",
      "Recorder (recorder)",
    ]);
  });

  it("test_page_reads_on_mount_and_on_re_read_only_never_on_a_timer", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    open();
    await settled();
    await act(async () => void (await vi.advanceTimersByTimeAsync(60_000)));
    const reads = (): number => paths.filter((p) => p in BODIES).length;
    expect(reads()).toBe(4);
    fireEvent.click(screen.getByRole("button", { name: "Re-read" }));
    await waitFor(() => expect(reads()).toBe(8));
  });

  it("test_page_a_frame_that_degrades_one_component_renders_that_tile_alone", async () => {
    open();
    await settled();
    // A frame lists every probe (`23` §15.9); the first takes the words from the report.
    const full = (oms: { name: string; state: "healthy" | "degraded"; detail?: string }) =>
      applySystemUpdate({
        ...{ kind: "health", health: oms.state },
        components: [
          { name: "postgres", state: "healthy" },
          oms,
          { name: "recorder", state: "healthy" },
        ],
      });
    act(() => full({ name: "oms", state: "healthy" }));
    const before = new Map(renders);
    act(() => full({ name: "oms", state: "degraded", detail: "<b>reconciliation</b> pending" }));
    const oms = tile("Order manager (oms)");
    expect(oms.textContent).toContain("degraded — <b>reconciliation</b> pending"); // text, never HTML
    expect(oms.querySelector("b")).toBeNull();
    const changed = [...renders].filter(([label, n]) => before.get(label) !== n).map(([l]) => l);
    expect(changed).toEqual(["Order manager (oms)"]);
  });

  it("test_page_full_frames_with_unchanged_words_render_no_tile_and_a_changed_word_one", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    open();
    await settled();
    // A frame lists every probe (`23` §15.9); the first takes the words from the report.
    type State = "healthy" | "degraded";
    const full = (oms: State) =>
      applySystemUpdate({
        ...{ kind: "health", health: oms },
        components: [
          ...[
            { name: "postgres", state: "healthy" as const },
            { name: "oms", state: oms },
          ],
          { name: "recorder", state: "healthy" as const },
        ],
      });
    act(() => full("healthy"));
    const before = new Map(renders);
    vi.setSystemTime(Date.now() + 2_000);
    act(() => full("healthy"));
    expect(renders).toEqual(before); // no CMP-178 renders; each tile's "as of" leaf moves alone
    const at = new Date().toISOString().slice(11, 19);
    expect(tile("Postgres (postgres)").textContent).toContain(`as of ${at}`);
    vi.setSystemTime(Date.now() + 2_000);
    act(() => full("degraded"));
    const changed = [...renders].filter(([label, n]) => before.get(label) !== n).map(([l]) => l);
    expect(changed).toEqual(["Order manager (oms)"]);
  });

  it("test_page_a_frame_naming_oms_in_a_state_it_cannot_read_keeps_its_tile_not_received", async () => {
    open();
    await settled();
    const exploded = { name: "oms", state: "exploded" as "down" };
    act(() => applySystemUpdate({ kind: "health", health: "healthy", components: [exploded] }));
    const oms = tile("Order manager (oms)");
    expect(oms.textContent).toContain("— not received");
    expect(oms.textContent).not.toMatch(/probe|healthy|\b1 ms/);
  });

  it("test_page_a_reported_component_with_no_readable_state_keeps_its_tile_not_received", async () => {
    const body = { overall: "healthy", components: [healthy("oms", 1), { name: "recorder" }] };
    replies.set(HEALTH, { status: 200, body });
    open();
    await settled();
    const recorder = tile("Recorder (recorder)");
    expect(recorder.textContent).toContain("— not received");
    expect(recorder.textContent).not.toMatch(/probe|healthy/);
  });

  it("test_page_a_name_the_newest_frame_drops_keeps_its_tile_not_received_never_the_reports_word", async () => {
    open();
    await settled();
    act(() =>
      applySystemUpdate({
        ...{ kind: "health", health: "healthy" },
        components: [
          { name: "postgres", state: "healthy" },
          { name: "oms", state: "healthy" },
        ],
      }),
    );
    const recorder = tile("Recorder (recorder)");
    expect(recorder.textContent).toContain("— not received");
    expect(recorder.textContent).not.toMatch(/probe|healthy|\b42 ms/);
  });

  it("test_page_a_failed_re_read_keeps_numbers_stale_and_a_good_retry_hands_focus_to_re_read", async () => {
    open();
    await settled();
    replies.set(HEALTH, { status: 503, body: { code: "store_unavailable" } });
    fireEvent.click(screen.getByRole("button", { name: "Re-read" }));
    await screen.findByText(
      "Health report unavailable — the server is busy. Showing live states only.",
    );
    expect(tile("Postgres (postgres)").textContent).toMatch(
      /probe 3 ms.*stale since \d\d:\d\d:\d\d/,
    );
    replies.delete(HEALTH);
    const line = screen.getByText(/^Health report unavailable/).closest("p") as HTMLElement;
    const retry = within(line).getByRole("button", { name: "Retry" });
    retry.focus();
    fireEvent.click(retry);
    await waitFor(() => expect(screen.queryByText(/^Health report unavailable/)).toBeNull());
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Re-read" }));
  });

  it("test_page_the_detail_view_takes_focus_and_gives_it_back_to_its_tile", async () => {
    open();
    await settled();
    fireEvent.click(within(tile("Recorder (recorder)")).getByRole("link"));
    const back = await screen.findByRole("link", { name: "All components" });
    expect(document.activeElement).toBe(back);
    expect(screen.getByRole("heading", { level: 2, name: "Recorder (recorder)" })).toBeTruthy();
    expect(
      screen.getByText("error · recorder gap on BTCUSDT · last seen 2026-10-22 14:02 UTC"),
    ).toBeTruthy();
    const recorder = screen.getByRole("link", { name: "Open Recorder & storage" });
    expect(recorder.getAttribute("href")).toBe("/admin/recorder");
    expect(document.title).toBe("System health - Recorder (recorder) - CandleViewer");
    fireEvent.click(back);
    const link = await within(
      await screen.findByRole("region", { name: "Recorder (recorder)" }),
    ).findByRole("link");
    await waitFor(() => expect(document.activeElement).toBe(link));
  });

  it("test_page_a_detail_view_for_a_name_no_tile_has_says_so_and_never_echoes_it", async () => {
    open("/admin/health?component=Free%20money%20here");
    await settled();
    expect(screen.getByRole("heading", { level: 2 }).textContent).toBe("No such component.");
    expect(screen.queryByText(/Free money/)).toBeNull();
  });

  it("test_page_an_anchor_shaped_name_the_answered_report_lacks_is_never_echoed", async () => {
    open("/admin/health?component=send_funds_now");
    await settled();
    expect(screen.getByRole("heading", { level: 2 }).textContent).toBe("No such component.");
    expect(document.body.textContent).not.toMatch(/send_funds_now/);
    expect(document.title).toBe("System health - No such component - CandleViewer");
    // No tile has it: closing hands focus to Re-read, never to <body>.
    fireEvent.click(screen.getByRole("link", { name: "All components" }));
    const reread = await screen.findByRole("button", { name: "Re-read" });
    await waitFor(() => expect(document.activeElement).toBe(reread));
  });

  it("test_page_the_detail_view_keeps_the_pages_state_lines_and_a_failed_first_read", async () => {
    replies.set(HEALTH, { status: 503, body: { code: "store_unavailable" } });
    open("/admin/health?component=recorder");
    const line = await screen.findByText(/^Health report unavailable — the server is busy/);
    expect(
      within(line.closest("p") as HTMLElement).getByRole("button", { name: "Retry" }),
    ).toBeTruthy();
    // The report failed before any body: a component-shaped name still heads its view.
    expect(screen.getByRole("heading", { level: 2 }).textContent).toBe("Recorder (recorder)");
    const down = { ...(BODIES[HEALTH] as object), components: [{ name: "oms", state: "down" }] };
    replies.set(HEALTH, { status: 200, body: down });
    fireEvent.click(screen.getByRole("button", { name: "Re-read" }));
    expect(await screen.findByText(/^Down: Order manager\./)).toBeTruthy();
    expect(screen.getByText(/^Overall: /)).toBeTruthy();
  });

  it("test_page_a_403_on_an_ops_read_withdraws_the_page_and_asks_nothing_more", async () => {
    replies.set("/api/v1/admin/statecharts?kind=position_protection", {
      status: 403,
      body: { code: "forbidden" },
    });
    open();
    await screen.findByRole("heading", { level: 1, name: "Your access changed" });
    const asked = paths.length;
    act(() => healthStore.reread());
    expect(paths).toHaveLength(asked);
    expect(screen.queryByRole("button", { name: "Re-read" })).toBeNull();
  });
});
