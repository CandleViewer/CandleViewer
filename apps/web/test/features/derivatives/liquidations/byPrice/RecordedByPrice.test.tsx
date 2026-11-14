// E24-S07 (#782) slice 2: the switch, the legend row and the table by role and name; the keyboard (a T2 switch stays
// focusable and changes nothing on Enter / Space); the badge from the flag; the coverage states; axe over every story.
import { createRequire } from "node:module";
import { fireEvent, render, screen, within } from "@testing-library/react";
import type { JSX } from "react";
import { describe, expect, it, vi } from "vitest";
import * as stories from "../../../../../src/features/derivatives/liquidations/byPrice/RecordedByPrice.stories";
import { ByPriceLegendRow } from "../../../../../src/features/derivatives/liquidations/byPrice/ByPriceLegendRow";
import { RecordedByPriceToggle } from "../../../../../src/features/derivatives/liquidations/byPrice/RecordedByPriceToggle";
import type { ToggleAccess } from "../../../../../src/features/derivatives/liquidations/byPrice/model";

// axe-core is a transitive dependency of @axe-core/playwright (already a devDependency).
const axe = createRequire(createRequire(import.meta.url).resolve("@axe-core/playwright"))(
  "axe-core",
) as { run: (el: Element, o?: object) => Promise<{ violations: { impact?: string | null }[] }> };

function mountSwitch(access: ToggleAccess, checked = false) {
  const onChange = vi.fn();
  const analytics = { toggled: vi.fn(), readFailed: vi.fn() };
  render(
    <div>
      <p id="notice">Read-only while viewing as alex.</p>
      <RecordedByPriceToggle {...{ access, checked, onChange, analytics }} symbol="BTCUSDT" />
    </div>,
  );
  const name = "Recorded liquidations by price · Not available to rules";
  return { onChange, analytics, sw: screen.getByRole("switch", { name }) };
}

