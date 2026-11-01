/**
 * E29-S01 (#911, BQ-15) the placeholder tabs: CMP-026 with a level-2 title and one cause each; Trade
 * groups and Algos in the deck's and D02:166's words, Working orders and Fills PROPOSED (G-W3).
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { DECK, PROPOSED_TEXT } from "../../../src/features/positions/copy";
import {
  PlaceholderTab,
  type PlaceholderTabId,
} from "../../../src/features/positions/PlaceholderTab";

describe("PlaceholderTab", () => {
  it.each<[PlaceholderTabId, string, string]>([
    ["working_orders", PROPOSED_TEXT.workingOrdersTitle, PROPOSED_TEXT.workingOrdersCause],
    ["fills", PROPOSED_TEXT.fillsTitle, PROPOSED_TEXT.fillsCause],
    [
      "trade_groups",
      DECK["blotter.ui.tab.trade_groups"].string,
      "Grouped orders across accounts will be listed here.",
    ],
    ["algos", DECK["blotter.ui.tab.algos"].string, "Running algorithms will be listed here."],
  ])("%s: its title and cause, no action", (tab, title, cause) => {
    const { container } = render(<PlaceholderTab tab={tab} />);
    expect(screen.getByRole("heading", { level: 2, name: title })).toBeInTheDocument();
    expect(screen.getByText(cause)).toBeInTheDocument();
    expect(container.querySelector('[data-cmp="CMP-026"]')).toHaveAttribute(
      "data-variant",
      "no-data",
    );
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("the PROPOSED titles follow the deck's pattern and are not deck strings", () => {
    const deck = Object.values(DECK).map((e) => e.string);
    for (const text of [PROPOSED_TEXT.workingOrdersTitle, PROPOSED_TEXT.fillsTitle]) {
      expect(text).toMatch(/ are not available yet$/);
      expect(deck).not.toContain(text);
    }
  });
});
