/**
 * The `/workspaces*` REST reads (E15-S03 #476; `22` `listWorkspaces`, `getWorkspace`), typed by
 * `packages/protocol`. Restore is one `getWorkspace` per workspace, never a call per pane, and every
 * read gives up after `READ_TIMEOUT_MS`; the writes (`updateLayout`, `If-Match`) join with saving in PR-2. A refusal is read into a closed
 * `ApiFailure` by status, `code` and first `rule` only: free text never reaches the UI or a log. A
 * `412` is reported, never retried (LY-T06); a `429` carries its wait and is never queued
 * (SR-E15-04, client half). The `ETag` is kept as received, for `If-Match`.
 */
import type { generated } from "@candleviewer/protocol";
import { apiFetch } from "../../../lib/http/csrfFetch";

type Schemas = generated.rest.components["schemas"];
export type Workspace = Schemas["Workspace"];
export type WorkspaceDetail = Schemas["WorkspaceDetail"];

export type ApiFailure =
  | { readonly kind: "not_found" }
  | { readonly kind: "precondition_failed" }
  | { readonly kind: "conflict"; readonly rule: string | null }
  | { readonly kind: "invalid"; readonly code: string | null; readonly rule: string | null }
  | { readonly kind: "rate_limited"; readonly retryAfterS: number | null }
  | { readonly kind: "forbidden"; readonly code: string | null }
  | { readonly kind: "unavailable" }
  | { readonly kind: "http"; readonly status: number }
  | { readonly kind: "network" };

export type ApiResult<T> =
  | { readonly ok: true; readonly value: T; readonly etag: string | null }
  | { readonly ok: false; readonly failure: ApiFailure };

const BASE = "/api/v1/workspaces";
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

const field = (v: unknown, key: string): unknown =>
  typeof v === "object" && v !== null ? Reflect.get(v, key) : null;
const text = (v: unknown): string | null => (typeof v === "string" ? v : null);

/** The problem's `code` and its first `errors[].rule`; nothing else of the body is read. */
async function problemOf(res: Response): Promise<{ code: string | null; rule: string | null }> {
  const body: unknown = await res.json().catch(() => null);
  const errors = field(body, "errors");
  const first: unknown = Array.isArray(errors) ? errors[0] : null;
  return { code: text(field(body, "code")), rule: text(field(first, "rule")) };
}

export async function failureOf(res: Response): Promise<ApiFailure> {
  if (res.status === 404) return { kind: "not_found" };
  if (res.status === 412) return { kind: "precondition_failed" };
  const wait = res.headers.get("Retry-After")?.trim() ?? "";
  if (res.status === 429)
    return { kind: "rate_limited", retryAfterS: /^\d+$/.test(wait) ? +wait : null };
  if (res.status === 503) return { kind: "unavailable" };
  if (res.status === 409) return { kind: "conflict", rule: (await problemOf(res)).rule };
  if (res.status === 403) return { kind: "forbidden", code: (await problemOf(res)).code };
  if (res.status === 422) return { kind: "invalid", ...(await problemOf(res)) };
  return { kind: "http", status: res.status };
}

/** A read with no answer by then is given up, as one with no answer at all (`recorderApi`'s bound). */
export const READ_TIMEOUT_MS = 10_000;

/** One bounded `GET`: the caller's `signal` or the deadline, whichever comes first, ends it. */
async function read<T>(path: string, signal?: AbortSignal): Promise<ApiResult<T>> {
  const bound = new AbortController();
  const stop = (): void => bound.abort();
  const timer = setTimeout(stop, READ_TIMEOUT_MS);
  if (signal?.aborted === true) stop();
  signal?.addEventListener("abort", stop, { once: true });
  try {
    const res = await apiFetch(path, { credentials: "same-origin", signal: bound.signal });
    if (!res.ok) return { ok: false, failure: await failureOf(res) };
    return { ok: true, value: (await res.json()) as T, etag: res.headers.get("ETag") };
  } catch {
    return { ok: false, failure: { kind: "network" } }; // unanswered, timed out or unreadable
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", stop);
  }
}

/** The caller's workspaces by `sort_order`, then `id`: at most 32, so one default page. */
export async function listWorkspaces(signal?: AbortSignal): Promise<ApiResult<Workspace[]>> {
  const page = await read<{ items: Workspace[] }>(BASE, signal);
  return page.ok ? { ...page, value: page.value.items } : page;
}

/** Restore in one request: the workspace and every live layout with its panes. */
export async function getWorkspace(
  workspaceId: string,
  signal?: AbortSignal,
): Promise<ApiResult<WorkspaceDetail>> {
  // A UUID only, so a route parameter never shapes a URL.
  if (!UUID.test(workspaceId)) return { ok: false, failure: { kind: "not_found" } };
  return read<WorkspaceDetail>(`${BASE}/${workspaceId}`, signal);
}
