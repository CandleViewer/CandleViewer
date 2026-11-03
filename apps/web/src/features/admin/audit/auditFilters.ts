/**
 * SCR-135's filter set (E42-S04; E42-D04 §4 Filters, D4, D7; BQ-3): URL state ⇄ the filters CMP-174
 * edits ⇄ a `queryAuditLog` query.
 * - The URL carries the contract's names (`22` queryAuditLog), `action` repeated, so a filtered
 *   view is a deep link. `q` and `ip` are URL state too, so they can sit in the browser's history
 *   (the plan's §13: for the security lens). A cursor and a limit are never URL state.
 * - A query leaves Environment out: it filters the loaded page only and sends no read (D7). Its
 *   action codes are sorted and unique, as the server keeps them, and it asks for 200 rows (D4).
 * - "My activity" (a Manager, `own`): the model drops Actor (the server scopes the read to the
 *   caller), and `q`, `ip` and Environment are T2 `rbac.owner_only`; none of them is ever sent
 *   (the orchestrator's BQ-3). A crafted link's values are dropped and named, for
 *   `audit.own_filter`.
 * - The client checks no value: the server's `422` decides, and its field errors show in the bar.
 */
import {
  queryString,
  type AuditEntry,
  type AuditQuery,
  type AuditView,
  type EntryOutcome,
  type Environment,
  type Severity,
} from "./auditReads";

/** The set CMP-174 edits: the contract's query parameters but paging, and D7's Environment. */
export type AuditFilters = Omit<AuditQuery, "cursor" | "limit"> & { environment?: Environment };
export type FilterName = keyof AuditFilters;

/** The URL state's names, in the contract's parameter order, then the client's Environment. */
export const FILTER_NAMES = [
  "actor_user_id",
  "action",
  "subject_type",
  "subject_id",
  "outcome",
  "severity",
  "ip",
  "from",
  "to",
  "q",
  "environment",
] as const satisfies readonly FilterName[];

/** D4: the client's page size, inside the contract's `limit` of 1 to 500. */
export const PAGE_LIMIT = 200;

/** What a Manager's model never holds or sends (BQ-3; AL-25). */
const OWNER_ONLY: readonly FilterName[] = ["actor_user_id", "ip", "q", "environment"];

const OUTCOMES: readonly EntryOutcome[] = ["success", "failure", "denied"];
const SEVERITIES: readonly Severity[] = ["debug", "info", "warning", "error", "critical"];
const ENVIRONMENTS: readonly Environment[] = ["live", "demo", "testnet"];

const oneOf = <T extends string>(list: readonly T[], value: string): value is T =>
  (list as readonly string[]).includes(value);

/** Codes trimmed, blanks dropped, each kept once in the order given. */
const codesOf = (raw: readonly string[]): string[] => [
  ...new Set(raw.map((code) => code.trim()).filter((code) => code !== "")),
];

/** One value per name: trimmed, a blank one dropped; the enums only as the contract's values. */
function put(out: AuditFilters, name: FilterName, raw: string): boolean {
  const value = raw.trim();
  if (value === "") return true;
  switch (name) {
    case "outcome":
      if (!oneOf(OUTCOMES, value)) return false;
      out.outcome = value;
      return true;
    case "severity":
      if (!oneOf(SEVERITIES, value)) return false;
      out.severity = value;
      return true;
    case "environment":
      if (!oneOf(ENVIRONMENTS, value)) return false;
      out.environment = value;
      return true;
    case "action":
      return true; // repeated: read whole by the caller
    default:
      out[name] = value;
      return true;
  }
}

/** A filter set as the model keeps it: text trimmed, blanks dropped, codes once each. */
export function normalise(filters: AuditFilters, view: AuditView = "raw"): AuditFilters {
  const out: AuditFilters = {};
  for (const name of FILTER_NAMES) {
    if (view === "own" && OWNER_ONLY.includes(name)) continue;
    if (name === "action") {
      const codes = codesOf(filters.action ?? []);
      if (codes.length > 0) out.action = codes;
      continue;
    }
    const value = filters[name];
    if (value !== undefined) put(out, name, value);
  }
  return out;
}

export interface ParsedFilters {
  readonly filters: AuditFilters;
  /** Names the URL held that this view cannot take: an unknown enum value, an Owner-only filter. */
  readonly dropped: readonly FilterName[];
}

/** The filter set a location's search holds. A cursor or a limit in it is ignored. */
export function parseFilters(search: string, view: AuditView = "raw"): ParsedFilters {
  const params = new URLSearchParams(search);
  const filters: AuditFilters = {};
  const dropped: FilterName[] = [];
  for (const name of FILTER_NAMES) {
    if (!params.has(name)) continue;
    if (view === "own" && OWNER_ONLY.includes(name)) {
      if (params.getAll(name).some((value) => value.trim() !== "")) dropped.push(name);
      continue;
    }
    if (name === "action") {
      const codes = codesOf(params.getAll("action"));
      if (codes.length > 0) filters.action = codes;
    } else if (!put(filters, name, params.get(name) ?? "")) {
      dropped.push(name);
    }
  }
  return { filters, dropped };
}

/** A filter set as URL state: the contract's names in order, `action` repeated, nothing blank. */
export function searchOf(filters: AuditFilters): string {
  const params = new URLSearchParams();
  const set = normalise(filters);
  for (const name of FILTER_NAMES) {
    if (name === "action") {
      for (const code of set.action ?? []) params.append("action", code);
      continue;
    }
    const value = set[name];
    if (value !== undefined) params.append(name, value);
  }
  return params.toString();
}

/**
 * The query one read sends: the set without Environment (D7), its codes sorted and unique, 200 rows
 * (D4), and the cursor when paging. For a Manager, never Actor, `q` or `ip` (BQ-3).
 */
export function queryOf(
  filters: AuditFilters,
  cursor?: string | null,
  view: AuditView = "raw",
): AuditQuery {
  const set = normalise(filters, view);
  delete set.environment;
  const { action, ...rest } = set;
  const query: AuditQuery = rest;
  if (action !== undefined) query.action = [...action].sort();
  query.limit = PAGE_LIMIT;
  if (cursor !== undefined && cursor !== null) query.cursor = cursor;
  return query;
}

/** One string per distinct set a read sends: Environment and the codes' order never change it. */
export function filtersKey(filters: AuditFilters, view: AuditView = "raw"): string {
  return queryString(queryOf(filters, null, view));
}

/** Any filter set, Environment included: `audit.end` and `audit.no_match` read filtered. */
export function isFiltered(filters: AuditFilters): boolean {
  return Object.keys(normalise(filters)).length > 0;
}

/** D7: the loaded rows of one environment, or all of them, the same list, when none is chosen. */
export function rowsFor(
  items: readonly AuditEntry[],
  environment: Environment | undefined,
): readonly AuditEntry[] {
  return environment === undefined ? items : items.filter((e) => e.environment === environment);
}
