// E13-S01 (#423) S1: the catalogue (`listIndicators`, `22` GET /indicators; D06 §3.1). The library
// lists every descriptor the server returns, never a hard-coded set (BQ-2). A body that breaks the
// contract is a failed catalogue (CMP-027 with Retry, no partial list; BQ-14); a value a reader
// may not know (`unit`, `category`) is tolerated (C-6.3). Trade-off (BQ-14): `compute` and `pane`
// are values the client must act on, so an unknown one still fails the whole catalogue, and an
// additive enum growth on the server (C-6.3) would blank the library until this client learns it.
// No count of entries is refused: `22` owns none, so the library pages its render instead.
import { apiFetch } from "../../../lib/http/csrfFetch";
import { parseParamsSchema, SANITY_MAX_TEXT, type SchemaResult } from "./schema";
import type { Category, Compute, DescriptorPane, IndicatorDescriptor, Unit } from "./types";

const ID = /^[a-z0-9_]{2,32}$/;
/** `22` `IndicatorOutput.id`. */
const OUTPUT_ID = /^[a-z][a-z0-9_]{0,31}$/;
const COMPUTE: readonly Compute[] = ["client_worker", "server"];
const PANE: readonly DescriptorPane[] = ["price", "sub", "both"];
/** `IndicatorDescriptor.category`, in the library's group order (D02 §4.1). */
export const CATEGORIES: readonly Category[] = [
  "trend",
  "momentum",
  "volatility",
  "volume",
  "orderflow",
];
const UNITS: readonly Unit[] = [
  "price",
  "qty",
  "notional",
  "ratio",
  "pct",
  "bps",
  "count",
  "ms",
  "zscore",
  "enum",
  "bool",
];

/** One normalised catalogue entry: the fields the surfaces render, the schema parsed once. */
export interface CatalogueEntry {
  readonly id: string;
  readonly name: string;
  /** `null` for a category this client does not know: listed under All only. */
  readonly category: Category | null;
  readonly pane: DescriptorPane;
  readonly compute: Compute;
  readonly estimated: boolean;
  /** `null` when absent or unknown: rendered unitless (`22` `unit`). */
  readonly unit: Unit | null;
  readonly warmupBars: number | null;
  readonly outputs: readonly { readonly id: string; readonly name: string }[];
  readonly schema: SchemaResult;
}

export type CatalogueResult =
  | { readonly ok: true; readonly entries: readonly CatalogueEntry[] }
  | { readonly ok: false; readonly status: number };

const pick = <T extends string>(set: readonly T[], value: unknown): T | null =>
  typeof value === "string" && (set as readonly string[]).includes(value) ? (value as T) : null;

const plainName = (value: unknown): value is string =>
  typeof value === "string" && value.length > 0 && value.length <= SANITY_MAX_TEXT;

/**
 * The outputs, or `null` to refuse. An absent `outputs` is `[]` by design: `22` does not list it in
 * `required`, so a descriptor without it is legal. A present one keeps `minItems: 1`.
 */
function outputsOf(raw: unknown): CatalogueEntry["outputs"] | null {
  if (raw === undefined) return [];
  if (!Array.isArray(raw) || raw.length === 0) return null;
  const out: { id: string; name: string }[] = [];
  for (const item of raw as unknown[]) {
    if (typeof item !== "object" || item === null) return null;
    const { id, name } = item as Record<string, unknown>;
    if (typeof id !== "string" || !OUTPUT_ID.test(id) || !plainName(name)) return null;
    out.push({ id, name });
  }
  return out;
}

/** One descriptor, or `null` when a field the client must act on is missing or unknown. */
export function normaliseDescriptor(raw: unknown): CatalogueEntry | null {
  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) return null;
  const d = raw as Partial<Record<keyof IndicatorDescriptor, unknown>>;
  const compute = pick(COMPUTE, d.compute);
  const pane = pick(PANE, d.pane);
  const outputs = outputsOf(d.outputs);
  if (typeof d.id !== "string" || !ID.test(d.id) || !plainName(d.name)) return null;
  if (compute === null || pane === null || outputs === null) return null;
  const warmup = d.warmup_bars;
  return Object.freeze({
    id: d.id,
    name: d.name,
    category: pick(CATEGORIES, d.category),
    pane,
    compute,
    estimated: d.estimated === true,
    unit: pick(UNITS, d.unit),
    warmupBars:
      typeof warmup === "number" && Number.isInteger(warmup) && warmup >= 0 ? warmup : null,
    outputs,
    schema: parseParamsSchema(d.params_schema),
  });
}

/** A `listIndicators` 200 body as entries, in the server's order; `null` breaks the contract. */
export function normaliseCatalogue(body: unknown): readonly CatalogueEntry[] | null {
  if (typeof body !== "object" || body === null) return null;
  const items = (body as { items?: unknown }).items ?? [];
  if (!Array.isArray(items)) return null;
  const seen = new Set<string>();
  const entries: CatalogueEntry[] = [];
  for (const item of items as unknown[]) {
    const entry = normaliseDescriptor(item);
    if (entry === null || seen.has(entry.id)) return null;
    seen.add(entry.id);
    entries.push(entry);
  }
  return Object.freeze(entries);
}

export type FetchLike = (input: string, init?: RequestInit) => Promise<Response>;

/** GET /api/v1/indicators. Status 0 is no answer; a broken body counts as a failure (200). */
export async function fetchCatalogue(fetchFn: FetchLike = apiFetch): Promise<CatalogueResult> {
  let res: Response;
  try {
    res = await fetchFn("/api/v1/indicators", { method: "GET" });
  } catch {
    return { ok: false, status: 0 };
  }
  if (!res.ok) return { ok: false, status: res.status };
  let body: unknown;
  try {
    body = await res.json();
  } catch {
    body = null;
  }
  const entries = normaliseCatalogue(body);
  return entries === null ? { ok: false, status: res.status } : { ok: true, entries };
}

/** An entry by id, for a preset or an instance. */
export const entryById = (
  entries: readonly CatalogueEntry[],
  id: string,
): CatalogueEntry | undefined => entries.find((e) => e.id === id);
