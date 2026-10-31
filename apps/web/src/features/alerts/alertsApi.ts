/**
 * REST client for the alerts centre (E40-S01): `listAlerts`, `setAlertEnabled`, `setAlertSnooze`,
 * `deleteAlert`, `listAlertDeliveries` and `getRuleVocabulary`, through `apiFetch` (bearer + CSRF).
 * Outcomes are fixed kinds: the server's `detail` text never reaches the screen.
 */
import { apiFetch } from "../../lib/http/csrfFetch";
import type { Alert, DeliveryRow, VocabularySignal } from "./types.js";

export type AlertsFailure = "forbidden" | "not_found" | "invalid" | "unavailable";
export type Outcome<T> =
  | { readonly kind: "ok"; readonly value: T; readonly truncated?: true }
  | { readonly kind: AlertsFailure };

export interface AlertsApi {
  list(signal?: AbortSignal): Promise<Outcome<readonly Alert[]>>;
  setEnabled(id: string, enabled: boolean): Promise<Outcome<Alert>>;
  /** `until` null clears the snooze. */
  setSnooze(id: string, until: string | null): Promise<Outcome<Alert>>;
  remove(id: string): Promise<Outcome<null>>;
  deliveries(
    query: { readonly alertId?: string; readonly status?: "failed" },
    signal?: AbortSignal,
  ): Promise<Outcome<readonly DeliveryRow[]>>;
  vocabulary(signal?: AbortSignal): Promise<Outcome<readonly VocabularySignal[]>>;
}

const BASE = "/api/v1";
/** Page bound of the alerts list (`limit` <= 500) and a cap so a bad cursor never loops. */
const ALERT_PAGE = 500;
const DELIVERY_PAGE = 100;
const MAX_PAGES = 10;

function failure(status: number): AlertsFailure {
  if (status === 403) return "forbidden";
  if (status === 404) return "not_found";
  if (status === 422 || status === 400) return "invalid";
  return "unavailable";
}

interface PageBody {
  readonly items?: unknown;
  readonly meta?: { readonly has_more?: unknown; readonly next_cursor?: unknown };
}

async function pages<T>(
  path: string,
  limit: number,
  signal?: AbortSignal,
): Promise<Outcome<readonly T[]>> {
  const items: T[] = [];
  let cursor: string | null = null;
  try {
    for (let page = 0; page < MAX_PAGES; page += 1) {
      const sep = path.includes("?") ? "&" : "?";
      const more = cursor === null ? "" : `&cursor=${encodeURIComponent(cursor)}`;
      const res = await apiFetch(
        `${BASE}${path}${sep}limit=${limit}${more}`,
        signal === undefined ? undefined : { signal },
      );
      if (!res.ok) return { kind: failure(res.status) };
      const body = (await res.json()) as PageBody;
      if (!Array.isArray(body.items)) return { kind: "unavailable" };
      items.push(...(body.items as T[]));
      const next = body.meta?.next_cursor;
      if (body.meta?.has_more !== true || typeof next !== "string")
        return { kind: "ok", value: items };
      cursor = next;
    }
    return { kind: "ok", value: items, truncated: true };
  } catch {
    return { kind: "unavailable" };
  }
}

async function send<T>(
  method: "PUT" | "DELETE",
  path: string,
  body?: unknown,
): Promise<Outcome<T>> {
  try {
    const init: RequestInit =
      body === undefined
        ? { method }
        : { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
    const res = await apiFetch(`${BASE}${path}`, init);
    if (!res.ok) return { kind: failure(res.status) };
    return { kind: "ok", value: (res.status === 204 ? null : await res.json()) as T };
  } catch {
    return { kind: "unavailable" };
  }
}

export const alertsApi: AlertsApi = {
  list: (signal) => pages<Alert>("/alerts", ALERT_PAGE, signal),
  setEnabled: (id, enabled) =>
    send("PUT", `/alerts/${encodeURIComponent(id)}/enabled`, { enabled }),
  setSnooze: (id, until) => send("PUT", `/alerts/${encodeURIComponent(id)}/snooze`, { until }),
  remove: (id) => send("DELETE", `/alerts/${encodeURIComponent(id)}`),
  deliveries: ({ alertId, status }, signal) => {
    const query = new URLSearchParams();
    if (alertId !== undefined) query.set("alert_id", alertId);
    if (status !== undefined) query.set("status", status);
    return pages<DeliveryRow>(`/alerts/deliveries?${query.toString()}`, DELIVERY_PAGE, signal);
  },
  vocabulary: async (signal) => {
    try {
      const res = await apiFetch(
        `${BASE}/rules/vocabulary`,
        signal === undefined ? undefined : { signal },
      );
      if (!res.ok) return { kind: failure(res.status) };
      const body = (await res.json()) as { signals?: VocabularySignal[] };
      return { kind: "ok", value: body.signals ?? [] };
    } catch {
      return { kind: "unavailable" };
    }
  },
};
