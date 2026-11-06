/** E16-S05: SCR-047 / SCR-151's block in the DOM (AC 1, 2, 3, 6, 7), its carriers, analytics, focus and axe. */
import { createRequire } from "node:module";
import { useRef, useState, type JSX } from "react";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const engine = vi.hoisted(() => ({ createChart: vi.fn() }));
vi.mock("@candleviewer/chart-engine", () => ({ createChart: engine.createChart }));

import {
  ChartEmptyState,
  ChartGapDescription,
  type ChartEmptyStateProps,
} from "../../../src/features/chart-empty/ChartEmptyState";
import * as F from "../../../src/features/chart-empty/fixtures";
import {
  selectChartState,
  type BarsAnswer,
  type ChartStateInput,
} from "../../../src/features/chart-empty/model";
import { THEME_ANALYTICS_EVENT } from "../../../src/shell/bootstrap/themeStore";

const axe = createRequire(createRequire(import.meta.url).resolve("@axe-core/playwright"))(
  "axe-core",
) as { run: (el: Element, o?: object) => Promise<{ violations: { impact?: string | null }[] }> };

type Row = Partial<ChartStateInput>;
const { at, OWNER, VIEWER, VIEWING_AS } = F;
const NEVER: Row = { symbol: "SOLUSDT", coverage: F.read(F.NEVER_COVERAGE) };
const RETENTION: Row = {
  window: { fromMs: at("2026-09-05T00:00:00Z"), toMs: at("2026-09-06T00:00:00Z") },
  coverage: F.read(F.RETENTION_COVERAGE),
};

function Block({ row, ...p }: Partial<ChartEmptyStateProps> & { row: Row }): JSX.Element {
  return (
    <ChartEmptyState
      state={selectChartState(F.input(row))}
      live="live"
      onAction={vi.fn()}
      onRetry={vi.fn()}
      {...p}
    />
  );
}
function mount(row: Row, over: Partial<ChartEmptyStateProps> = {}) {
  const props = { onAction: vi.fn(), onRetry: vi.fn(), report: vi.fn(), ...over };
  return { ...render(<Block row={row} {...props} />), ...props };
}

describe("AC 1: a never-recorded symbol explains, for the Owner", () => {
  it("states no recorded history, notes live data, offers Record this symbol → SCR-140", () => {
    const { onAction } = mount(NEVER);
    const name = "History starts when you record SOLUSDT — recording has not begun yet.";
    expect(screen.getByRole("heading", { level: 3, name })).toBeInTheDocument();
    expect(screen.getByText(/^Nothing is missing/, { selector: "p" })).toBeInTheDocument();
    const live = screen.getByText("Live data is streaming now.");
    expect(live.querySelector('[style*="data-confidence-live-indicator"] svg')).not.toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Record this symbol" }));
    expect(onAction).toHaveBeenCalledWith("record", "/admin/recorder"); // the registry's R-340
    fireEvent.click(screen.getByRole("button", { name: "Learn more" }));
    expect(onAction).toHaveBeenLastCalledWith("learn_more", null);
  });

  it.each([
    ["delayed", "Live data is streaming at a reduced rate."],
    ["disconnected", "Live data will resume when the connection returns."],
    ["stale", null],
  ] as const)("the live sentence under %s", (live, words) => {
    mount(NEVER, { live });
    expect(screen.queryByText(/^Live data/)?.textContent ?? null).toBe(words);
  });
});

it("AC 2: the 422's recording_started_at is UTC text in the heading", () => {
  mount({ bars: { kind: "no_data_recorded", recordingStartedAtMs: at("2026-09-01T08:00:00Z") } });
  const name = "History starts 2026-09-01 08:00 UTC — recording began then.";
  expect(screen.getByRole("heading", { name })).toBeInTheDocument();
});

