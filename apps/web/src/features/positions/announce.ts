/**
 * The Positions panel's announcements (E29-S01 #911) through the shell's one announcer
 * (`app-shell/announcer.tsx`; E17-D02 §11: the panel owns no live region). The routing is E29-D05
 * §8.1's (PROPOSED, owner approval pending on #2701):
 *
 * - **RT-05**, a crossing into Critical: assertive, once per crossing; **RT-12**, a Near crossing:
 *   polite, once per crossing. The store hands each crossing once (`PositionsSnapshot.crossings`,
 *   whose `seq` never repeats).
 * - **RT-07**, the stale lock and the kill-switch lock: assertive, once per episode, in D03:329's
 *   words by variant; **RT-11**, reconciling, desync and synced: polite, once per episode.
 *   `accountSignals` numbers the episodes and `accountLine` gives D03 §4.1's words. An episode waits
 *   until the directory lists its account, so it is said by the account's label, never an id stub.
 * - **RT-15**, could not load and an account withdrawn: polite, once (the panel's lines).
 * - **RT-16**, the focused row's changed values and the totals: polite, at most once per 2 s per
 *   field, through the chart's ambient writer (`chart/a11y/politeWriter.ts`), with "significant",
 *   under the default preference, read as a sign change of uPnL or R (D05 §8.1, C-06).
 * - **Serialised, never concatenated** (D05 §8.3): a region takes one message at a time, each after
 *   the shell's per-region budget (`REGION_BUDGET_MS`), so no writer cuts another's message; a batch
 *   goes most severe first. At most `MAX_QUEUED` wait per region (C-2.18): past it the oldest goes.
 *   A message said into a `slot` replaces the one of that slot still waiting (latest wins).
 *
 * The sentences composed here (a crossing, a value change) are PROPOSED to E29-D03's copy owner
 * (G-W3): each joins words a design gives (the row's name, E29-D05 N-01; the tier sentence, D02
 * §5.3; CMP-116's reading).
 */
import { useEffect, useRef } from "react";
import { liqSentence, pnlReading } from "@candleviewer/ui";
import { sayToShell } from "../../chart/a11y/politeWriter";
import { REGION_BUDGET_MS, lastWrittenAt, type Politeness } from "../app-shell/announcer";
import { accountLine, type AccountSignal } from "./accountSignals";
import { bindKinds, bindTextKinds } from "./copy";
import { parseDecimal } from "./model/decimal";
import type { LiqReading } from "./model/liqTier";
import type { PositionRowModel } from "./model/rowMapping";

/** The messages a region holds at most while it waits for its budget (C-2.18). */
export const MAX_QUEUED = 8;

export interface AnnouncerTimers {
  setTimeout(callback: () => void, ms: number): unknown;
  clearTimeout(handle: unknown): void;
}

export interface PanelAnnouncer {
  /**
   * Queues one message; it is written when its region's budget allows. With `slot`, it replaces
   * the message of that slot still waiting, in its place (a newer result of the same kind).
   */
  say(politeness: Politeness, text: string, slot?: string): void;
  /** Drops what waits; nothing is written after it. */
  dispose(): void;
}

export interface PanelAnnouncerOptions {
  /** Writes one message; defaults to the shell announcer (`sayToShell`, a fresh key each time). */
  readonly write?: ((politeness: Politeness, text: string) => void) | undefined;
  /** When a region was last written (epoch ms); defaults to the shell announcer's. */
  readonly lastWrittenAt?: ((politeness: Politeness) => number) | undefined;
  readonly now?: (() => number) | undefined;
  readonly timers?: AnnouncerTimers | undefined;
}

const platformTimers: AnnouncerTimers = {
  setTimeout: (callback, ms) => setTimeout(callback, ms),
  clearTimeout: (handle) => clearTimeout(handle as ReturnType<typeof setTimeout>),
};

interface Queued {
  text: string;
  readonly slot: string | undefined;
}

