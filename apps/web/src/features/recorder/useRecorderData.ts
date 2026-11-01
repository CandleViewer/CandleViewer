/**
 * SCR-140's reads (E16-D02 §2, §3.1; Q-04; BQ-6, BQ-7, BQ-10): the three first-paint GETs (the whole list, page by
 * page; the status; the storage, again every 60 s), the `recorder` topic for the live view, a stopped row's last
 * session (its "Stopped … gone by", read as a row reaches `stopped`, again after each restart) and each active
 * symbol's gaps of the last 24 h (`getDataCoverage`, one symbol per call, four at a time, at mount, every 60 s and
 * when the degraded rows change). Nothing polls the status (Q-04): the topic asks for the reads again once after a
 * reconnect, and for the list when its rows change or a write landed (`rereadList`), through its 5 s gap. A part
 * that never loaded is `failed` until a Retry; a later read that fails keeps the part's last data, and an add merged
 * after a list read began stands until a later read has it.
 */
import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";
import type { generated } from "@candleviewer/protocol";
import type { RecordedSymbol, RecordingStatus, StorageUsage } from "./model/types";
import { parseMs } from "./model";
import { recorderApi, type DataCoverage } from "./recorderApi";
import {
  openRecorderTopic,
  type RecorderTopic,
  type RecorderTopicOptions,
  type RecorderTopicView,
} from "./recorderTopic";

type Session = generated.rest.components["schemas"]["RecordingSession"];

export interface Part<T> {
  readonly data: T | null;
  readonly state: "loading" | "ready" | "failed";
}

/** One gap of the last 24 h (D02 §1's gap table: start, end, duration, reason). */
export interface Gap {
  readonly symbol: string;
  readonly fromMs: number;
  readonly toMs: number;
  /** `DataCoverage.gaps[].reason`, open-ended for readers (C-6.3). */
  readonly reason: string | null;
}

export interface RecorderData {
  readonly list: Part<readonly RecordedSymbol[]>;
  readonly status: Part<RecordingStatus>;
  readonly storage: Part<StorageUsage>;
  readonly view: RecorderTopicView;
  /** A stopped row's last session `ended_at` (ms), by symbol. */
  readonly stoppedAtMs: ReadonlyMap<string, number>;
  /** The last 24 h's gaps, newest first, one per interval and symbol whatever the stream. */
  readonly gaps: readonly Gap[];
  /** Reads every part that failed again; true once the three have loaded. */
  readonly retry: () => Promise<boolean>;
  /** Asks for the list again (after a write, or a step-up's lost answer), through the topic's 5 s gap (BQ-7). */
  readonly rereadList: () => void;
  /** An add's answer, in the list by symbol until the list is read again. */
  readonly merge: (row: RecordedSymbol) => void;
}

export interface RecorderDataOptions {
  /** The topic's client and clock (tests inject a fake socket and frame). */
  readonly topic?: Omit<RecorderTopicOptions, "onReread">;
  readonly now?: () => number;
}

export const COVERAGE_EVERY_MS = 60_000;
/** D02 §2: the disk bar's used figure is re-read every 60 s (`CV_DISK_SAMPLE_INTERVAL_S`). */
export const STORAGE_EVERY_MS = 60_000;
const COVERAGE_AT_ONCE = 4;
const DAY_MS = 86_400_000;
const LOADING = { data: null, state: "loading" } as const;
const NO_VIEW: RecorderTopicView = { frame: null, frameAtMs: null, serverMs: null, stale: false };
const noSubscription = (): (() => void) => () => undefined;

/** A read's outcome on its part: the data, else `failed` only while nothing has loaded. */
const settled = <T>(prev: Part<T>, data: T | null): Part<T> =>
  data !== null
    ? { data, state: "ready" }
    : prev.data === null
      ? { data: null, state: "failed" }
      : prev;

/** A symbol's gaps of the last 24 h, one per interval and reason, whatever the stream. */
function gapsOf(symbol: string, coverage: DataCoverage, sinceMs: number): Gap[] {
  const seen = new Map<string, Gap>();
  for (const stream of coverage.streams ?? []) {
    for (const gap of stream.gaps ?? []) {
      const fromMs = parseMs(gap.from);
      const toMs = parseMs(gap.to);
      if (fromMs === null || toMs === null || toMs < sinceMs) continue;
      const reason = gap.reason ?? null;
      seen.set(`${fromMs}|${toMs}|${reason}`, { symbol, fromMs, toMs, reason });
    }
  }
  return [...seen.values()];
}