describe("RecordedByPriceToggle", () => {
  it("is off by default and switches with no acknowledgement, saved", () => {
    const { sw, onChange, analytics } = mountSwitch({ kind: "persisted" });
    expect(sw.getAttribute("aria-checked")).toBe("false");
    sw.focus();
    expect(document.activeElement).toBe(sw);
    fireEvent.click(sw); // a native button's Space / Enter activation arrives as a click
    expect(onChange).toHaveBeenCalledWith(true, "persisted");
    expect(analytics.toggled).toHaveBeenCalledWith("BTCUSDT", true, "persisted");
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("switches for the session only for a Viewer (T1)", () => {
    const { sw, onChange } = mountSwitch({ kind: "session" }, true);
    expect(sw.getAttribute("aria-disabled")).toBeNull();
    fireEvent.click(sw);
    expect(onChange).toHaveBeenCalledWith(false, "session");
  });

  it("is T2 rbac.view_as under view-as: focusable, described by the one notice, inert", () => {
    const { sw, onChange, analytics } = mountSwitch({
      kind: "view-as",
      user: "alex",
      noticeId: "notice",
    });
    expect(sw.getAttribute("aria-disabled")).toBe("true");
    expect(sw.hasAttribute("disabled")).toBe(false);
    expect(sw.getAttribute("aria-describedby")).toContain("notice");
    // the notice form (one notice, many pointers) draws CMP-019 `lock` decoratively: the host's notice names the reason
    expect(sw.closest(".cv-choice")?.querySelector(".cv-choice__lock svg")).not.toBeNull();
    expect(screen.getAllByText("Read-only while viewing as alex.")).toHaveLength(1);
    sw.focus();
    expect(document.activeElement).toBe(sw);
    fireEvent.click(sw);
    expect(onChange).not.toHaveBeenCalled();
    expect(analytics.toggled).not.toHaveBeenCalled();
    expect(sw.getAttribute("aria-checked")).toBe("false");
  });
});

const legend = () => screen.getByRole("list", { name: "Price pane legend" });
const nameOf = () => within(legend()).getByRole("button", { name: /^Recorded liquidations/ });

describe("ByPriceLegendRow", () => {
  it("names the layer, its day and the rules exclusion, K01's sentence its description", () => {
    render(stories.Full.render());
    const label = "Recorded liquidations by price (today, UTC) · Not available to rules";
    expect(nameOf().textContent).toBe(label);
    const tip = document.getElementById(nameOf().getAttribute("aria-describedby") ?? "");
    expect(tip?.textContent).toBe(
      "Histogram of recorded liquidations by price level. Not a prediction.",
    );
    expect(legend().textContent).not.toMatch(/estimated/i);
  });

  it("draws the estimated word when, and only when, the flag is true", () => {
    render(stories.FlaggedEstimated.render());
    expect(nameOf().textContent).toContain("(estimated)");
  });

  it("shows the partial-coverage chip and sentence and makes no full-day claim", () => {
    render(stories.PartialCoverage.render());
    expect(nameOf().textContent).not.toContain("today");
    expect(within(legend()).getByText("since 06:30 UTC")).toBeTruthy();
    expect(legend().textContent).toContain("No history before 06:30 UTC. Bybit publishes no");
  });

  it("says a refused answer inside the polite status region", () => {
    render(stories.Refused.render());
    expect(within(legend()).getByRole("status").textContent).toBe(
      "The server's answer could not be read, so nothing is drawn.",
    );
  });

  it.each([
    ["NotRecorded", "Not recorded before 15 Sep 08:00 UTC — this is not 'no liquidations'"],
    ["NeverRecorded", "No liquidation history for BTCUSDT. Bybit publishes none"],
    ["NoneRecorded", "No liquidation was recorded since 00:00 UTC."],
    ["Loading", "Loading recorded liquidations by price…"],
    ["Refused", "The server's answer could not be read, so nothing is drawn."],
    ["Failed", "Couldn't load recorded liquidations by price"],
  ] as const)("%s says %s", (story, line) => {
    render(stories[story].render());
    expect(legend().textContent).toContain(line);
  });

  it("says stale in its status, offers Retry when failed, and renders nothing while off", () => {
    const { unmount } = render(stories.Stale.render());
    expect(within(legend()).getByRole("status").textContent).toBe("Stale 60s · last 10:59:00");
    unmount();
    const retry = vi.fn();
    const failed = render(stories.Failed.render());
    expect(
      within(legend()).getByRole("button", {
        name: "Retry loading recorded liquidations by price",
      }),
    ).toBeTruthy();
    expect(within(legend()).getByRole("status").textContent).toBe(
      "Couldn't load recorded liquidations by price",
    );
    failed.unmount();
    const off = stories.viewOf(null, { phase: "off", retry });
    const { container } = render(<ByPriceLegendRow view={off} nowMs={0} />);
    expect(container.innerHTML).toBe("");
  });
});

describe("ByPriceTable", () => {
  it("lists the served buckets largest first, units in the headers and the cells' names", () => {
    render(stories.Table.render());
    const name = "Recorded liquidations by price, BTCUSDT, top 2 buckets, largest first";
    const table = screen.getByRole("table", { name });
    expect(
      within(table)
        .getAllByRole("columnheader")
        .map((h) => h.textContent.trim()),
    ).toEqual([
      "From (USDT)",
      "To (USDT)",
      "Long liquidated (USDT)",
      "Short liquidated (USDT)",
      "Prints",
    ]);
    const first = within(table).getAllByRole("row")[1]?.textContent ?? "";
    expect(first).toContain("62,880.00 USDT");
    expect(first).toContain("202,473.60 USDT");
  });

  it("shows the host's empty state when nothing was recorded", () => {
    render(stories.TableEmpty.render());
    expect(screen.getByText(/this is not 'no liquidations'/)).toBeTruthy();
  });
});

describe("accessibility", () => {
  it.each(
    Object.entries(stories).filter(([, s]) => typeof s === "object" && s !== null && "render" in s),
  )(
    "story %s has no serious or critical axe violation",
    async (_name, story) => {
      render((story as { render: () => JSX.Element }).render());
      // jsdom has no canvas, so contrast is off here. These stories are not yet registered in
      // packages/ui/.storybook/main.ts, so no run checks their contrast today: slice 3 registers them.
      const res = await axe.run(document.body, { rules: { "color-contrast": { enabled: false } } });
      const bad = res.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
      expect(bad).toEqual([]);
    },
    30_000,
  );
});
