/**
 * SCR-063's placeholder tabs (E29-S01 #911, BQ-15; E29-D02 §4, D-17): the strip never changes, so
 * Fills, Trade groups and Algos render now, each a CMP-026 `no-data` with its title and one cause
 * sentence. Trade groups and Algos take the deck's titles and D02:166's causes (E34's and E33's
 * tabs); Fills (E29-S04) takes PROPOSED strings on the same pattern, routed to E29-D03's copy owner
 * (G-W3). Working orders is its own tab (E29-S02, `orders/WorkingOrdersTab.tsx`). No epic key in
 * user copy (D02 §4).
 */
import type { JSX } from "react";
import { EmptyState } from "@candleviewer/ui";
import { D02_TEXT, DECK, PROPOSED_TEXT } from "./copy";
import type { PanelTab } from "./panelState";

export type PlaceholderTabId = Exclude<PanelTab, "positions" | "working_orders">;

const WORDS: Readonly<
  Record<PlaceholderTabId, { readonly title: string; readonly cause: string }>
> = {
  fills: { title: PROPOSED_TEXT.fillsTitle, cause: PROPOSED_TEXT.fillsCause },
  trade_groups: {
    title: DECK["blotter.ui.tab.trade_groups"].string,
    cause: D02_TEXT.tradeGroupsCause.string,
  },
  algos: { title: DECK["blotter.ui.tab.algos"].string, cause: D02_TEXT.algosCause.string },
};

/** One placeholder tab's panel: CMP-026 with its title (a level-2 heading under the page's h1) and its cause. */
export function PlaceholderTab({ tab }: { readonly tab: PlaceholderTabId }): JSX.Element {
  const words = WORDS[tab];
  return <EmptyState title={words.title} description={words.cause} headingLevel={2} />;
}