/**
 * A stopped row's end (A-5309-01): its newest session's `ended_at`, by `started_at` (else `ended_at`); none while that
 * session is still open, so an earlier stop's date never stands in for this one.
 */
function lastEnd(sessions: readonly Session[]): number | null {
  const key = (s: Session): number => parseMs(s.started_at) ?? parseMs(s.ended_at) ?? 0;
  const newest = [...sessions].sort((a, b) => key(b) - key(a))[0];
  return newest === undefined ? null : parseMs(newest.ended_at);
}

/** `items` with each merged row in its place by symbol, or after them (an add the read had not seen). */
function withMerged(
  items: readonly RecordedSymbol[],
  merged: readonly RecordedSymbol[],
): RecordedSymbol[] {
  const rows = [...items];
  for (const row of merged) {
    const at = rows.findIndex((r) => r.symbol === row.symbol);
    if (at < 0) rows.push(row);
    else rows[at] = row;
  }
  return rows;
}

/** Runs `tasks` with at most `limit` in flight. */
async function inBatches(tasks: readonly (() => Promise<void>)[], limit: number): Promise<void> {
  let next = 0;
  const lane = async (): Promise<void> => {
    while (next < tasks.length) await tasks[next++]?.();
  };
  await Promise.all(Array.from({ length: Math.min(limit, tasks.length) }, lane));
}