describe("AC 3: a non-owner gets an explanation, not a dead button", () => {
  it.each([
    ["Viewer", VIEWER, /Only the owner can change recording\.$/],
    ["view-as", VIEWING_AS, /Read-only while viewing as alex\.$/],
  ])("%s: no record button, the sentence", (_n, access, sentence) => {
    mount({ ...NEVER, access });
    expect(screen.queryByRole("button", { name: /Record/ })).toBeNull();
    expect(screen.getByText(sentence, { selector: "p" })).toBeInTheDocument();
    expect(screen.getAllByRole("button").map((b) => b.textContent)).toEqual(["Learn more"]);
  });
});

it("role-restricted: Show coverage is secondary, no CTA (D05 :225)", () => {
  mount({ roleRestricted: true });
  const button = screen.getByRole("button", { name: "Show coverage" });
  expect(button).toHaveAttribute("data-variant", "secondary");
});

describe("AC 6 and AC 7", () => {
  it("a coverage failure is the error state with Retry, not busy", () => {
    const { onRetry } = mount({ coverage: F.FAILED });
    expect(screen.getByText("Couldn't load recorded coverage.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(onRetry).toHaveBeenCalledTimes(1);
    expect(document.querySelector("[aria-busy]")).toBeNull();
  });

  it("first load is CMP-029 under aria-busy; populated and SCR-048 render nothing here", () => {
    const { container, unmount } = mount({ bars: { kind: "loading" } });
    expect(container.querySelector('[aria-busy="true"] [data-cmp="CMP-029"]')).not.toBeNull();
    expect(screen.queryByRole("heading")).toBeNull();
    unmount();
    expect(mount({ bars: { kind: "ok", count: 4 } }).container.innerHTML).toBe("");
    expect(mount({ bars: { kind: "failed" } }).container.innerHTML).toBe("");
  });

  it.each<[string, Row]>([
    ["never recorded", NEVER],
    ["a gap", {}],
    ["not trading", { instrumentStatus: "Closed" }],
    ["coverage failed", { coverage: F.FAILED }],
  ])("bootstrap-empty, %s: no canvas, no engine", (_n, row) => {
    mount(row);
    expect(document.querySelector("canvas")).toBeNull();
    expect(engine.createChart).not.toHaveBeenCalled();
  });
});

describe("announcements and analytics, once per entry", () => {
  it("says {heading} {cause} once and reports chart.empty_state_shown once", () => {
    const { report, rerender } = mount({});
    expect(screen.getByRole("status")).toHaveTextContent(
      "No bars for BTCUSDT 1m between 02:11 and 02:14 UTC. " +
        "Recording was interrupted (connection to the exchange lost).",
    );
    const reason = "no_data_in_range";
    const event = { name: "chart.empty_state_shown", reason, cause: "ws_disconnect" };
    expect(report).toHaveBeenCalledWith(event);
    rerender(<Block row={{}} live="delayed" report={report} />);
    expect(report).toHaveBeenCalledTimes(1);
  });

  it("a SCR-151 panel sends no chart event (its own is carried) and has its own heading", () => {
    const { report } = mount({ roleRestricted: true }, { surface: "history-panel" });
    expect(report).not.toHaveBeenCalled();
    const name = "No history is available for BTCUSDT here.";
    expect(screen.getByRole("heading", { name })).toBeInTheDocument();
  });

  it("the default reporter dispatches on the app's seam", () => {
    const seen = vi.fn();
    const listener = (e: Event): void => seen((e as CustomEvent).detail);
    window.addEventListener(THEME_ANALYTICS_EVENT, listener);
    render(<Block row={{ instrumentStatus: "Closed" }} />);
    window.removeEventListener(THEME_ANALYTICS_EVENT, listener);
    expect(seen).toHaveBeenCalledWith({
      name: "chart.empty_state_shown",
      reason: "symbol_delisted",
    });
  });
});

describe("FM-16: the first bar ends 1a while the block held focus", () => {
  const none = { kind: "no_data_recorded", recordingStartedAtMs: null } as const;
  const started = { kind: "no_data_recorded", recordingStartedAtMs: 5 } as const;
  function Host({ from = none, next }: { from?: BarsAnswer; next: BarsAnswer }): JSX.Element {
    const toolbar = useRef<HTMLButtonElement>(null);
    const [bars, setBars] = useState<BarsAnswer>(from);
    return (
      <>
        <button ref={toolbar} type="button">
          Toolbar
        </button>
        <button type="button" onClick={() => setBars(next)}>
          Next
        </button>
        <Block row={{ bars }} returnFocusTo={toolbar} />
      </>
    );
  }
  const focusIn = (): void => screen.getByRole("button", { name: "Record this symbol" }).focus();

  it.each([
    ["unmount, focus inside → the toolbar", false, "Toolbar"],
    ["unmount, focus already out → left alone", true, "Next"],
  ])("%s", (_n, leave, focused) => {
    render(<Host next={{ kind: "ok", count: 1 }} />);
    const next = screen.getByRole("button", { name: "Next" });
    act(focusIn);
    if (leave) act(() => next.focus());
    act(() => fireEvent.click(next));
    expect(screen.getByRole("button", { name: focused })).toHaveFocus();
  });

  it("a reason change while mounted (1b → 2) moves no focus", () => {
    render(<Host from={started} next={{ kind: "ok", count: 0 }} />);
    const coverage = screen.getByRole("button", { name: "Show coverage" });
    act(() => coverage.focus());
    act(() => fireEvent.click(screen.getByRole("button", { name: "Next" })));
    expect(screen.getByRole("heading", { name: /^No bars for BTCUSDT 1m between/ })).toBeVisible();
    expect(screen.getByRole("button", { name: "Show coverage" })).toHaveFocus();
  });
});

describe("the gap carriers (AC 4's text equivalent)", () => {
  it("the chart region's description lists the gaps; unknown coverage never says none", () => {
    const window = { fromMs: at("2026-09-04T00:00:00Z"), toMs: at("2026-09-04T06:00:00Z") };
    const coverage = F.read(F.AC4_COVERAGE);
    const state = selectChartState(F.input({ window, bars: { kind: "ok", count: 9 }, coverage }));
    const gaps = state.kind === "populated" ? state.gaps : [];
    const { rerender } = render(<ChartGapDescription id="d" gaps={gaps} coverageKnown />);
    const d = (): HTMLElement | null => document.getElementById("d");
    expect(d()).toHaveTextContent("Missing: 4 Sep 02:11–02:23 UTC, connection lost.");
    rerender(<ChartGapDescription id="d" gaps={[]} coverageKnown={false} />);
    expect(d()).toHaveTextContent("Couldn't load recorded coverage.");
    rerender(<ChartGapDescription id="d" gaps={[]} coverageKnown />);
    expect(d()).toBeEmptyDOMElement();
  });

  it("BQ-04: the field-present branch from the PROPOSED fixture adds the kline line (D05-G1)", () => {
    const window = { fromMs: at("2026-09-04T00:00:00Z"), toMs: at("2026-09-04T06:00:00Z") };
    const coverage = F.read(F.PROPOSED_BACKFILLED_COVERAGE);
    const state = selectChartState(F.input({ window, bars: { kind: "ok", count: 9 }, coverage }));
    const gaps = state.kind === "populated" ? state.gaps : [];
    render(<ChartGapDescription id="p" gaps={gaps} coverageKnown />);
    expect(document.getElementById("p")).toHaveTextContent(
      "connection lost (Bars from exchange klines; order flow missing.).",
    );
  });
});

it.each<[string, Row, typeof OWNER]>([
  ["owner", NEVER, OWNER],
  ["sentence form", NEVER, VIEWER],
  ["retention", RETENTION, OWNER],
  ["error", { coverage: F.FAILED }, OWNER],
])("axe: zero serious / critical (%s)", async (_n, row, access) => {
  mount({ ...row, access });
  const res = await axe.run(document.body, { rules: { "color-contrast": { enabled: false } } });
  const bad = res.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
  expect(bad).toEqual([]);
});
