/**
 * The client instrument index (E08-S09; E08-D05 §3, §6.2): the Trading listing from `GET /instruments`,
 * paged to the end and normalised once (`toEntry`), read at `start()` and hourly, and again on
 * `reread()` (an `instrument_revision`, or "Retry now"); and `lookupSymbol` (`GET /instruments/{symbol}`),
 * whose answers feed the session caches through `learn()`. No React: a plain external store
 * (`subscribe` / `getSnapshot`) on an injected clock, as `features/app-shell/clock.ts` does.
 * Its lifecycle in the app: the shell's store (`searchSession`) holds one from the shell's start, but
 * starts it only once a workspace binds the first opener, so a held index is not a running one: a
 * host that shows the list reads `useRunningIndex()` (or `running`), never `index !== null`.
 */
import type { generated } from "@candleviewer/protocol";
import { apiFetch } from "../../lib/http/csrfFetch";
import { toEntry, type IndexEntry, type IndexPhase, type Instrument } from "./ranking";

type Schemas = generated.rest.components["schemas"];
type ListBody =
  generated.rest.operations["listInstruments"]["responses"][200]["content"]["application/json"];

/** The time source and the microtask queue, injectable for tests (as `lib/ws/policy/timers.ts`). */
export interface Clock {
  readonly now: () => number;
  readonly setTimeout: (run: () => void, ms: number) => unknown;
  readonly clearTimeout: (id: unknown) => void;
  readonly queueMicrotask: (run: () => void) => void;
}

/** Reads the globals on every call, so fake timers installed after import still apply. */
export const SYSTEM_CLOCK: Clock = {
  now: () => Date.now(),
  setTimeout: (run, ms) => setTimeout(run, ms),
  // `id` is what this clock's `setTimeout` returned; the cast only restores that type.
  clearTimeout: (id) => clearTimeout(id as ReturnType<typeof setTimeout>),
  queueMicrotask: (run) => queueMicrotask(run),
};

/** Every GET ends by then, as the shell's bootstrap calls do (`BOOTSTRAP_TIMEOUT_MS`). */
const DEADLINE_MS = 10_000;
/** §6.2 Loading: after the n-th 503 with no list, wait 2^n s capped at 30: 2, 4, 8, 16, 30, 30… */
const MAX_STEP_S = 30;
/** 503s for this long with no list is "Load failed". */
const UNAVAILABLE_FOR_MS = 60_000;
/** Load failed: "Next try in 30 s.", or later when the server asks for longer. */
const RETRY_FAILED_MS = 30_000;
const REREAD_MS = 3_600_000;
/** A server's `Retry-After` is honoured from 1 s up to the longest wait this store makes. */
const MAX_RETRY_AFTER_S = REREAD_MS / 1000;
/** A re-read running longer than this is "Refreshing". */
const REFRESHING_AFTER_MS = 1_000;
const PAGE_LIMIT = 500;
/** 20 000 instruments: a cursor that never ends cannot loop. */
const MAX_PAGES = 40;
/** `22`'s `Symbol`. */
const SYMBOL = /^[A-Z0-9]{2,20}USDT$/;
/** §12.2: a lookup sends only a `Symbol` within the shipped 4–20 rule (`api/instruments.py`). */
const SENDABLE = /^[A-Z0-9]{2,16}USDT$/;

/** The §6.2 causes: no answer, 503s for 60 s, or another status (`instance` only when sent). */
export type LoadFailure =
  | { readonly cause: "network" }
  | { readonly cause: "unavailable"; readonly instance: string | null }
  | { readonly cause: "http"; readonly status: number; readonly instance: string | null };

/** `GET /instruments/{symbol}`'s answer, for a check or a Recent, Favourite or current symbol. */
export type Lookup =
  /** `listed`: Trading, it joins the list; `status`: any other status, for the status rule. */
  | { readonly kind: "listed" | "status"; readonly symbol: string; readonly instrument: Instrument }
  /** A 404: no such symbol, or no longer listed. */
  | { readonly kind: "not_listed"; readonly symbol: string }
  /** No usable answer: "Couldn't check Bybit for X just now." */
  | { readonly kind: "unchecked"; readonly symbol: string };