export function useRecorderData(options: RecorderDataOptions = {}): RecorderData {
  // The page's clock, read when a round of reads starts.
  const clock = useRef(options.now ?? Date.now);
  clock.current = options.now ?? Date.now;
  const [list, setList] = useState<Part<readonly RecordedSymbol[]>>(LOADING);
  const [status, setStatus] = useState<Part<RecordingStatus>>(LOADING);
  const [storage, setStorage] = useState<Part<StorageUsage>>(LOADING);
  const [stoppedAtMs, setStoppedAtMs] = useState<ReadonlyMap<string, number>>(new Map());
  const [gaps, setGaps] = useState<ReadonlyMap<string, readonly Gap[]>>(new Map());
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  // C-5309-13: an add merged after a list read began stands until a read begun after it lands.
  const sequence = useRef(0);
  const merged = useRef(new Map<string, { readonly row: RecordedSymbol; readonly at: number }>());
  const readList = useCallback(async (): Promise<boolean> => {
    sequence.current += 1;
    const began = sequence.current;
    const res = await recorderApi.listAll();
    // A 2xx with no list is no list (A-5309-02): `listAll` answers it as a failure.
    const items = res.ok && res.data !== null ? res.data.items : null;
    if (!alive.current) return items !== null;
    if (items !== null) {
      for (const [symbol, add] of merged.current) if (add.at < began) merged.current.delete(symbol);
    }
    const later = [...merged.current.values()].map((add) => add.row);
    setList((prev) => settled(prev, items === null ? null : withMerged(items, later)));
    return items !== null;
  }, []);
  const readStatus = useCallback(async (): Promise<boolean> => {
    const res = await recorderApi.status();
    if (alive.current) setStatus((prev) => settled(prev, res.ok ? res.data : null));
    return res.ok;
  }, []);
  const readStorage = useCallback(async (): Promise<boolean> => {
    const res = await recorderApi.storage();
    if (alive.current) setStorage((prev) => settled(prev, res.ok ? res.data : null));
    return res.ok;
  }, []);
  const readAll = useCallback(
    async (): Promise<boolean> =>
      (await Promise.all([readList(), readStatus(), readStorage()])).every(Boolean),
    [readList, readStatus, readStorage],
  );
  useEffect(() => {
    void readAll();
  }, [readAll]);

  // The disk figures again every 60 s (D02 §2; C-5309-10 (b)): the frame carries the level, REST the bar's figure.
  useEffect(() => {
    const every = setInterval(() => void readStorage(), STORAGE_EVERY_MS);
    return () => clearInterval(every);
  }, [readStorage]);

  // The topic, opened once; the reconnect re-reads the three, a change of rows the list (BQ-6, BQ-7).
  const topicOptions = useRef(options.topic);
  const [topic, setTopic] = useState<RecorderTopic | null>(null);
  useEffect(() => {
    const opened = openRecorderTopic({
      ...topicOptions.current,
      onReread: (cause) => (cause === "reconnect" ? readAll() : readList()),
    });
    setTopic(opened);
    return () => opened.close();
  }, [readAll, readList]);
  const view = useSyncExternalStore(
    topic?.subscribe ?? noSubscription,
    topic === null ? () => NO_VIEW : topic.getView,
  );

  // Each symbol's live state: the frame's (an untracked `idle` aside) over REST's (A-5309-01).
  const states = new Map<string, string>();
  for (const row of list.data ?? []) states.set(row.symbol, row.state ?? "");
  for (const row of view.frame?.symbols ?? [])
    if (row.state !== "idle") states.set(row.symbol, row.state);
  const ofState = (stopped: boolean): string =>
    [...states]
      .filter(([, state]) => (state === "stopped") === stopped)
      .map(([symbol]) => symbol)
      .sort()
      .join(",");

  // A stopped row's last session (its end and the retention's "gone by", D02 §2), read as the row reaches `stopped`,
  // a stop seen live included; a row that leaves `stopped` forgets its end, so its next stop is read again.
  const asked = useRef(new Set<string>());
  const stoppedKey = ofState(true);
  useEffect(() => {
    const stopped = new Set(stoppedKey === "" ? [] : stoppedKey.split(","));
    for (const symbol of [...asked.current]) {
      if (stopped.has(symbol)) continue;
      asked.current.delete(symbol);
      setStoppedAtMs((prev) => {
        if (!prev.has(symbol)) return prev;
        const next = new Map(prev);
        next.delete(symbol);
        return next;
      });
    }
    for (const symbol of stopped) {
      if (asked.current.has(symbol)) continue;
      asked.current.add(symbol);
      void recorderApi.sessions({ symbol, limit: 100 }).then((res) => {
        const end = lastEnd(res.data?.items ?? []);
        if (!alive.current || end === null || !asked.current.has(symbol)) return;
        setStoppedAtMs((prev) => new Map(prev).set(symbol, end));
      });
    }
  }, [stoppedKey]);

  // The gaps: every active symbol (never a stopped one's, BQ-10's 20 at most) at mount, every 60 s, and again when
  // the degraded rows change (BQ-10).
  const symbols = ofState(false);
  const degraded = (view.frame?.symbols ?? [])
    .filter((row) => row.state === "degraded")
    .map((row) => row.symbol)
    .join(",");
  useEffect(() => {
    if (symbols === "") return undefined;
    const read = (): void => {
      const since = clock.current() - DAY_MS;
      const tasks = symbols.split(",").map((symbol) => async () => {
        const res = await recorderApi.coverage({ symbol });
        if (!alive.current || !res.ok || res.data === null) return;
        const found = gapsOf(symbol, res.data, since);
        setGaps((prev) => new Map(prev).set(symbol, found));
      });
      void inBatches(tasks, COVERAGE_AT_ONCE);
    };
    read();
    const every = setInterval(read, COVERAGE_EVERY_MS);
    return () => clearInterval(every);
  }, [symbols, degraded]);

  const retry = useCallback(async (): Promise<boolean> => {
    const reads = [
      list.state === "failed" ? readList() : Promise.resolve(true),
      status.state === "failed" ? readStatus() : Promise.resolve(true),
      storage.state === "failed" ? readStorage() : Promise.resolve(true),
    ];
    return (await Promise.all(reads)).every(Boolean);
  }, [list.state, status.state, storage.state, readList, readStatus, readStorage]);

  // A write's re-read goes through the topic's gap and its one in flight (C-5309-10 (c)); before the topic opens, at once.
  const rereadList = useCallback((): void => {
    if (topic === null) void readList();
    else topic.requestRows();
  }, [topic, readList]);
  const merge = useCallback((row: RecordedSymbol): void => {
    sequence.current += 1;
    merged.current.set(row.symbol, { row, at: sequence.current });
    setList((prev) => ({ data: withMerged(prev.data ?? [], [row]), state: "ready" }));
  }, []);

  const allGaps = [...gaps.values()].flat().sort((a, b) => b.fromMs - a.fromMs);
  return { list, status, storage, view, stoppedAtMs, gaps: allGaps, retry, rereadList, merge };
}
