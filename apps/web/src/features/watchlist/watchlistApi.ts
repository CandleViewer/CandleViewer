/**
 * SCR-100's and SCR-101's `/watchlists` calls (`22` `listWatchlists`, `createWatchlist`, `updateWatchlist`,
 * `deleteWatchlist`; E08-T07): the caller's lists, a new list, the whole list replaced against the version last read
 * (`If-Match: W/"<id>:<version>"`, `WatchlistETag`), and a list deleted, through the app's one REST client
 * (`apiFetch`: the bearer, SR-041's CSRF header). An answer maps to an outcome by status only; nothing of a body but
 * the stored list is read. A replace refused `412`, or `404` (the list deleted in another window), is a conflict; `409`
 * is a taken name (`name_taken`); `403` a refusal.
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

/** A new list (`WatchlistInput`): without `columns` the server gives it E08-D07 §4.1's default columns. */
export interface NewWatchlist {
  readonly name: string;
  readonly symbols: readonly string[];
  readonly columns?: readonly string[];
}

/** A delete's answer: the list is gone (a `404` too: it already was), a refusal (403), or any other failure. */
export type RemoveOutcome =
  { readonly kind: "deleted" } | { readonly kind: "refused" } | { readonly kind: "failed" };

/** SCR-101's calls besides SCR-100's: a list created, and a list deleted. */
export interface ManagerApi extends WatchlistApi {
  create(input: NewWatchlist): Promise<SaveOutcome>;
  remove(list: Watchlist): Promise<RemoveOutcome>;
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

/** A write's answer: the stored list, or a refusal by status (`404` a conflict only on a replace). */
async function storedOf(res: Response, replacing: boolean): Promise<SaveOutcome> {
  if (res.status === 412 || (replacing && res.status === 404)) return { kind: "conflict" };
  if (res.status === 409) return { kind: "name_taken" };
  if (res.status === 403) return { kind: "refused" };
  if (!res.ok) return { kind: "failed" };
  const stored: unknown = await res.json().catch(() => null);
  return isWatchlist(stored) ? { kind: "saved", list: stored } : { kind: "failed" };
}

export function createWatchlistApi(fetcher: typeof apiFetch = apiFetch): ManagerApi {
  /** One write, bounded; no answer at all (the network, the deadline) is a failure. */
  const write = async (
    path: string,
    init: RequestInit,
    read: (res: Response) => Promise<SaveOutcome>,
  ): Promise<SaveOutcome> => {
    try {
      return await withDeadline(undefined, async (bounded) =>
        read(await fetcher(path, { ...init, signal: bounded })),
      );
    } catch {
      return { kind: "failed" };
    }
  };
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
    replace(list, next) {
      const input: WatchlistInput = {
        name: next.name ?? list.name,
        symbols: [...next.symbols],
        columns: [...next.columns],
      };
      return write(
        `${WATCHLISTS_PATH}/${encodeURIComponent(list.id)}`,
        {
          method: "PUT",
          headers: { "Content-Type": "application/json", "If-Match": etagOf(list) },
          body: JSON.stringify(input),
        },
        (res) => storedOf(res, true),
      );
    },
    create(next) {
      const input: WatchlistInput = {
        name: next.name,
        symbols: [...next.symbols],
        ...(next.columns === undefined ? {} : { columns: [...next.columns] }),
      };
      return write(
        WATCHLISTS_PATH,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(input),
        },
        (res) => storedOf(res, false),
      );
    },
    async remove(list): Promise<RemoveOutcome> {
      try {
        return await withDeadline(undefined, async (bounded): Promise<RemoveOutcome> => {
          const res = await fetcher(`${WATCHLISTS_PATH}/${encodeURIComponent(list.id)}`, {
            method: "DELETE",
            signal: bounded,
          });
          if (res.ok || res.status === 404) return { kind: "deleted" };
          return res.status === 403 ? { kind: "refused" } : { kind: "failed" };
        });
      } catch {
        return { kind: "failed" };
      }
    },
  };
}
