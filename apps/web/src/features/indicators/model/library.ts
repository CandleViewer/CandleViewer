// E13-S01 (#423) S1: the library's list and search model (SCR-034; D02 §4.1–§4.4). Pure: the
// scorer is injected, so the UI passes CMP-213's own (S3b) and the tests a plain one. Search runs
// over `name` and `id` (CG-6: no alias field yet) inside the active tab; results stay grouped by
// category in descriptor order, and a filtered tab reports hits it hides (D02 D3).
import { CATEGORIES, type CatalogueEntry } from "./catalogue";
import { onChartCount, type Instance } from "./instances";
import { favouritesOf } from "./presets";
import type { Category, IndicatorPreset } from "./types";

export type LibraryTab = "all" | "overlay" | "subpane" | "orderflow";
export const LIBRARY_TABS: readonly LibraryTab[] = ["all", "overlay", "subpane", "orderflow"];

export type MatchRange = readonly [start: number, end: number];
/** A scorer: `null` when `query` does not match `label`, else a score (higher first) and spans. */
export type Matcher = (
  label: string,
  query: string,
) => { readonly score: number; readonly ranges: readonly MatchRange[] } | null;

export interface EntryRow {
  readonly entry: CatalogueEntry;
  /** Spans of `entry.name`; empty when only the id matched or the query is empty. */
  readonly ranges: readonly MatchRange[];
  /** "On chart ×N" (D02 D4); > 0 makes the action "Add second instance". */
  readonly onChart: number;
  /** "Requires recorded history" for every `compute: server` entry (D02 D2). */
  readonly requiresRecording: boolean;
  /** The built-in presets listed as flat rows after the entry (D02 D2). */
  readonly builtins: readonly IndicatorPreset[];
}

export interface LibraryGroup {
  /** `null`: a category this client does not know (listed under All only). */
  readonly category: Category | null;
  readonly rows: readonly EntryRow[];
}

export interface LibraryView {
  /** The landing's Favourites group; `null` while a query is typed. */
  readonly favourites: readonly IndicatorPreset[] | null;
  readonly groups: readonly LibraryGroup[];
  /** Entries the query matches in this tab (the polite count, D02 D3). */
  readonly matches: number;
  /** Matches the active tab hides ("2 matches in other categories — show all"). */
  readonly elsewhere: number;
}

export interface LibraryInput {
  readonly entries: readonly CatalogueEntry[];
  readonly presets: readonly IndicatorPreset[];
  readonly instances: readonly Instance[];
  readonly tab: LibraryTab;
  readonly query: string;
  readonly match: Matcher;
}

/** Whether `entry` is listed under `tab` (D06 §3.3: `both` under both pane tabs). */
export function inTab(entry: Pick<CatalogueEntry, "pane" | "category">, tab: LibraryTab): boolean {
  switch (tab) {
    case "all":
      return true;
    case "overlay":
      return entry.pane !== "sub";
    case "subpane":
      return entry.pane !== "price";
    case "orderflow":
      return entry.category === "orderflow";
  }
}

interface Hit {
  readonly entry: CatalogueEntry;
  readonly score: number;
  readonly ranges: readonly MatchRange[];
}

function hit(entry: CatalogueEntry, query: string, match: Matcher): Hit | null {
  if (query.trim() === "") return { entry, score: 0, ranges: [] };
  const byName = match(entry.name, query);
  const byId = match(entry.id, query);
  if (byName === null && byId === null) return null;
  if (byId !== null && (byName === null || byId.score > byName.score)) {
    return { entry, score: byId.score, ranges: [] };
  }
  return byName === null ? null : { entry, score: byName.score, ranges: byName.ranges };
}

/** The library's rows for one tab and query. */
export function libraryView(input: LibraryInput): LibraryView {
  const { entries, presets, instances, tab, query, match } = input;
  const searching = query.trim() !== "";
  const hits: Hit[] = [];
  let elsewhere = 0;
  for (const entry of entries) {
    const found = hit(entry, query, match);
    if (found === null) continue;
    if (inTab(entry, tab)) hits.push(found);
    else elsewhere += 1;
  }
  // Best first within a group when searching; descriptor order otherwise (stable sort).
  if (searching) hits.sort((a, b) => b.score - a.score);
  const order: (Category | null)[] = [...CATEGORIES, null];
  const groups: LibraryGroup[] = [];
  for (const category of order) {
    const rows = hits
      .filter((h) => h.entry.category === category)
      .map((h): EntryRow => ({
        entry: h.entry,
        ranges: h.ranges,
        onChart: onChartCount(instances, h.entry.id),
        requiresRecording: h.entry.compute === "server",
        builtins: searching
          ? []
          : presets.filter((p) => p.is_builtin && p.indicator_code === h.entry.id),
      }));
    if (rows.length > 0) groups.push({ category, rows });
  }
  return {
    favourites: searching ? null : favouritesOf(presets, entries),
    groups,
    matches: hits.length,
    elsewhere: searching ? elsewhere : 0,
  };
}