export interface IndexSnapshot {
  /**
   * `loading`: no list, the first GET in flight or answered 503. `failed`: no list, with `failure`.
   * `ready`: a list in memory; it is stale while `staleSince` is set.
   */
  readonly phase: IndexPhase;
  /** The Trading listing. */
  readonly entries: readonly IndexEntry[];
  /** The session caches of looked-up symbols: non-Trading ones, and 404s. */
  readonly known: readonly IndexEntry[];
  readonly unlisted: readonly string[];
  /** When the list in memory arrived (the clock's ms). */
  readonly loadedAt: number | null;
  readonly cacheAgeS: number | null;
  readonly staleSince: string | null;
  /** A re-read of the list in memory has run for more than 1 s; that list is kept until it lands. */
  readonly refreshing: boolean;
  /** The next try, while loading after a 503 or failed (the clock's ms). */
  readonly retryAt: number | null;
  readonly failure: LoadFailure | null;
}

export interface InstrumentIndex {
  readonly subscribe: (listener: () => void) => () => void;
  readonly getSnapshot: () => IndexSnapshot;
  /** Reads now, then keeps the list fresh. Idempotent while running. */
  readonly start: () => void;
  /** Clears every timer and aborts the read in flight, whose answer is dropped. */
  readonly stop: () => void;
  /** Reads again now, aborting a read in flight. Inert unless started. */
  readonly reread: () => void;
  /** A lookup's answer: `listed` joins the list, `status` and `not_listed` their session caches. */
  readonly learn: (answer: Lookup) => void;
}

/** `value[key]` when `value` is an object, else `undefined`; `T` pins `key` to the contract's names. */
const field = <T>(value: unknown, key: keyof T & string): unknown =>
  typeof value === "object" && value !== null ? Reflect.get(value, key) : undefined;

/** A row this feature can use: `22`'s `Symbol`, with `base_coin` and `status` strings when present. */
export function isInstrument(value: unknown): value is Instrument {
  const symbol = field<Instrument>(value, "symbol");
  const text = (key: keyof Instrument & string): boolean => {
    const found = field<Instrument>(value, key);
    return found === undefined || typeof found === "string";
  };
  return typeof symbol === "string" && SYMBOL.test(symbol) && text("base_coin") && text("status");
}

interface Answer {
  readonly ok: boolean;
  readonly status: number;
  readonly body: unknown;
  /** The wait the server asked for (`retryAfter`), or `null`. */
  readonly retryAfterS: number | null;
}

/** Whole seconds only (`22`'s `RetryAfter`): an HTTP date or a `null` is not sent. */
function retryAfter(res: Response, body: unknown): number | null {
  const sent =
    res.headers.get("Retry-After") ?? field<Schemas["Problem"]>(body, "retry_after_seconds");
  const text = typeof sent === "number" ? String(sent) : sent;
  if (typeof text !== "string" || !/^\s*\d+\s*$/.test(text)) return null;
  return Math.min(Math.max(Number(text), 1), MAX_RETRY_AFTER_S);
}

/** One GET (or a POST), ended by `signal` or the deadline; `null` when no answer came. */
async function getJson(
  path: string,
  signal: AbortSignal,
  clock: Clock,
  method = "GET",
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
    const res = await apiFetch(path, { method, signal: call.signal });
    // A broken success body is no answer; a refusal's body is optional.
    const body: unknown = res.ok ? await res.json() : await res.json().catch(() => null);
    return { ok: res.ok, status: res.status, body, retryAfterS: retryAfter(res, body) };
  } catch {
    return null;
  } finally {
    clock.clearTimeout(deadline);
    signal.removeEventListener("abort", end);
  }
}

