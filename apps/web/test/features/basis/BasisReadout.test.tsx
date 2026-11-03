// E24-S08 (#783) slice 1: the basis header readout by role: figures with units in the name, the sign as
// text, the source line and selector, the one polite announcement, and axe over every story.
import { createRequire } from "node:module";
import { fireEvent, render, screen, within } from "@testing-library/react";
import type { ReactElement } from "react";
import { describe, expect, it, vi } from "vitest";
import * as stories from "../../../src/features/basis/ui/BasisReadout.stories";
import { BasisReadout } from "../../../src/features/basis/ui/BasisReadout";
import { INITIAL_BASIS_SNAPSHOT } from "../../../src/features/basis/basisFeed";

// axe-core is a transitive dependency of @axe-core/playwright (already a devDependency).
const axe = createRequire(createRequire(import.meta.url).resolve("@axe-core/playwright"))(
  "axe-core",
) as {
  run: (
    el: Element,
    o?: object,
  ) => Promise<{ violations: { id: string; impact?: string | null }[] }>;
};

async function serious(): Promise<string[]> {
  // jsdom has no canvas; contrast is the Storybook / Playwright axe run's
  const res = await axe.run(document.body, { rules: { "color-contrast": { enabled: false } } });
  return res.violations
    .filter((v) => v.impact === "serious" || v.impact === "critical")
    .map((v) => v.id);
}

const group = () => screen.getByRole("group", { name: "Basis, BTCUSDT" });

describe("basis readout (CMP-036 rows)", () => {
  it("says mark, index and basis with units, the sign as text, and the source", () => {
    render(stories.SourceLast.render());
    const text = group().textContent ?? "";
    expect(text).toContain("82,751.20 USDT");
    expect(text).toContain("82,782.37 USDT");
    expect(text).toContain("−31.17 (−0.038 %)");
    expect(text).toContain("basis, last − index");
    expect(
      screen.getByText("minus 31.17 USDT, minus 0.038 percent, basis, last minus index"),
    ).toBeTruthy();
    expect(screen.getByText("82,751.20 USDT")).toBeTruthy();
  });

  it("states the active source: mark", () => {
    render(stories.SourceMark.render());
    expect(group().textContent).toContain("basis, mark − index");
    expect(screen.getByRole("radio", { name: "mark" }).getAttribute("aria-checked")).toBe("true");
  });

  it("draws a positive basis with a plus sign", () => {
    render(stories.PositiveBasis.render());
    expect(group().textContent).toContain("+7.63 (+0.009 %)");
  });

  it("reads missing values as words, never 0", () => {
    render(stories.WaitingForTicker.render());
    expect(within(group()).getAllByText("no value yet").length).toBeGreaterThan(0);
    expect(group().textContent).not.toMatch(/\b0\b/);
  });

  it("says when only the basis is missing (no mark for the mark source)", () => {
    render(stories.NoMark.render());
    expect(group().textContent).toContain("no basis for this source");
  });

  it("shows the stale chip with the last-good time", () => {
    render(stories.StaleT1.render());
    expect(group().textContent).toContain("last 09:14:02 UTC");
  });

  it("offers the source as a radiogroup, calls back and announces once, politely", () => {
    const onChange = vi.fn();
    render(
      <BasisReadout
        symbol="BTCUSDT"
        snapshot={INITIAL_BASIS_SNAPSHOT}
        source="last"
        onSourceChange={onChange}
      />,
    );
    const status = screen.getByRole("status");
    expect(status.textContent).toBe("");
    const picker = screen.getByRole("radiogroup", { name: "Basis source" });
    fireEvent.click(within(picker).getByRole("radio", { name: "mark" }));
    expect(onChange).toHaveBeenCalledWith("mark");
    expect(status.textContent).toBe("Basis source is now mark: basis, mark minus index.");
  });

  it("keeps the rows out of a live region: ticks are never announced", () => {
    render(stories.SourceLast.render());
    expect(group().querySelector("dl")?.getAttribute("aria-live")).toBe("off");
  });

  it("has no serious axe violation in any story", { timeout: 30_000 }, async () => {
    for (const story of Object.values(stories).filter(
      (v): v is { render: () => ReactElement } =>
        typeof v === "object" && v !== null && "render" in v,
    )) {
      const { unmount } = render(story.render());
      expect(await serious()).toEqual([]);
      unmount();
    }
  });
});
