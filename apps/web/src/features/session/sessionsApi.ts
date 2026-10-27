/**
 * #1640 S3, SCR-112 sessions: `GET /auth/sessions` (`authListSessions`), `DELETE /me/sessions/{id}`
 * (`revokeMySession`; the current id is a logout) and `POST /auth/logout {all_sessions: true}`.
 * Outcomes are fixed kinds: no server `detail` ever reaches the screen.
 */
import type { generated } from "@candleviewer/protocol";
import { accessToken } from "../../lib/auth/accessToken";
import { apiFetch } from "../../lib/http/csrfFetch";

type Schemas = generated.rest.components["schemas"];
export type UserSession = Schemas["UserSession"];
type LogoutBody = NonNullable<
  generated.rest.operations["authLogout"]["requestBody"]
>["content"]["application/json"];

/** `refused`: `401` (a locked or cookie-only caller may not sign out everywhere; 22 `authLogout`). */
export type SessionsFailure = "forbidden" | "not_found" | "refused" | "unavailable";
export type ListOutcome =
  | { readonly kind: "ok"; readonly items: readonly UserSession[] }
  | { readonly kind: SessionsFailure };
export type ActionOutcome = { readonly kind: "done" } | { readonly kind: SessionsFailure };

export interface SessionsApi {
  /** `signal` aborts the read (the section unmounted, or a newer read replaced it). */
  list(signal?: AbortSignal): Promise<ListOutcome>;
  revoke(sessionId: string): Promise<ActionOutcome>;
  signOutEverywhere(): Promise<ActionOutcome>;
  /** Forgets the token in every tab and routes to SCR-001. */
  endSession(): void;
}

/** The server's page bound (`MAX_PAGE`), and a cap so a bad cursor never loops. */
const PAGE = 100;
const MAX_PAGES = 10;

function failure(status: number): SessionsFailure {
  if (status === 403) return "forbidden";
  if (status === 404) return "not_found";
  if (status === 401) return "refused";
  return "unavailable"; // 503, 422 and anything unexpected
}

async function list(signal?: AbortSignal): Promise<ListOutcome> {
  const items: UserSession[] = [];
  let cursor: string | null = null;
  try {
    for (let page = 0; page < MAX_PAGES; page += 1) {
      const query = cursor === null ? "" : `&cursor=${encodeURIComponent(cursor)}`;
      const res = await apiFetch(
        `/api/v1/auth/sessions?limit=${PAGE}${query}`,
        signal === undefined ? undefined : { signal },
      );
      // a 401 here judged no sign-out everywhere: it is not `refused` (whose copy is about that)
      if (!res.ok) return { kind: res.status === 401 ? "unavailable" : failure(res.status) };
      const body = (await res.json()) as {
        items?: unknown;
        meta?: { has_more?: unknown; next_cursor?: unknown };
      };
      if (!Array.isArray(body.items)) return { kind: "unavailable" };
      items.push(...(body.items as UserSession[]));
      const next = body.meta?.next_cursor;
      if (body.meta?.has_more !== true || typeof next !== "string") break;
      cursor = next;
    }
    return { kind: "ok", items };
  } catch {
    return { kind: "unavailable" };
  }
}

async function act(call: () => Promise<Response>): Promise<ActionOutcome> {
  try {
    const res = await call();
    return res.ok ? { kind: "done" } : { kind: failure(res.status) };
  } catch {
    return { kind: "unavailable" };
  }
}

const everywhere: LogoutBody = { all_sessions: true };

export const sessionsApi: SessionsApi = {
  list,
  revoke: (id) =>
    act(() => apiFetch(`/api/v1/me/sessions/${encodeURIComponent(id)}`, { method: "DELETE" })),
  signOutEverywhere: () =>
    act(() =>
      apiFetch("/api/v1/auth/logout", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(everywhere),
      }),
    ),
  endSession: () => accessToken.endSession(),
};