/** `GET /instruments/{symbol}`, for a check or a Recent, Favourite or current symbol (§3 row 2). */
export async function lookupSymbol(
  symbol: string,
  signal: AbortSignal,
  clock: Clock = SYSTEM_CLOCK,
): Promise<Lookup> {
  if (!SENDABLE.test(symbol)) return { kind: "unchecked", symbol };
  const answer = await getJson(`/api/v1/instruments/${encodeURIComponent(symbol)}`, signal, clock);
  const body = answer?.body;
  if (answer?.status === 404) return { kind: "not_listed", symbol };
  if (answer?.ok !== true || !isInstrument(body) || body.symbol !== symbol) {
    return { kind: "unchecked", symbol };
  }
  return { kind: body.status === "Trading" ? "listed" : "status", symbol, instrument: body };
}

/** `POST /instruments/refresh` (the Owner's `instruments:write`): its answer, by status and `code` only (§12.2). */
export type RefreshAnswer =
  | { readonly kind: "requested" }
  | { readonly kind: "refused" }
  | { readonly kind: "rate_limited" | "exchange_rate_limited"; readonly waitS: number };

export async function requestRefresh(clock: Clock = SYSTEM_CLOCK): Promise<RefreshAnswer> {
  const signal = new AbortController().signal;
  const answer = await getJson("/api/v1/instruments/refresh", signal, clock, "POST");
  if (answer?.status === 202) return { kind: "requested" };
  const code = field<Schemas["Problem"]>(answer?.body, "code");
  if (answer?.status !== 429 || (code !== "rate_limited" && code !== "exchange_rate_limited"))
    return { kind: "refused" };
  return { kind: code, waitS: answer.retryAfterS ?? 1 };
}

type ReadOutcome =
  | { readonly ok: true; readonly items: readonly Instrument[]; readonly meta: unknown }
  | { readonly ok: false; readonly failure: LoadFailure; readonly retryAfterS: number | null };

function refused({ status, body, retryAfterS }: Answer): ReadOutcome {
  const sent = field<Schemas["Problem"]>(body, "instance");
  const instance = typeof sent === "string" ? sent : null;
  const failure: LoadFailure =
    status === 503 ? { cause: "unavailable", instance } : { cause: "http", status, instance };
  return { ok: false, failure, retryAfterS };
}

async function readAll(signal: AbortSignal, clock: Clock): Promise<ReadOutcome> {
  const items: Instrument[] = [];
  let meta: unknown;
  let cursor = "";
  for (let page = 0; page < MAX_PAGES; page += 1) {
    const path = `/api/v1/instruments?status=Trading&limit=${PAGE_LIMIT}${cursor}`;
    const answer = await getJson(path, signal, clock);
    if (answer === null) return { ok: false, failure: { cause: "network" }, retryAfterS: null };
    const rows = field<ListBody>(answer.body, "items");
    if (!answer.ok || !Array.isArray(rows)) return refused(answer);
    items.push(...rows.filter(isInstrument));
    meta = field<ListBody>(answer.body, "meta");
    const more = field<Schemas["InstrumentsPageMeta"]>(meta, "has_more") === true;
    const next = field<Schemas["InstrumentsPageMeta"]>(meta, "next_cursor");
    if (!more || typeof next !== "string") break;
    cursor = `&cursor=${encodeURIComponent(next)}`;
  }
  return { ok: true, items, meta };
}

const INITIAL: IndexSnapshot = {
  phase: "loading",
  entries: [],
  known: [],
  unlisted: [],
  loadedAt: null,
  cacheAgeS: null,
  staleSince: null,
  refreshing: false,
  retryAt: null,
  failure: null,
};

