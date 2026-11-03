/**
 * E42-S08 (#1137) §5.2: the machine view (SI-3 to SI-7). Its facts as served, the acknowledge as
 * T2 while the machine is latched (BQ-5: a press sends nothing and says its reason once), the
 * chart's drawing beside its text list, the configuration's leaves "(current)" in both (AC4; BQ-6),
 * the timeline newest first, and each state of §5.2's table. Reads go through the real read layer
 * and a store of the test's own, against a stubbed `fetch` (no network, C-13.5).
 */
import { createRequire } from "node:module";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { GatedAnnounceProvider } from "@candleviewer/ui";
import { clearAnnouncements, ShellAnnouncer } from "../../../../src/features/app-shell/announcer";
import type { ConsumerSpec, TopicFrame, TopicHandle } from "../../../../src/lib/ws/api";
import { setActiveClient } from "../../../../src/lib/ws/client/activeClient";
import type { WsClientHandle } from "../../../../src/lib/ws/client/createWsClient";
import { resetShellState, setShellState } from "../../../../src/shell/bootstrap/store";
import type { ReadTimers } from "../../../../src/features/admin/overview/adminReads";
import {
  readDetail,
  readExport,
  readList,
  type MachineRef,
} from "../../../../src/features/admin/statecharts/inspectorReads";
import {
  createInspectorStore,
  inspector,
  type InspectorStore,
} from "../../../../src/features/admin/statecharts/inspectorStore";
import { MachineView } from "../../../../src/features/admin/statecharts/MachineView";
import {
  frozenExport,
  KILL_SWITCH_DETAIL,
  KILL_SWITCH_EXPORT,
  LATCHED_DETAIL,
  LATCHED_KEY,
  ORDER_EXPORT,
  ORDER_HASH,
} from "./fixtures";

// axe-core is a transitive dependency of @axe-core/playwright (as in AdminArea.test.tsx).
const axe = createRequire(createRequire(import.meta.url).resolve("@axe-core/playwright"))(
  "axe-core",
) as { run: (el: Element, o?: object) => Promise<{ violations: { impact?: string | null }[] }> };

const LATCHED: MachineRef = { key: LATCHED_KEY, env: "demo" };
const KILL_SWITCH: MachineRef = { key: "kill_switch", env: "demo" };
const DETAIL = `/api/v1/admin/statecharts/${encodeURIComponent(LATCHED_KEY)}?environment=demo`;
const EXPORT = "/api/v1/admin/statecharts/order/export";
const KS_DETAIL = "/api/v1/admin/statecharts/kill_switch?environment=demo";
const KS_EXPORT = "/api/v1/admin/statecharts/kill_switch/export";
/** The answer's clock: the day of the world's snapshots, so their times show no date. */
const NOW = Date.parse("2026-10-15T18:00:06Z");
const REASON = "Acknowledging isn't built yet.";

const TIMERS: ReadTimers = {
  setTimeout: (run, ms) => globalThis.setTimeout(run, ms),
  clearTimeout: (handle) => globalThis.clearTimeout(handle as ReturnType<typeof setTimeout>),
};

type Reply = { readonly status?: number; readonly body: unknown } | "hang";
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
      return new Response(JSON.stringify(reply.body), {
        status: reply.status ?? 200,
        headers: { "Content-Type": "application/json" },
      });
    }),
  );
  return requests;
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

/** The view as the shell holds it: the shell's gated announcement is a no-op (#5135). */
function show(
  machine: MachineRef = LATCHED,
  options: { readonly focusOnOpen?: boolean; readonly store?: InspectorStore } = {},
) {
  const store = options.store ?? storeFor();
  const onBack = vi.fn();
  const view = render(
    <GatedAnnounceProvider announce={() => undefined}>
      <main>
        <MachineView
          machine={machine}
          onBack={onBack}
          store={store}
          focusOnOpen={options.focusOnOpen ?? false}
        />
      </main>
      <ShellAnnouncer />
    </GatedAnnounceProvider>,
  );
  return { store, onBack, view };
}

