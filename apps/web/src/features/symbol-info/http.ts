/**
 * One GET for SCR-103's reads (`GET /instruments/{symbol}`, `GET /market/data-coverage`): ended by the caller's
 * `signal` or a 10 s deadline, answered by status and body only. The copy maps by status (and `code`), never by
 * `Problem.detail` (D06 §12); a `Problem.instance` is kept only when it is a `urn:cv:req:` reference.
 */
import { apiFetch } from "../../lib/http/csrfFetch";
import type { Clock } from "../symbol-search/instrumentIndex";

export const DEADLINE_MS = 10_000;
/** `Retry-After` is honoured from 1 s up to a minute (the ladder is bounded at 60 s, D-12). */
const MAX_RETRY_AFTER_S = 60;

export interface Answer {
  readonly status: number;
  readonly ok: boolean;
  readonly body: unknown;
  /** The wait the server asked for, whole seconds only, or `null`. */
  readonly retryAfterS: number | null;
  /** `Problem.instance` when it is `urn:cv:req:…`, else `null`. */
  readonly instance: string | null;
}

/** `value[key]` when `value` is an object, else `undefined`. */
export const field = (value: unknown, key: string): unknown =>
  typeof value === "object" && value !== null ? Reflect.get(value, key) : undefined;

function retryAfter(res: Response, body: unknown): number | null {
  const sent = res.headers.get("Retry-After") ?? field(body, "retry_after_seconds");
  const text = typeof sent === "number" ? String(sent) : sent;
  if (typeof text !== "string" || !/^\s*\d+\s*$/.test(text)) return null;
  return Math.min(Math.max(Number(text), 1), MAX_RETRY_AFTER_S);
}

function instanceOf(body: unknown): string | null {
  const sent = field(body, "instance");
  return typeof sent === "string" && /^urn:cv:req:\S+$/.test(sent) ? sent : null;
}

/** `null` when no answer came (a network error, the deadline, or an abort). */
export async function getAnswer(
  path: string,
  signal: AbortSignal,
  clock: Clock,
): Promise<Answer | null> {
  if (signal.aborted) return null;
  const call = new AbortController();
  const end = (): void => {
    clock.clearTimeout(deadline);
    call.abort();
  };
  const deadline = clock.setTimeout(end, DEADLINE_MS);
  signal.addEventListener("abort", end);
  try {
    const res = await apiFetch(path, { method: "GET", signal: call.signal });
    const body: unknown = res.ok ? await res.json() : await res.json().catch(() => null);
    return {
      status: res.status,
      ok: res.ok,
      body,
      retryAfterS: retryAfter(res, body),
      instance: instanceOf(body),
    };
  } catch {
    return null;
  } finally {
    clock.clearTimeout(deadline);
    signal.removeEventListener("abort", end);
  }
}
