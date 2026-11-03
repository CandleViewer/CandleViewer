/**
 * SCR-012's words (E10-S05, #5236), in one place. A merged string is used verbatim and names its source; the strings
 * no merged spec names (`15` CMP-059 hands them to "SCR-012's keys") are marked PROPOSED for the owner's read.
 * Route and command labels are not here: they come from `routes/titles.ts` and `keymap.json`.
 */

/** The groups in E10-D02 f11's fixed order (Navigate · Panel · Symbol · Action · Setting). */
export const GROUPS = {
  navigate: "Navigate",
  panel: "Panel",
  symbol: "Symbol",
  action: "Action",
  setting: "Setting",
} as const;

export const PALETTE_COPY = {
  /** PROPOSED: the dialog title; `keymap.json`'s label for `global.palette`. */
  title: "Command palette",
  /** PROPOSED: the input's label; the CMP-084 trigger's visible label. */
  inputLabel: "Search commands",
  /** PROPOSED: the listbox's name. */
  listLabel: "Commands",
  /** E10-D03 :363 (E10-D02 :104): a destructive row's tag and the end of its name. */
  confirmsTag: "confirms",
  /** E10-D02 f10: the empty query's two sections. */
  recent: "Recent",
  suggested: "Suggested",
} as const;

/** PROPOSED: the count sentence, said once per settled query (CMP-059's settle). */
export const countText = (n: number): string => (n === 1 ? "1 result" : `${String(n)} results`);

/**
 * The no-results sentence, shown and said once. With a Symbol source mounted it is `14` SCR-012's "No command or
 * symbol matches" (E10-D03 §6.1's quotes); without one it claims no symbol search (PROPOSED, with its way on).
 */
export function noResultsText(query: string, symbolsSearched: boolean): string {
  return symbolsSearched
    ? `No command or symbol matches “${query}”`
    : `No command matches “${query}”. Try fewer letters, or use the nav rail.`;
}

/** PROPOSED: said once, politely, when `runCommand` refuses a row (no handler, or the arm reads unarmed). */
export const refusedText = (label: string): string =>
  `${label} did not run: it is not available here.`;

/** E09-D09 §3.1 `rbac.view_as`, verbatim: every write while viewing as another user (not a protective command). */
export const viewAsReason = (user: string): string => `Read-only while viewing as ${user}.`;
/** E09-D09 §3.1 `rbac.permission`, verbatim, with §3.2's verb. */
export const permissionReason = (verb: string): string => `Your role can't ${verb}.`;
/** E09-D09 §3.1 `rbac.owner_only`, verbatim, with §3.2's verb or the action's own. */
export const ownerOnlyReason = (verb: string): string => `Only the owner can ${verb}.`;
