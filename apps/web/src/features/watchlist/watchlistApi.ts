/**
 * SCR-100's `/watchlists` calls (`22` `listWatchlists`, `updateWatchlist`; E08-T07): the caller's lists, and the whole
 * list replaced against the version last read (`If-Match: W/"<id>:<version>"`, `WatchlistETag`), through the app's one
 * REST client (`apiFetch`: the bearer, SR-041's CSRF header). An answer maps to a save outcome by status only; nothing
 * of a body but the stored list is read.
 */
import type { generated } from "@candleviewer/protocol";
import { apiFetch } from "../../lib/http/csrfFetch";
import type { SaveOutcome, Watchlist, WatchlistSaver } from "./listEdits";

type ListBody =
  generated.rest.operations["listWatchlists"]["responses"][200]["content"]["application/json"];
type WatchlistInput = generated.rest.components["schemas"]["WatchlistInput"];

export const WATCHLISTS_PATH = "/api/v1/watchlists";
/** Every call ends by then, as the app's other REST reads do. */
const DEADLINE_MS = 10_000;

export interface WatchlistApi extends WatchlistSaver {
  /** The caller's lists; throws when they could not be read. */
  list(signal?: AbortSignal): Promise<readonly Watchlist[]>;
}

/** `WatchlistETag`: the weak tag of a list item, from its id and version. */
export const etagOf = (list: Watchlist): string => `W/"${list.id}:${list.version}"`;

const isRecord = (value: unknown): value is Readonly<Record<string, unknown>> =>
  typeof value === "object" && value !== null && !Array.isArray(value);
const strings = (value: unknown): value is string[] =>
  Array.isArray(value) && value.every((item) => typeof item === "string");

/** A list as the contract answers it; anything else is not one (the reader skips it). */
export function isWatchlist(value: unknown): value is Watchlist {
  return (
    isRecord(value) &&
    typeof value["id"] === "string" &&
    typeof value["name"] === "string" &&
    strings(value["symbols"]) &&
    strings(value["columns"]) &&
    typeof value["version"] === "number"
  );
}

/** `call` with a signal that aborts at the deadline or with the caller's; the timer is cleared either way. */
async function withDeadline<T>(
  signal: AbortSignal | undefined,
  call: (signal: AbortSignal) => Promise<T>,
): Promise<T> {
  const controller = new AbortController();
  const abort = (): void => controller.abort();
  const timer = setTimeout(abort, DEADLINE_MS);
  if (signal?.aborted === true) abort();
  else signal?.addEventListener("abort", abort, { once: true });
  try {
    return await call(controller.signal);
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", abort);
  }
}

export function createWatchlistApi(fetcher: typeof apiFetch = apiFetch): WatchlistApi {
  return {
    list(signal) {
      return withDeadline(signal, async (bounded) => {
        const res = await fetcher(WATCHLISTS_PATH, { signal: bounded });
        if (!res.ok) throw new Error(`listWatchlists answered ${res.status}`);
        const body = (await res.json()) as ListBody | null; // narrowed by `isWatchlist` below
        const items: unknown = isRecord(body) ? body["items"] : undefined;
        return Array.isArray(items) ? items.filter(isWatchlist) : [];
      });
    },
    async replace(list, next): Promise<SaveOutcome> {
      const input: WatchlistInput = {
        name: list.name,
        symbols: [...next.symbols],
        columns: [...next.columns],
      };
      try {
        return await withDeadline(undefined, async (bounded): Promise<SaveOutcome> => {
          const res = await fetcher(`${WATCHLISTS_PATH}/${encodeURIComponent(list.id)}`, {
            method: "PUT",
            headers: { "Content-Type": "application/json", "If-Match": etagOf(list) },
            body: JSON.stringify(input),
            signal: bounded,
          });
          if (res.status === 412) return { kind: "conflict" };
          if (res.status === 403) return { kind: "refused" };
          if (!res.ok) return { kind: "failed" };
          const stored: unknown = await res.json().catch(() => null);
          return isWatchlist(stored) ? { kind: "saved", list: stored } : { kind: "failed" };
        });
      } catch {
        return { kind: "failed" };
      }
    },
  };
}