export function createInstrumentIndex(clock: Clock = SYSTEM_CLOCK): InstrumentIndex {
  const listeners = new Set<() => void>();
  let snap = INITIAL;
  let running = false;
  let controller: AbortController | null = null;
  let next: unknown = null;
  let slow: unknown = null;
  /** Turns `loading` into `failed` 60 s into the 503s, while a later try is still pending. */
  let flip: unknown = null;
  /** The episode's first answer, for the 60 s rule, and its answers since, for the ladder. */
  let since = 0;
  let unavailable = 0;

  const set = (patch: Partial<IndexSnapshot>): void => {
    snap = { ...snap, ...patch };
    for (const listener of listeners) {
      try {
        listener();
      } catch (error) {
        // A subscriber's own failure is raised on its own, as `lib/ws` does: the others are
        // still told, and the schedule stands.
        clock.queueMicrotask(() => {
          throw error;
        });
      }
    }
  };
  const halt = (): void => {
    for (const timer of [next, slow, flip]) if (timer !== null) clock.clearTimeout(timer);
    next = slow = flip = null;
    controller?.abort();
    controller = null;
  };
  const schedule = (ms: number): void => {
    next = clock.setTimeout(() => {
      next = null;
      void read();
    }, ms);
  };

  async function read(): Promise<void> {
    halt();
    const own = new AbortController();
    controller = own;
    if (snap.phase === "ready") {
      slow = clock.setTimeout(() => {
        slow = null;
        set({ refreshing: true });
      }, REFRESHING_AFTER_MS);
    }
    const out = await readAll(own.signal, clock);
    if (controller !== own) return; // stopped, or a newer read replaced this one
    controller = null; // done: `halt` only clears the timers
    halt();
    const now = clock.now();
    if (out.ok) {
      schedule(REREAD_MS);
      // One row per symbol, should an offset cursor shift under a server refresh.
      const unique = new Map(out.items.map((i): [string, Instrument] => [i.symbol, i]));
      const entries = [...unique.values()].filter((i) => i.status === "Trading").map(toEntry);
      const listed = new Set(entries.map((e) => e.symbol));
      const age = field<Schemas["InstrumentsPageMeta"]>(out.meta, "cache_age_s");
      const stale = field<Schemas["InstrumentsPageMeta"]>(out.meta, "stale_since");
      return set({
        phase: "ready",
        entries,
        known: snap.known.filter((e) => !listed.has(e.symbol)),
        unlisted: snap.unlisted.filter((s) => !listed.has(s)),
        loadedAt: now,
        cacheAgeS: typeof age === "number" ? age : null,
        staleSince: typeof stale === "string" ? stale : null,
        refreshing: false,
        retryAt: null,
        failure: null,
      });
    }
    if (snap.phase === "ready") {
      schedule(REREAD_MS);
      return set({ refreshing: false }); // a failed re-read keeps the list
    }
    if (snap.phase === "loading" && unavailable === 0) since = now;
    const end = since + UNAVAILABLE_FOR_MS; // 503s for 60 s are "Load failed" (§6.2)
    const loading = snap.phase === "loading" && out.failure.cause === "unavailable" && now < end;
    const asked = out.retryAfterS === null ? null : out.retryAfterS * 1000;
    const step = Math.min(2 ** (unavailable + 1), MAX_STEP_S) * 1000;
    // A try due past the 60 s mark comes in `failed`: it waits as `failed` does, and the
    // state turns `failed` on time, on its own timer, with that try kept.
    const late = loading && now + (asked ?? step) > end;
    const wait = loading && !late ? (asked ?? step) : Math.max(RETRY_FAILED_MS, asked ?? 0);
    unavailable += 1;
    schedule(wait);
    if (late) {
      const { failure } = out;
      flip = clock.setTimeout(() => {
        flip = null;
        set({ phase: "failed", failure });
      }, end - now);
    }
    set({
      phase: loading ? "loading" : "failed",
      failure: loading ? null : out.failure,
      retryAt: now + wait,
    });
  }

  return {
    subscribe(listener) {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    getSnapshot: () => snap,
    start() {
      if (running) return;
      running = true;
      unavailable = 0;
      void read();
    },
    stop() {
      running = false;
      halt();
    },
    reread() {
      if (running) void read();
    },
    learn(answer) {
      if (answer.kind === "unchecked") return;
      const { symbol } = answer;
      const entries = snap.entries.filter((e) => e.symbol !== symbol);
      const known = snap.known.filter((e) => e.symbol !== symbol);
      const unlisted = snap.unlisted.filter((s) => s !== symbol);
      if (answer.kind === "not_listed") {
        return set({ entries, known, unlisted: [...unlisted, symbol] });
      }
      const entry = toEntry(answer.instrument);
      if (answer.kind === "listed") return set({ entries: [...entries, entry], known, unlisted });
      set({ entries, known: [...known, entry], unlisted });
    },
  };
}
