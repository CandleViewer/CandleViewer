// E14-T02 (#400): the drawings REST client (`22-api-openapi.yaml` listDrawings, batchUpsertDrawings).
// A batch body is serialised once and re-sent byte-identical with the same `Idempotency-Key` on a
// retry; `if_match` tokens are copied as received strings, never through a Date (`22` Drawing).
import { apiFetch } from "../../../lib/http/csrfFetch";
import type { Drawing, DrawingBatchOp, DrawingBatchResult, DrawingsPage, Problem } from "./types";

const BASE = "/api/v1";
const PAGE_LIMIT = 500;
/** 500 live drawings per symbol make one page the norm; a cursor that never ends cannot loop. */
const MAX_PAGES = 20;
/** `22` RetryAfter is whole seconds; anything longer than a minute is clamped. */
const MAX_RETRY_AFTER_S = 60;

export type BatchOutcome =
  | { readonly kind: "ok"; readonly result: DrawingBatchResult }
  /** 409: the batch rolled back. `index` is the failing operation (`errors[0].field`), when named. */
  | { readonly kind: "conflict"; readonly rule: string; readonly index: number | null }
  | { readonly kind: "rate_limited"; readonly retryAfterS: number | null }
  /** No answer (status 0), 408 or 5xx: the same body may be re-sent. */
  | { readonly kind: "retryable"; readonly status: number }
  /** 403, 413, 422 and other refusals: never re-sent (D02:500). */
  | { readonly kind: "rejected"; readonly status: number; readonly code: string | null };

export type ListOutcome =
  | { readonly ok: true; readonly items: readonly Drawing[] }
  | { readonly ok: false; readonly status: number };

export interface DrawingsApi {
  readonly list: (symbol: string) => Promise<ListOutcome>;
  readonly batch: (body: string, idempotencyKey: string) => Promise<BatchOutcome>;
}

export function serializeBatch(operations: readonly DrawingBatchOp[]): string {
  return JSON.stringify({ operations });
}

export type FetchLike = (input: string, init?: RequestInit) => Promise<Response>;

async function readJson(res: Response): Promise<unknown> {
  try {
    return await res.json();
  } catch {
    return null;
  }
}

/** A 200 page we can trust: anything else is not a (possibly empty) list, so never hydrated. */
function asPage(body: unknown): DrawingsPage | null {
  if (typeof body !== "object" || body === null) return null;
  const { items, meta } = body as { items?: unknown; meta?: unknown };
  if (!Array.isArray(items) || typeof meta !== "object" || meta === null) return null;
  return typeof (meta as { has_more?: unknown }).has_more === "boolean"
    ? (body as DrawingsPage)
    : null;
}

/** A 2xx batch body we can trust: without it nothing is confirmed (no tokens, no ids). */
function asBatchResult(body: unknown): DrawingBatchResult | null {
  if (typeof body !== "object" || body === null) return null;
  const { created, updated, deleted } = body as Record<string, unknown>;
  return [created, updated, deleted].every((list) => Array.isArray(list))
    ? (body as DrawingBatchResult)
    : null;
}

function retryAfter(res: Response): number | null {
  const text = res.headers.get("Retry-After");
  if (text === null || !/^\s*\d+\s*$/.test(text)) return null;
  return Math.min(Math.max(Number(text), 1), MAX_RETRY_AFTER_S);
}

function conflictOf(body: unknown): { rule: string; index: number | null } {
  const problem = (body ?? {}) as Partial<Problem>;
  const first = Array.isArray(problem.errors) ? problem.errors[0] : undefined;
  const rule = typeof first?.rule === "string" ? first.rule : (problem.code ?? "conflict");
  const match = typeof first?.field === "string" ? /^operations\.(\d+)$/.exec(first.field) : null;
  return { rule, index: match?.[1] === undefined ? null : Number(match[1]) };
}

export function createDrawingsApi(fetchImpl: FetchLike = apiFetch): DrawingsApi {
  return {
    list: async (symbol) => {
      const items: Drawing[] = [];
      let cursor: string | null = null;
      for (let page = 0; page < MAX_PAGES; page += 1) {
        const query = new URLSearchParams({ symbol, limit: String(PAGE_LIMIT) });
        if (cursor !== null) query.set("cursor", cursor);
        let res: Response;
        try {
          res = await fetchImpl(`${BASE}/drawings?${query.toString()}`, { method: "GET" });
        } catch {
          return { ok: false, status: 0 };
        }
        if (!res.ok) return { ok: false, status: res.status };
        const page = asPage(await readJson(res));
        if (page === null) return { ok: false, status: res.status };
        items.push(...page.items);
        const next = page.meta.next_cursor ?? null;
        if (!page.meta.has_more || next === null) return { ok: true, items };
        cursor = next;
      }
      // A partial list would make hydrate drop confirmed rows it never saw.
      return { ok: false, status: 0 };
    },
    batch: async (body, idempotencyKey) => {
      let res: Response;
      try {
        res = await fetchImpl(`${BASE}/drawings/batch`, {
          method: "POST",
          headers: { "Content-Type": "application/json", "Idempotency-Key": idempotencyKey },
          body,
        });
      } catch {
        return { kind: "retryable", status: 0 };
      }
      if (res.ok) {
        // An unreadable 2xx confirms nothing: re-send the same body under the same key, whose
        // replay returns the stored answer (`22` Idempotency-Key).
        const result = asBatchResult(await readJson(res));
        return result === null ? { kind: "retryable", status: res.status } : { kind: "ok", result };
      }
      if (res.status === 429) return { kind: "rate_limited", retryAfterS: retryAfter(res) };
      if (res.status === 408 || res.status >= 500) return { kind: "retryable", status: res.status };
      const problem = await readJson(res);
      if (res.status === 409) return { kind: "conflict", ...conflictOf(problem) };
      const code = (problem as Partial<Problem> | null)?.code;
      return { kind: "rejected", status: res.status, code: typeof code === "string" ? code : null };
    },
  };
}