export function createPanelAnnouncer(options: PanelAnnouncerOptions = {}): PanelAnnouncer {
  const write = options.write ?? sayToShell;
  const writtenAt = options.lastWrittenAt ?? lastWrittenAt;
  const now = options.now ?? ((): number => Date.now());
  const timers = options.timers ?? platformTimers;
  const queues: Record<Politeness, Queued[]> = { polite: [], assertive: [] };
  const pending: Record<Politeness, unknown> = { polite: undefined, assertive: undefined };
  let disposed = false;

  function pump(region: Politeness): void {
    pending[region] = undefined;
    if (disposed) return;
    const queue = queues[region];
    if (queue.length === 0) return;
    const due = writtenAt(region) + REGION_BUDGET_MS;
    const at = now();
    if (at < due) {
      pending[region] = timers.setTimeout(() => pump(region), due - at);
      return;
    }
    const next = queue.shift();
    if (next !== undefined) write(region, next.text);
    if (queue.length > 0) pending[region] = timers.setTimeout(() => pump(region), REGION_BUDGET_MS);
  }

  return {
    say(politeness, text, slot) {
      if (disposed || text.trim() === "") return;
      const queue = queues[politeness];
      const waiting = slot === undefined ? undefined : queue.find((q) => q.slot === slot);
      if (waiting !== undefined) {
        waiting.text = text; // latest wins, in the place the first took
        return;
      }
      queue.push({ text, slot });
      if (queue.length > MAX_QUEUED) queue.shift();
      if (pending[politeness] === undefined) pump(politeness);
    },
    dispose() {
      disposed = true;
      for (const region of ["polite", "assertive"] as const) {
        if (pending[region] !== undefined) timers.clearTimeout(pending[region]);
        pending[region] = undefined;
        queues[region] = [];
      }
    },
  };
}

/**
 * The panel's announcer for a component's lifetime: created on first use and disposed on unmount,
 * so nothing is written after it. StrictMode's simulated unmount disposes it and its second mount
 * makes the next `say` create a fresh one (as `chart/a11y/politeWriter.ts`'s `useAmbientWriter`
 * does), so a development build is never left silent. The facade is stable across renders.
 */
export function usePanelAnnouncer(options?: PanelAnnouncerOptions): PanelAnnouncer {
  const optionsRef = useRef(options);
  const inner = useRef<PanelAnnouncer | null>(null);
  const unmounted = useRef(false);
  useEffect(() => {
    unmounted.current = false; // StrictMode's second mount: the next say creates a fresh announcer
    return () => {
      unmounted.current = true;
      inner.current?.dispose();
      inner.current = null;
    };
  }, []);
  const facade = useRef<PanelAnnouncer | null>(null);
  facade.current ??= {
    say: (politeness, text, slot) => {
      if (unmounted.current) return;
      inner.current ??= createPanelAnnouncer(optionsRef.current);
      inner.current.say(politeness, text, slot);
    },
    dispose: () => inner.current?.dispose(),
  };
  return facade.current;
}

/** One message of a batch, with the rank that orders it (D05 §8.3: most severe first). */
export interface Announcement {
  readonly politeness: Politeness;
  readonly text: string;
  /** Lower first: a lock 0, a Critical crossing 1, the rest 2. */
  readonly rank: number;
}

/** Hands a batch to the announcer, most severe first; equal ranks keep their order. */
export function sayAll(announcer: PanelAnnouncer, batch: readonly Announcement[]): void {
  const ordered = batch.map((a, i) => ({ a, i })).sort((x, y) => x.a.rank - y.a.rank || x.i - y.i);
  for (const { a } of ordered) announcer.say(a.politeness, a.text);
}

/** E29-D05 N-01's short name of a row: "BTCUSDT Long on Main". */
export const rowName = (
  row: Pick<PositionRowModel, "symbol" | "sideWord" | "accountLabel" | "accountId">,
): string => `${row.symbol} ${row.sideWord} on ${row.accountLabel ?? row.accountId}`;

/**
 * A crossing's sentence (RT-05, RT-12; PROPOSED): the row's name and D02 §5.3's tier sentence, "ETHUSDT Short on
 * Sub-1: Near liquidation: 27 % of the entry buffer left, 1.2 % from liquidation".
 */
export function crossingText(
  row: Pick<PositionRowModel, "symbol" | "sideWord" | "accountLabel" | "accountId">,
  reading: LiqReading,
): string | undefined {
  const sentence = liqSentence({
    tier: reading.tier,
    distancePct: reading.distancePct,
    sharePct: reading.sharePct,
    mmRatePct: reading.mmRatePct,
  });
  return sentence === undefined ? undefined : `${rowName(row)}: ${sentence}`;
}

