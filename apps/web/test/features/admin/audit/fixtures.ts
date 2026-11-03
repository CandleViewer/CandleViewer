/**
 * E42-S04 (#1135) test data, after E42-D04 §1's worked example: owner `basiltt`, manager `alex`,
 * LIVE, 2026-10-22 "as of 14:02:11", the break at entry 1,204,118 found at 14:05:07 UTC in a
 * check of entries 204,119–1,204,118. Typed with the generated contract types (C-4.16). No value is
 * secret-shaped: hashes, digests, signatures and keys are repeated characters of the served shape.
 */
import { vi } from "vitest";
import type { generated } from "@candleviewer/protocol";

type Schemas = generated.rest.components["schemas"];
type Ops = generated.rest.operations;
export type Entry = Schemas["AuditEntry"];
export type Verify = Ops["verifyAuditChain"]["responses"][200]["content"]["application/json"];
export type IncidentRow = Schemas["Incident"];

export const OWNER_ID = "9f1c2b4e-0a1d-4f2b-9e3a-11c0ffee0001";
export const ALEX_ID = "9f1c2b4e-0a1d-4f2b-9e3a-11c0ffee0002";
export const INCIDENT_ID = "1a000000-0000-4000-8000-000000000007";
export const REF = "urn:cv:req:0193f2bb-9c11-7a3d-88f1-0d2e3f4a5b6c";
/** The worked example's clock: 2026-10-22 14:02:11 UTC. */
export const T0 = Date.UTC(2026, 9, 22, 14, 2, 11);
export const GENESIS = "0".repeat(64);
export const hex = (c: string): string => c.repeat(64);

/** One entry of the worked example; `over` changes what a case needs. */
export function entry(over: Partial<Entry> = {}): Entry {
  return {
    id: 1_204_118,
    ts: "2026-10-22T14:01:50.212000Z",
    actor_user_id: OWNER_ID,
    actor_username: "basiltt",
    action: "orders.submit",
    subject_type: "order",
    subject_id: "0a000000-0000-4000-8000-000000000001",
    subject_label: null,
    outcome: "success",
    severity: "info",
    reason: null,
    environment: "live",
    session_id: "5e000000-0000-4000-8000-000000000001",
    ip: "100.84.12.9",
    user_agent: null,
    request_id: "0193f2bb-9c11-7a3d-88f1-0d2e3f4a5b6c",
    detail: { before: null, after: { symbol: "BTCUSDT", side: "buy", legs: 3 } },
    entry_hash: hex("3"),
    prev_hash: hex("7"),
    ...over,
  };
}

/** `n` entries, newest first, ids counting down from `top`. */
export function entries(n: number, top = 1_204_300, over: Partial<Entry> = {}): Entry[] {
  return Array.from({ length: n }, (_, i) =>
    entry({
      id: top - i,
      ts: new Date(T0 - i * 1_000).toISOString(),
      ...over,
    }),
  );
}

/** A served list page (`queryAuditLog`'s `200`). */
export function pageBody(
  items: readonly Entry[],
  more: { readonly next?: string | null; readonly chain?: boolean } = {},
): { items: Entry[]; chain_verified: boolean; meta: Schemas["PageMeta"] } {
  const next = more.next === undefined ? null : more.next;
  return {
    items: [...items],
    chain_verified: more.chain ?? true,
    meta: { next_cursor: next, has_more: next !== null, count: items.length },
  };
}

export function verifyBody(over: Partial<Verify> = {}): Verify {
  return {
    verified: true,
    entries_checked: 1_000_000,
    first_bad_id: null,
    checked_at: "2026-10-22T14:05:07Z",
    from_id: 204_119,
    to_id: 1_204_118,
    anchor_hash: hex("e"),
    last_hash: hex("8"),
    ...over,
  };
}

/** The break of the worked example: entry 1,204,118 in a check of entries 204,119–1,204,118. */
export const BROKEN: Verify = verifyBody({
  verified: false,
  entries_checked: 1_000_000,
  first_bad_id: 1_204_118,
  last_hash: hex("4"),
});

export function incident(over: Partial<IncidentRow> = {}): IncidentRow {
  return {
    id: INCIDENT_ID,
    component: "db",
    severity: "critical",
    status: "open",
    title: "audit chain break at id <n>",
    detail: "audit chain break at id 1204118",
    occurrences: 1,
    first_seen_at: "2026-10-22T14:05:07Z",
    last_seen_at: "2026-10-22T14:05:07Z",
    acknowledged_by: null,
    acknowledged_at: null,
    resolved_at: null,
    runbook_ref: null,
    signature: "5f0c2d9e4b7a1c3e",
    ...over,
  };
}

/** A JSON answer. */
export const json = (
  status: number,
  body: unknown,
  headers: Record<string, string> = {},
): Response =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...headers },
  });

/** A problem answer (RFC 9457), as the server sends it. */
export const problem = (
  status: number,
  code: string,
  extra: Record<string, unknown> = {},
  headers: Record<string, string> = {},
): Response =>
  new Response(
    JSON.stringify({
      type: `https://candleviewer.local/errors/${code}`,
      title: "Refused",
      status,
      code,
      instance: REF,
      ...extra,
    }),
    { status, headers: { "Content-Type": "application/problem+json", ...headers } },
  );

export interface Sent {
  readonly url: string;
  readonly method: string;
  readonly headers: Headers;
  readonly body: string | null;
  readonly signal: AbortSignal | undefined;
}

/** Stubs `fetch` with `answer`, recording each request as sent. */
export function stubFetch(answer: (sent: Sent) => Response | Promise<Response>): Sent[] {
  const calls: Sent[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
      const sent: Sent = {
        url: String(input),
        method: (init.method ?? "GET").toUpperCase(),
        headers: new Headers(init.headers),
        body: typeof init.body === "string" ? init.body : null,
        signal: init.signal ?? undefined,
      };
      calls.push(sent);
      return answer(sent);
    }),
  );
  return calls;
}

/** A `fetch` that never answers, and rejects as a browser does once its signal aborts. */
export function hangingFetch(): AbortSignal[] {
  const signals: AbortSignal[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn((_input: RequestInfo | URL, init: RequestInit = {}) => {
      const signal = init.signal as AbortSignal;
      signals.push(signal);
      return new Promise<Response>((_resolve, reject) => {
        signal.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
      });
    }),
  );
  return signals;
}

/** A document whose visibility the test sets, counting its listeners. */
export class FakeDocument extends EventTarget {
  visibilityState: DocumentVisibilityState = "visible";
  listeners = 0;
  override addEventListener(...args: Parameters<EventTarget["addEventListener"]>): void {
    this.listeners += 1;
    super.addEventListener(...args);
  }
  override removeEventListener(...args: Parameters<EventTarget["removeEventListener"]>): void {
    this.listeners -= 1;
    super.removeEventListener(...args);
  }
  show(state: DocumentVisibilityState): void {
    this.visibilityState = state;
    this.dispatchEvent(new Event("visibilitychange"));
  }
}
