// E24-S03 (#778) slice 1: the funding table alternative (D02 §11) on its own: the gap rows in words, the
// visible-range filter, the 200-row cap, "No settlements in view.", the tri-state sort with `aria-sort`, and
// the rate's sign as text.
import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { buildFundingSeries } from "../../../src/features/funding/series";
import { ratePercent } from "../../../src/features/funding/ui/format";
import {
  compareDecimal,
  FundingTable,
  MAX_TABLE_ROWS,
} from "../../../src/features/funding/ui/FundingTable";
import { recordedSettled } from "./support/fundingFixtures";

const H = 3_600_000;
const POINTS = recordedSettled("BTCUSDT_8h").map((i) => ({
  tMs: Date.parse(i.t),
  rate: i.funding_rate,
}));
const T = POINTS.map((p) => p.tMs);
const series = (gaps: { fromMs: number; toMs: number }[] = [], settled = POINTS) =>
  buildFundingSeries({ settled, intervalMinutes: 480, coverage: { noCoverage: false, gaps } });
const table = () => screen.getByRole("table", { name: "Funding rate, BTCUSDT, settled" });
const firstColumn = () =>
  within(table())
    .getAllByRole("row")
    .slice(1)
    .map((r) => within(r).getAllByRole("cell")[0]?.textContent);

describe("funding table (D02 §11)", () => {
  it("lists a missing settlement as a row in words, in time order", () => {
    const missing = POINTS.filter((_, i) => i !== 1);
    const gap = { fromMs: T[0] ?? 0, toMs: T[2] ?? 0 };
    render(<FundingTable symbol="BTCUSDT" series={series([gap], missing)} />);
    const rows = within(table()).getAllByRole("row");
    expect(rows).toHaveLength(5);
    const gapRow = rows[2];
    if (gapRow === undefined) throw new Error("no gap row");
    expect(within(gapRow).getByText("missing settlement · not recorded")).toBeTruthy();
    expect(within(gapRow).getAllByText("no rate")).toHaveLength(2); // rate and annualised
    expect(within(gapRow).getByText("2023-11-14 00:00 – 2023-11-14 16:00")).toBeTruthy();
  });

  it("keeps the rows in the chart's visible range only, and says when none is", () => {
    const visible = { fromMs: T[1] ?? 0, toMs: T[2] ?? 0 };
    const { unmount } = render(
      <FundingTable symbol="BTCUSDT" series={series()} visible={visible} />,
    );
    expect(firstColumn()).toEqual(["2023-11-14 08:00", "2023-11-14 16:00"]);
    unmount();
    render(
      <FundingTable
        symbol="BTCUSDT"
        series={series()}
        visible={{ fromMs: 0, toMs: 1 }}
        headingLevel={5}
      />,
    );
    expect(screen.getByRole("heading", { level: 5, name: "No settlements in view." })).toBeTruthy();
  });

  it("draws the newest 200 rows and names the cap in the caption (F4)", () => {
    const many = Array.from({ length: MAX_TABLE_ROWS + 50 }, (_, i) => ({
      tMs: i * 8 * H,
      rate: "0.0001",
    }));
    render(<FundingTable symbol="BTCUSDT" series={series([], many)} />);
    const name = "Funding rate, BTCUSDT, settled, showing the newest 200 of 250";
    expect(within(screen.getByRole("table", { name })).getAllByRole("row")).toHaveLength(201);
  });

  it("sorts by rate up, down, then back to time order, with aria-sort, gaps last", () => {
    const gap = { fromMs: (T[3] ?? 0) + 1, toMs: (T[3] ?? 0) + 9 * H };
    render(<FundingTable symbol="BTCUSDT" series={series([gap])} />);
    const button = within(table()).getByRole("button", { name: "Rate (% per interval)" });
    const header = () => button.closest("th")?.getAttribute("aria-sort");
    const rates = () =>
      within(table())
        .getAllByRole("row")
        .slice(1)
        .map((r) => within(r).getAllByRole("cell")[1]?.textContent);
    expect(header()).toBe("none");
    fireEvent.click(button);
    expect(header()).toBe("ascending");
    expect(rates()[0]).toContain("−0.0040 %");
    expect(rates()[4]).toContain("no rate");
    fireEvent.click(button);
    expect(header()).toBe("descending");
    expect(rates()[0]).toContain("+0.0120 %");
    expect(rates()[4]).toContain("no rate");
    fireEvent.click(button);
    expect(header()).toBe("none");
    expect(firstColumn()[0]).toBe("2023-11-14 00:00");
  });

  it("keeps the predicted row last whatever the sort, never among the settled ones", () => {
    const predicted = { tMs: (T[3] ?? 0) + 8 * H, rate: "-0.001", annualisedPct: null };
    const withNext = buildFundingSeries({
      settled: POINTS,
      intervalMinutes: 480,
      coverage: null,
      predicted,
    });
    render(<FundingTable symbol="BTCUSDT" series={withNext} />);
    const name = "Funding rate, BTCUSDT, settled and predicted (estimated)";
    const last = () => within(screen.getByRole("table", { name })).getAllByRole("row").at(-1);
    fireEvent.click(screen.getByRole("button", { name: "Rate (% per interval)" }));
    expect(last()?.textContent).toContain("predicted");
    fireEvent.click(screen.getByRole("button", { name: "Rate (% per interval)" }));
    expect(last()?.textContent).toContain("predicted");
  });

  it("orders decimals exactly, never through a float", () => {
    expect(compareDecimal("0.00010000000000000001", "0.0001")).toBe(1);
    expect(compareDecimal("-0.00004", "0.00004")).toBe(-1);
    expect(compareDecimal("-0.5", "-0.05")).toBe(-1);
    expect(compareDecimal("0.10", "0.1")).toBe(0);
  });

  it.each([
    ["0.0001", "+0.0100 %", "plus 0.0100 percent"],
    ["-0.00004", "−0.0040 %", "minus 0.0040 percent"],
    ["0.00006667", "+0.0067 %", "plus 0.0067 percent"],
    ["0", "0.0000 %", "0.0000 percent"],
    ["-0.005", "−0.5000 %", "minus 0.5000 percent"],
    ["0.000000004", "0.0000 %", "0.0000 percent"],
  ])("formats %s as %s", (rate, text, spoken) => {
    expect(ratePercent(rate)).toEqual({ text, spoken });
  });
});