/** The crossings of one commit as announcements: Critical assertive (RT-05), Near polite (RT-12). */
export function crossingAnnouncements(
  crossings: readonly { readonly key: string; readonly crossing: "near" | "critical" }[],
  rowOf: (key: string) => PositionRowModel | undefined,
  readingOf: (key: string) => LiqReading | undefined,
): readonly Announcement[] {
  const out: Announcement[] = [];
  for (const { key, crossing } of crossings) {
    const row = rowOf(key);
    const reading = readingOf(key);
    const text =
      row === undefined || reading === undefined ? undefined : crossingText(row, reading);
    if (text === undefined) continue;
    out.push(
      crossing === "critical"
        ? { politeness: "assertive", text, rank: 1 }
        : { politeness: "polite", text, rank: 2 },
    );
  }
  return out;
}

/** What the account announcements remember: the episode each account last said. */
export type SaidEpisodes = ReadonlyMap<string, number>;

/**
 * RT-07 and RT-11 for a signals change: each account's new episode once (its `accountLine` announcement), and
 * `acct.announce.synced` once when an episode ends on an account still listed. An account the directory does not
 * list yet (`listed`) is held, unsaid: its episode is said once its label is known, and one that ends before
 * then is never said, nor its end; a withdrawn account's signals leave with its rows and say nothing. Returns
 * the batch and what is now said.
 */
export function accountAnnouncements(
  said: SaidEpisodes,
  accounts: ReadonlyMap<string, AccountSignal>,
  labelOf: (accountId: string) => string,
  listed: (accountId: string) => boolean,
): { readonly batch: readonly Announcement[]; readonly said: SaidEpisodes } {
  const batch: Announcement[] = [];
  const next = new Map<string, number>();
  for (const [id, signal] of accounts) {
    const line = accountLine(signal);
    if (signal.oms === null || line === null) continue;
    const before = said.get(id);
    if (!listed(id)) {
      if (before !== undefined) next.set(id, before); // what was said stays said
      continue;
    }
    next.set(id, signal.oms.episode);
    if (before === signal.oms.episode) continue;
    batch.push({
      politeness: line.announce.politeness,
      text: bindTextKinds(line.announce.text, line.announce.name, { label: labelOf(id) }),
      rank: signal.oms.state === "stale" ? 0 : 2,
    });
  }
  for (const id of said.keys()) {
    if (next.has(id) || !listed(id)) continue;
    batch.push({
      politeness: "polite",
      text: bindKinds("acct.announce.synced", { label: labelOf(id) }),
      rank: 2,
    });
  }
  return { batch, said: next };
}

/** The sign of a decimal string: -1, 0 or 1; `null` for none. */
export function signOf(value: string | null): -1 | 0 | 1 | null {
  const d = parseDecimal(value);
  if (d === null) return null;
  return d.units < 0n ? -1 : d.units > 0n ? 1 : 0;
}

/**
 * RT-16's line for the focused row (PROPOSED): "BTCUSDT Long on Main: uPnL profit 8.00 USDT, R profit 0.32 R". A
 * null R reads as CMP-114 reads it: "R unavailable: no stop price" for no stop, else "R unavailable".
 */
export function rowValuesText(
  row: Pick<
    PositionRowModel,
    "symbol" | "sideWord" | "accountLabel" | "accountId" | "unrealisedPnl" | "r"
  >,
  currency: string,
): string {
  const upnl = pnlReading({ value: row.unrealisedPnl, format: "abs", currency });
  const r =
    row.r.value === null
      ? pnlReading({
          value: null,
          format: "r",
          ...(row.r.reason === "no_stop" ? {} : { nullReading: "R unavailable" }),
        })
      : `R ${pnlReading({ value: row.r.value, format: "r", places: 2 })}`;
  return `${rowName(row)}: uPnL ${upnl}, ${r}`;
}

/** RT-16's line for the totals (PROPOSED): "LIVE total: uPnL loss 205.84 USDT". */
export function totalsValuesText(
  label: string,
  unrealisedPnl: string | null,
  currency: string,
): string {
  return `${label}: uPnL ${pnlReading({ value: unrealisedPnl, format: "abs", currency })}`;
}
