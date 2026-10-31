/**
 * The Positions tab's analytics (E29-S01 #911's Observability: `blotter.opened`,
 * `blotter.grouped{by}`, `blotter.filtered`; E29-D02 §15) on the app's seam: a `cv:analytics`
 * event on `window`, as SCR-102 and SCR-157 report (nothing leaves the page here). The payloads
 * carry kinds and counts, never an account, a symbol or a figure (financial data, the ticket's
 * classification). Their property names are PROPOSED (owner: E29-D02 §15's table, which names the
 * events only). CSV export and a T2 press emit nothing (BQ-17; D04H:224).
 */
import { THEME_ANALYTICS_EVENT } from "../../shell/bootstrap/themeStore";
import type { FilterChip, FilterKind } from "./model/filters";
import type { GroupBy } from "./model/grouping";
import type { PanelTab } from "./panelState";

const report = (detail: Readonly<Record<string, unknown>>): void => {
  window.dispatchEvent(new CustomEvent(THEME_ANALYTICS_EVENT, { detail }));
};

export const reportOpened = (tab: PanelTab): void => report({ name: "blotter.opened", tab });

export const reportGrouped = (by: GroupBy): void => report({ name: "blotter.grouped", by });

/** The chips after a change: how many, and of which kinds (never their values). */
export function reportFiltered(chips: readonly FilterChip[]): void {
  const kinds: FilterKind[] = [...new Set(chips.map((c) => c.kind))].sort();
  report({ name: "blotter.filtered", chips: chips.length, kinds });
}