const WORLD: Readonly<Record<string, Reply>> = {
  [DETAIL]: { body: LATCHED_DETAIL },
  [EXPORT]: { body: ORDER_EXPORT },
};
const WAIT = { timeout: 5_000 } as const;
const region = (): HTMLElement => screen.getByRole("region", { name: /^order:0a000000/ });
/** The view once its chart's text list is drawn. */
const settled = async (): Promise<HTMLElement> => {
  await screen.findByRole("heading", { name: "Transitions" }, WAIT);
  return region();
};

/** What assistive technology reads: the text without its `aria-hidden` parts. */
function spoken(node: Element): string {
  const copy = node.cloneNode(true) as Element;
  copy.querySelectorAll('[aria-hidden="true"]').forEach((hidden) => hidden.remove());
  return (copy.textContent ?? "").replace(/\s+/g, " ").trim();
}
/** A list item's own words, without its children's list. */
function own(item: Element): string {
  const copy = item.cloneNode(true) as Element;
  copy.querySelectorAll("ul").forEach((list) => list.remove());
  return (copy.textContent ?? "").trim();
}
/** The facts as term and value pairs, as read. */
function facts(root: HTMLElement): [string, string][] {
  return [...root.querySelectorAll("dl > div")].map((pair) => [
    pair.querySelector("dt")?.textContent ?? "",
    spoken(pair.querySelector("dd") as Element),
  ]);
}
const polite = (): HTMLElement | null =>
  document.querySelector<HTMLElement>('[aria-live="polite"] p');

beforeEach(() => {
  denials.length = 0;
  clearAnnouncements();
});

afterEach(() => {
  clearAnnouncements();
  inspector.reset();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe(
  "the latched order (SC-CHAIN-TRIPS): SI-3, SI-4, SI-5 and SI-7 today",
  { timeout: 30_000 },
  () => {
    it("test_machine_view_while_loading_is_busy_takes_focus_and_tears_down", async () => {
      const requests = serve({ [DETAIL]: "hang" });
      const { view } = show(LATCHED, { focusOnOpen: true });
      const heading = screen.getByRole("heading", { level: 2 });
      expect(heading).toHaveTextContent(`${LATCHED_KEY} · DEMO`);
      expect(heading).toHaveFocus();
      expect(region()).toHaveAttribute("aria-busy", "true");
      expect(requests.map((r) => r.path)).toEqual([DETAIL]);
      view.unmount();
      await waitFor(() => expect(requests[0]?.signal?.aborted).toBe(true), WAIT);
    });

    it("test_machine_view_shows_the_served_facts_without_deriving_any", async () => {
      serve(WORLD);
      show();
      const root = await settled();
      expect(root).not.toHaveAttribute("aria-busy");
      expect(facts(root)).toEqual([
        ["Kind", "order (B1)"],
        ["Environment", "DEMO"],
        ["State", "triggered"],
        ["Hash", `${LATCHED_DETAIL.machine.machine_hash} · matches the lock`],
        ["Chain trips", "2"],
        ["Latched", "Latched — chain trips: 2"],
        ["Deferred", "2"],
        ["Updated", "18:00:02 UTC"],
      ]);
      // The octagon is a glyph beside the words, never the only signal.
      const latched = root.querySelectorAll("dl > div")[5] as Element;
      expect(latched.querySelector('svg[aria-hidden="true"]')).not.toBeNull();
    });

    it("test_machine_view_text_list_marks_the_configurations_leaves_current", async () => {
      serve(WORLD);
      show();
      const root = await settled();
      const items = within(root).getAllByRole("listitem").map(own);
      expect(items.filter((words) => words.includes("(current)"))).toEqual([
        "triggered (current)",
        "sl_present (current)",
      ]);
    });

    it("test_machine_view_draws_the_chart_beside_its_text_list_marking_the_same_states", async () => {
      serve(WORLD);
      show();
      const root = await settled();
      const drawing = within(root).getByRole("region", { name: "State diagram: order (B1)" });
      const image = within(drawing).getByRole("img");
      const list = document.getElementById(image.getAttribute("aria-details") ?? "");
      expect(list).toContainElement(within(root).getByRole("heading", { name: "States" }));
      const marked = [...image.querySelectorAll("rect[data-current]")].map(
        (rect) => rect.parentElement?.querySelector("text")?.textContent,
      );
      expect(marked).toEqual(["triggered", "sl_present"]);
    });

    it("test_machine_view_timeline_lists_events_newest_first_faulted_in_words", async () => {
      serve(WORLD);
      show();
      const root = await settled();
      const table = within(root).getByRole("table", { name: "Events, newest first" });
      const rows = within(table)
        .getAllByRole("row")
        .slice(1)
        .map((row) => within(row).getAllByRole("cell").map(spoken));
      expect(rows).toEqual([
        [
          "18:00:01 UTC",
          "PRICE_TRIGGERED",
          "commit",
          "lifecycle.submitted, protection.sl_present to lifecycle.triggered, protection.sl_present",
          "",
        ],
        ["17:59:58 UTC", "FILL", "fault", "lifecycle.submitted to lifecycle.submitted", "faulted"],
        ["2026-10-14 23:59:57 UTC", "SUBMITTED", "ahead", "lifecycle.submitting to none", ""],
      ]);
    });

    it("test_machine_view_timeline_gives_its_narrow_columns_widths_and_wraps_from_to", async () => {
      // A parallel chart's "From → to" is long: it wraps, never cut, beside fixed narrow columns.
      serve(WORLD);
      show();
      const root = await settled();
      const table = within(root).getByRole("table", { name: "Events, newest first" });
      const widths = [...table.querySelectorAll("col")].map((col) => col.style.width);
      expect(widths).toEqual(["17em", "15em", "6em", "", "6em"]);
      const fromTo = within(table).getAllByRole("row")[1]?.querySelectorAll("td")[3];
      expect(fromTo?.querySelector<HTMLElement>("span[style]")?.style.whiteSpace).toBe("normal");
    });

    it("test_machine_view_acknowledge_is_t2_focusable_described_and_names_the_machine", async () => {
      serve(WORLD);
      show();
      await settled();
      const ack = screen.getByRole("button", { name: /Acknowledge latch/ });
      // The lock leads the full label (G-T2.1d), and the name names the machine (the ticket's a11y note).
      expect(ack).toHaveAccessibleName(
        new RegExp(`^Not available ?Acknowledge latch on ${LATCHED_KEY}…$`),
      );
      expect(ack).toHaveAttribute("aria-disabled", "true");
      expect(ack).not.toBeDisabled();
      expect(ack).toHaveAccessibleDescription(REASON);
      const reason = document.getElementById(ack.getAttribute("aria-describedby") ?? "");
      expect(reason).toHaveTextContent(REASON);
      expect(seenLabel(ack)).toBe("Acknowledge latch…");
    });

    it("test_machine_view_acknowledge_press_sends_nothing_and_says_its_reason_per_press", async () => {
      const requests = serve(WORLD);
      show();
      await settled();
      const asked = requests.length;
      const ack = screen.getByRole("button", { name: /Acknowledge latch/ });
      ack.focus();
      // Enter and Space reach a native button as a click; a held Enter's repeats are CMP-001's to drop.
      fireEvent.click(ack);
      await waitFor(() => expect(polite()).toHaveTextContent(REASON), WAIT);
      const first = polite()?.dataset["seq"];
      fireEvent.click(ack);
      await waitFor(() => expect(polite()?.dataset["seq"]).not.toBe(first), WAIT);
      expect(polite()).toHaveTextContent(REASON);
      expect(ack).toHaveFocus();
      expect(requests).toHaveLength(asked);
      expect(requests.every((r) => r.method === "GET")).toBe(true);
    });
  },
);

/** The label a sighted user reads: the visually hidden words and the named lock left out. */
function seenLabel(button: HTMLElement): string {
  const copy = button.cloneNode(true) as HTMLElement;
  copy.querySelectorAll(".cv-visually-hidden, [role='img']").forEach((node) => node.remove());
  return (copy.textContent ?? "").trim();
}

describe("§5.2's states", { timeout: 30_000 }, () => {
  it("test_machine_view_an_unlatched_machine_has_no_acknowledge", async () => {
    serve({ [KS_DETAIL]: { body: KILL_SWITCH_DETAIL }, [KS_EXPORT]: { body: KILL_SWITCH_EXPORT } });
    show(KILL_SWITCH);
    const root = await screen.findByRole("region", { name: "kill_switch · DEMO" }, WAIT);
    await within(root).findByRole("heading", { name: "Transitions" }, WAIT);
    expect(within(root).queryByRole("button", { name: /Acknowledge/ })).toBeNull();
    expect(facts(root)).toContainEqual(["Latched", "Not latched"]);
    expect(facts(root)).toContainEqual(["Kind", "kill_switch (B18)"]);
    expect(
      within(root)
        .getAllByRole("listitem")
        .map((item) => item.textContent),
    ).toContain("clear (initial) (current)");
  });

  it.each([
    ["latched with no trip", { degraded: true, chain_trips: 0 }, "Latched — chain trips: 0", true],
    ["tripped but not latched", { degraded: false, chain_trips: 3 }, "Not latched", false],
  ])(
    "test_machine_view_reads_the_served_latch_never_chain_trips_%s",
    async (_name, patch, latched, acknowledge) => {
      // C-2.21: the latch is `degraded` as served, whatever `chain_trips` says (C-1137-05 (e)).
      const machine = { ...LATCHED_DETAIL.machine, ...patch };
      serve({ ...WORLD, [DETAIL]: { body: { ...LATCHED_DETAIL, machine } } });
      show();
      const root = await settled();
      expect(facts(root)).toContainEqual(["Chain trips", String(patch.chain_trips)]);
      expect(facts(root)).toContainEqual(["Latched", latched]);
      const ack = within(root).queryByRole("button", { name: /Acknowledge latch/ });
      expect(ack !== null).toBe(acknowledge);
    },
  );

  it("test_machine_view_a_hash_off_the_lock_reads_differs_in_words", async () => {
    const machine = { ...LATCHED_DETAIL.machine, lock_matches: false };
    serve({ ...WORLD, [DETAIL]: { body: { ...LATCHED_DETAIL, machine } } });
    show();
    const root = await settled();
    expect(facts(root)).toContainEqual(["Hash", `${machine.machine_hash} · differs`]);
  });

  it("test_machine_view_a_null_deferred_depth_reads_not_recorded", async () => {
    const machine = { ...LATCHED_DETAIL.machine, deferred_depth: null };
    serve({ ...WORLD, [DETAIL]: { body: { ...LATCHED_DETAIL, machine } } });
    show();
    const root = await settled();
    expect(facts(root)).toContainEqual(["Deferred", "not recorded"]);
    const deferred = root.querySelectorAll("dl > div dd")[6] as Element;
    expect(deferred.textContent).toBe("—not recorded");
  });

  it.each([
    [
      "error",
      "snapshot seal did not verify",
      "A snapshot's seal didn't verify, so its machine isn't listed.",
    ],
    ["unavailable", "snapshots: no provider wired", "Machine snapshots can't be read right now."],
    ["error", "snapshots timed out after 300 ms", "Machine snapshots can't be read right now."],
  ])(
    "test_machine_view_snapshots_%s_with_%s_shows_its_line_and_no_facts",
    async (status, detail, line) => {
      // A machine served beside a snapshot not read `ok` is never shown (22: machine fields only
      // with `snapshots` `ok`).
      const body = { snapshots: { status, detail }, machine: LATCHED_DETAIL.machine };
      const requests = serve({ [DETAIL]: { body } });
      show();
      expect(await screen.findByText(line, {}, WAIT)).toBeInTheDocument();
      expect(region().querySelector("dl")).toBeNull();
      expect(screen.queryByRole("heading", { name: "States" })).toBeNull();
      expect(requests.map((r) => r.path)).toEqual([DETAIL]); // no chart without a served machine
    },
  );

  it.each([
    [404, "This machine isn't listed. It may have stopped, or it isn't visible to you."],
    [501, "Machine details aren't available on this server."],
  ])("test_machine_view_a_%i_reads_its_line_with_back_to_machines", async (status, line) => {
    serve({ [DETAIL]: { status, body: { code: "x" } } });
    const { onBack } = show();
    expect(await screen.findByText(line, {}, WAIT)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Back to machines" }));
    expect(onBack).toHaveBeenCalledTimes(1);
  });

  it("test_machine_view_a_failed_read_offers_retry_and_reads_again", async () => {
    const requests = serve({ [DETAIL]: { status: 503, body: { code: "unavailable" } } });
    show();
    expect(
      await screen.findByText("This machine can't be read right now.", {}, WAIT),
    ).toBeVisible();
    const again = serve(WORLD);
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    const root = await settled();
    expect(facts(root)[0]).toEqual(["Kind", "order (B1)"]);
    expect(screen.queryByText("This machine can't be read right now.")).toBeNull();
    expect(requests.map((r) => r.path)).toEqual([DETAIL]);
    expect(again.map((r) => r.path)).toEqual([DETAIL, EXPORT]);
  });

  it("test_machine_view_an_unusable_chart_keeps_the_facts_and_timeline_and_retries", async () => {
    serve({ [DETAIL]: { body: LATCHED_DETAIL } });
    show();
    expect(await screen.findByText("The chart can't be read right now.", {}, WAIT)).toBeVisible();
    expect(facts(region())).toHaveLength(8);
    expect(screen.getByRole("table", { name: "Events, newest first" })).toBeInTheDocument();
    serve(WORLD);
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await settled();
    expect(screen.queryByText("The chart can't be read right now.")).toBeNull();
  });

  it("test_machine_view_a_changed_chart_marks_no_current_state_and_offers_reread", async () => {
    const other = frozenExport("B01.order", "order", "d".repeat(64));
    const requests = serve({ ...WORLD, [EXPORT]: { body: other } });
    show();
    const root = await settled();
    expect(within(root).getByText("This chart changed since the machine was read.")).toBeVisible();
    expect(root.textContent).not.toContain("(current)");
    fireEvent.click(within(root).getByRole("button", { name: "Re-read" }));
    await waitFor(() => expect(requests.filter((r) => r.path === DETAIL)).toHaveLength(2), WAIT);
    expect(requests.some((r) => r.path.includes("?limit="))).toBe(false); // no page holds a list
  });

  it("test_machine_view_a_changed_chart_draws_no_current_state_either", async () => {
    const other = frozenExport("B01.order", "order", "d".repeat(64));
    serve({ ...WORLD, [EXPORT]: { body: other } });
    show();
    const root = await settled();
    const drawing = within(root).getByRole("region", { name: "State diagram: order (B1)" });
    expect(within(drawing).getByRole("img").querySelectorAll("[data-current]")).toHaveLength(0);
  });

  it("test_machine_view_a_chart_over_the_drawings_bounds_is_its_list_alone", async () => {
    const states = Object.fromEntries(Array.from({ length: 41 }, (_, i) => [`s${i}`, {}]));
    const big = {
      machine_kind: "order",
      machine_hash: ORDER_HASH,
      stately: { id: "order", initial: "s0", states },
    };
    serve({ ...WORLD, [EXPORT]: { body: big } });
    show();
    const root = await settled();
    expect(
      within(root).getByText("This chart is too large to draw here; the list below is complete."),
    ).toBeVisible();
    expect(within(root).queryByRole("region", { name: /^State diagram/ })).toBeNull();
    expect(within(root).getAllByRole("listitem").length).toBeGreaterThanOrEqual(41);
  });

  it("test_machine_view_timeline_unavailable_and_empty_say_so", async () => {
    serve({ ...WORLD, [DETAIL]: { body: { ...LATCHED_DETAIL, events: { status: "error" } } } });
    show();
    expect(await screen.findByText("Events can't be read right now.", {}, WAIT)).toBeVisible();
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("test_machine_view_no_recorded_events_says_so_without_a_table", async () => {
    serve({ ...WORLD, [DETAIL]: { body: { ...LATCHED_DETAIL, recent_events: [] } } });
    show();
    expect(await screen.findByText("No events recorded yet.", {}, WAIT)).toBeVisible();
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("test_machine_view_a_withdrawn_area_shows_nothing_and_asks_once", async () => {
    const requests = serve({ [DETAIL]: { status: 403, body: { instance: "urn:cv:req:9" } } });
    const { view } = show();
    await waitFor(() => expect(denials).toEqual(["urn:cv:req:9"]), WAIT);
    expect(view.container.querySelector("section")).toBeNull();
    expect(requests).toHaveLength(1);
  });
});

describe("tab order, focus and axe", { timeout: 60_000 }, () => {
  it("test_machine_view_tab_order_is_back_then_acknowledge_then_nothing_else", async () => {
    serve(WORLD);
    show();
    const root = await settled();
    const stops = [...root.querySelectorAll<HTMLElement>("button, a[href], [tabindex]")].filter(
      (node) => node.tabIndex >= 0,
    );
    expect(stops).toEqual([
      screen.getByRole("button", { name: "Back to machines" }),
      screen.getByRole("button", { name: /Acknowledge latch/ }),
    ]);
    // The heading takes focus only by script (tabindex -1); the text list is not a stop.
    expect(screen.getByRole("heading", { level: 2 })).toHaveAttribute("tabindex", "-1");
  });

  it("test_machine_view_tab_order_takes_the_diagram_then_the_timeline_while_they_scroll", async () => {
    vi.stubGlobal("ResizeObserver", undefined); // each region measured once, on mount
    vi.spyOn(HTMLElement.prototype, "scrollWidth", "get").mockReturnValue(900);
    vi.spyOn(HTMLElement.prototype, "clientWidth", "get").mockReturnValue(400);
    serve(WORLD);
    show();
    const root = await settled();
    const stops = (): HTMLElement[] =>
      [...root.querySelectorAll<HTMLElement>("button, a[href], [tabindex]")].filter(
        (node) => node.tabIndex >= 0,
      );
    // Each region measures itself after its commit: the stops are read once both have.
    await waitFor(
      () =>
        expect(stops()).toEqual([
          screen.getByRole("button", { name: "Back to machines" }),
          screen.getByRole("button", { name: /Acknowledge latch/ }),
          screen.getByRole("region", { name: "State diagram: order (B1)" }),
          screen.getByRole("region", { name: "Events, newest first" }),
        ]),
      WAIT,
    );
  });

  it("test_machine_view_without_focus_on_open_leaves_focus_where_it_was", async () => {
    serve(WORLD);
    show();
    await settled();
    expect(screen.getByRole("heading", { level: 2 })).not.toHaveFocus();
  });

  it("test_machine_view_uses_the_inspectors_own_store_by_default", async () => {
    const requests = serve(WORLD);
    render(<MachineView machine={LATCHED} onBack={() => undefined} />);
    await settled();
    expect(inspector.getState().machine.ref).toEqual(LATCHED);
    expect(requests.map((r) => r.path)).toEqual([DETAIL, EXPORT]);
  });

  it.each(["dark", "light"])(
    "test_machine_view_has_no_serious_axe_violation_in_%s",
    async (theme) => {
      document.documentElement.setAttribute("data-theme", theme);
      serve(WORLD);
      show();
      await settled();
      // jsdom has no layout: contrast is the real-browser collectors' (e2e/a11y).
      const res = await axe.run(document.body, { rules: { "color-contrast": { enabled: false } } });
      document.documentElement.removeAttribute("data-theme");
      expect(
        res.violations.filter((v) => v.impact === "serious" || v.impact === "critical"),
      ).toEqual([]);
    },
  );
});

describe(
  "an inline Re-read or Retry: focus stays while it exists, then waits on the heading (A-1137-02)",
  { timeout: 30_000 },
  () => {
    const heading = (): HTMLElement => screen.getByRole("heading", { level: 2 });
    /** A press on `button` from focus, as Enter on a native button gives. */
    const press = (button: HTMLElement): void => {
      act(() => button.focus());
      fireEvent.click(button);
    };

    it("test_machine_view_the_machines_retry_leaves_focus_on_its_heading_and_says_it_loaded", async () => {
      serve({ [DETAIL]: { status: 503, body: { code: "unavailable" } } });
      show();
      const retry = await screen.findByRole("button", { name: "Retry" }, WAIT);
      serve(WORLD);
      press(retry);
      await settled();
      expect(document.activeElement).not.toBe(document.body);
      expect(heading()).toHaveFocus();
      await waitFor(() => expect(polite()).toHaveTextContent("The machine loaded."), WAIT);
    });

    it("test_machine_view_the_charts_retry_leaves_focus_on_its_heading_and_says_it_loaded", async () => {
      serve({ [DETAIL]: { body: LATCHED_DETAIL } });
      show();
      const retry = await screen.findByRole("button", { name: "Retry" }, WAIT);
      serve(WORLD);
      press(retry);
      await settled();
      expect(document.activeElement).not.toBe(document.body);
      expect(heading()).toHaveFocus();
      await waitFor(() => expect(polite()).toHaveTextContent("The chart loaded."), WAIT);
    });

    it("test_machine_view_a_machines_retry_that_fails_again_keeps_focus_on_it", async () => {
      const requests = serve({ [DETAIL]: { status: 503, body: { code: "unavailable" } } });
      const { store } = show();
      const retry = await screen.findByRole("button", { name: "Retry" }, WAIT);
      press(retry);
      // The read fails again: the same Retry stays, and so does focus (A-1137-d04).
      await waitFor(() => {
        expect(requests.filter((r) => r.path === DETAIL)).toHaveLength(2);
        expect(store.getState().machine.inFlight).toBe(false);
      }, WAIT);
      expect(screen.getByRole("button", { name: "Retry" })).toBe(retry);
      expect(retry).toHaveFocus();
    });

    it("test_machine_view_a_charts_retry_that_fails_again_keeps_focus_on_it", async () => {
      const requests = serve({ [DETAIL]: { body: LATCHED_DETAIL } });
      const { store } = show();
      const retry = await screen.findByRole("button", { name: "Retry" }, WAIT);
      press(retry);
      // Its error and Retry stay while the chart is read again, and after it fails again.
      await waitFor(() => {
        expect(requests.filter((r) => r.path === EXPORT)).toHaveLength(2);
        expect(store.getState().machine.chart?.phase).toBe("unusable");
      }, WAIT);
      expect(screen.getByRole("button", { name: "Retry" })).toBe(retry);
      expect(retry).toHaveFocus();
    });

    it("test_machine_view_the_changed_charts_reread_leaves_focus_on_its_heading", async () => {
      const other = "d".repeat(64);
      const otherExport = frozenExport("B01.order", "order", other);
      serve({ ...WORLD, [EXPORT]: { body: otherExport } });
      show();
      const root = await settled();
      const reread = within(root).getByRole("button", { name: "Re-read" });
      // The machine was redeployed: its detail now names the export's hash, so the line goes.
      const moved = {
        ...LATCHED_DETAIL,
        machine: { ...LATCHED_DETAIL.machine, machine_hash: other },
      };
      serve({ [DETAIL]: { body: moved }, [EXPORT]: { body: otherExport } });
      press(reread);
      await waitFor(
        () =>
          expect(
            within(root).queryByText("This chart changed since the machine was read."),
          ).toBeNull(),
        WAIT,
      );
      expect(document.activeElement).not.toBe(document.body);
      expect(heading()).toHaveFocus();
    });
  },
);

/** The latched order as its topic publishes it (`23` §15.10), with `patch`. */
const published = (patch: Readonly<Record<string, unknown>> = {}) => ({
  machine_kind: "order",
  state: "triggered",
  regions: { lifecycle: "triggered", protection: "sl_present" },
  tags: ["protected"],
  degraded: true,
  machine_hash: ORDER_HASH,
  environment: "demo",
  updated_at_ms: Date.parse("2026-10-15T18:00:09Z"),
  ...patch,
});
const frameOf = (p: unknown): TopicFrame => ({
  kind: "d",
  seq: 1,
  ts: 0,
  sp: undefined,
  decodeMs: 0,
  size: 0,
  meta: undefined,
  body: { e: "j", p },
});

/** The shell's client, one handle per topic, and the display's frames run by the test. */
function liveWorld(environment: "demo" | "live" = "demo") {
  const queues: TopicFrame[][] = [];
  const specs: ConsumerSpec[] = [];
  const client = {
    consume: (spec: ConsumerSpec): TopicHandle => {
      specs.push(spec);
      const queue: TopicFrame[] = [];
      queues.push(queue);
      return {
        ch: spec.ch,
        status: "live",
        effective: {},
        source: "live",
        rs: undefined,
        read: () => queue.splice(0),
        release: () => undefined,
      };
    },
  };
  const callbacks: ((t: number) => void)[] = [];
  vi.stubGlobal("requestAnimationFrame", (callback: (t: number) => void) =>
    callbacks.push(callback),
  );
  vi.stubGlobal("cancelAnimationFrame", () => undefined);
  setShellState({ environment });
  act(() => setActiveClient(client as unknown as WsClientHandle));
  /** Publishes `p` and runs one animation frame. */
  const publish = (p: unknown): void =>
    act(() => {
      queues[0]?.push(frameOf(p));
      for (const callback of callbacks.splice(0)) callback(0);
    });
  return { specs, publish };
}

const assertive = (): HTMLElement | null =>
  document.querySelector<HTMLElement>('[aria-live="assertive"] p');

describe("the live state (BQ-7, §3.4)", { timeout: 30_000 }, () => {
  afterEach(() => {
    act(() => setActiveClient(null));
    resetShellState();
  });

  it("test_machine_view_a_live_state_that_differs_is_a_line_with_reread_never_a_read", async () => {
    const { specs, publish } = liveWorld();
    const requests = serve(WORLD);
    show();
    const root = await settled();
    expect(specs.map((s) => s.ch)).toEqual([`machines.${LATCHED_KEY}.state`]);
    const asked = requests.length;
    publish(published({ state: "filled" }));
    const line = within(root).getByText(
      /^Live: filled at 18:00:09 UTC\. The saved snapshot shows triggered\./,
    );
    expect(requests).toHaveLength(asked); // a frame never reads
    expect(polite()).toBeNull(); // nor is it said
    fireEvent.click(within(line).getByRole("button", { name: "Re-read" }));
    await waitFor(() => expect(requests.filter((r) => r.path === DETAIL)).toHaveLength(2), WAIT);
  });

  it("test_machine_view_the_latch_seen_live_is_a_line_and_said_once_assertively", async () => {
    const { publish } = liveWorld();
    const clear = { ...LATCHED_DETAIL.machine, degraded: false, chain_trips: 0 };
    serve({ ...WORLD, [DETAIL]: { body: { ...LATCHED_DETAIL, machine: clear } } });
    show();
    const root = await settled();
    publish(published());
    // The saved side says what differs: the latch, which it shows clear (A-1137-14).
    expect(
      within(root).getByText(
        /^Live: triggered, latched at 18:00:09 UTC\. The saved snapshot shows it clear\./,
      ),
    ).toBeVisible();
    await waitFor(() => expect(assertive()).toHaveTextContent(`${LATCHED_KEY} latched.`), WAIT);
  });

  it("test_machine_view_a_live_state_and_latch_that_differ_say_both_sides", async () => {
    const { publish } = liveWorld();
    const clear = { ...LATCHED_DETAIL.machine, degraded: false, chain_trips: 0 };
    serve({ ...WORLD, [DETAIL]: { body: { ...LATCHED_DETAIL, machine: clear } } });
    show();
    const root = await settled();
    publish(published({ state: "filled" }));
    expect(
      within(root).getByText(
        /^Live: filled, latched at 18:00:09 UTC\. The saved snapshot shows triggered, clear\./,
      ),
    ).toBeVisible();
  });

  it("test_machine_view_the_live_lines_reread_leaves_focus_on_its_heading", async () => {
    const { publish } = liveWorld();
    serve(WORLD);
    show();
    const root = await settled();
    publish(published({ state: "filled" }));
    const reread = within(root).getByRole("button", { name: "Re-read" });
    // The snapshot caught up: the re-read serves the live state, so the line and its button go.
    const caught = { ...LATCHED_DETAIL, machine: { ...LATCHED_DETAIL.machine, state: "filled" } };
    serve({ ...WORLD, [DETAIL]: { body: caught } });
    act(() => reread.focus());
    fireEvent.click(reread);
    await waitFor(() => expect(within(root).queryByText(/^Live:/)).toBeNull(), WAIT);
    expect(document.activeElement).not.toBe(document.body);
    expect(screen.getByRole("heading", { level: 2 })).toHaveFocus();
  });

  it("test_machine_view_the_topics_latch_never_shows_a_clear", async () => {
    const { publish } = liveWorld();
    serve(WORLD);
    show();
    const root = await settled();
    publish(published({ degraded: false }));
    expect(within(root).queryByText(/^Live:/)).toBeNull();
    expect(facts(root)).toContainEqual(["Latched", "Latched — chain trips: 2"]);
  });

  it("test_machine_view_in_another_environment_subscribes_to_nothing", async () => {
    const { specs } = liveWorld("live");
    serve(WORLD);
    show();
    await settled();
    expect(specs).toEqual([]);
  });
});
