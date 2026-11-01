/**
 * SCR-142's reads (E16-D04 §3; E16-D06 C-w, §16.1): `GET /recording/storage` and `GET /admin/health` on entry, every
 * 60 s while the section is mounted, and on Retry. The figures are the server's 60 s sample, never computed for a
 * request (the ticket's Performance note): this reads the last sample. Each answer is committed as it lands, so a
 * report never waits on health's answer; an answer to an older read that lands after a newer one's changes nothing,
 * and the newer sample always wins, the page's seed included (C-486P3-07). A storage read that fails keeps the last
 * good report (the stamp turns stale, `failed` says why); a health read that fails keeps the last health, which
 * `healthFailed` tags. The clock ticks every 5 s, so the stamp turns stale with no new answer.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { parseMs, type StorageUsage } from "../model";
import { recorderApi, type HealthReport } from "../recorderApi";
import { SAMPLE_EVERY_MS } from "./storageModel";

/** How often the stamp's age is read again (its words are whole seconds and minutes). */
export const CLOCK_TICK_MS = 5_000;

/** What a read brought: whether the report came, and the health that did. */
export interface ReadOutcome {
  readonly storage: boolean;
  readonly health: HealthReport | null;
}

export interface StorageReads {
  /** The newest report: the section's own read, or the page's seed when newer. */
  readonly report: StorageUsage | null;
  /** The latest storage read failed (the unavailable state): the report, if any, is the last good one. */
  readonly failed: boolean;
  /** No report yet and the first read unanswered (the loading state). */
  readonly loading: boolean;
  /** The last health report that came; null until one does. */
  readonly health: HealthReport | null;
  /** The latest health read failed: `health`, if any, is the last good one (C-486P3-07). */
  readonly healthFailed: boolean;
  /** The section's clock, ms. */
  readonly nowMs: number;
  /** Reads both again (a Retry); resolves with what came, once both have answered. */
  readonly retry: () => Promise<ReadOutcome>;
}

/** The reads of one kind: how many were sent, and the newest whose answer has landed. */
interface Order {
  issued: number;
  landed: number;
}

const sampledAt = (report: StorageUsage | null): number =>
  parseMs(report?.generated_at) ?? Number.NEGATIVE_INFINITY;

export function useStorageReport(
  seed: StorageUsage | null,
  now: () => number = Date.now,
): StorageReads {
  const clock = useRef(now);
  clock.current = now;
  const [own, setOwn] = useState<StorageUsage | null>(null);
  const [failed, setFailed] = useState(false);
  const [answered, setAnswered] = useState(false);
  const [health, setHealth] = useState<HealthReport | null>(null);
  const [healthFailed, setHealthFailed] = useState(false);
  const [nowMs, setNowMs] = useState(() => now());
  const alive = useRef(true);
  const storageReads = useRef<Order>({ issued: 0, landed: 0 });
  const healthReads = useRef<Order>({ issued: 0, landed: 0 });
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  const read = useCallback(async (): Promise<ReadOutcome> => {
    /** True when this read is the newest to land of its kind: an older answer landing late is dropped. */
    const lands = (order: Order, seq: number): boolean => {
      if (!alive.current || seq < order.landed) return false;
      order.landed = seq;
      return true;
    };
    const readStorage = async (): Promise<boolean> => {
      storageReads.current.issued += 1;
      const seq = storageReads.current.issued;
      const res = await recorderApi.storage();
      const report = res.ok ? res.data : null;
      if (lands(storageReads.current, seq)) {
        if (report !== null) {
          setOwn((prev) => (sampledAt(report) >= sampledAt(prev) ? report : prev));
        }
        setFailed(report === null);
        setAnswered(true);
        setNowMs(clock.current());
      }
      return report !== null;
    };
    const readHealth = async (): Promise<HealthReport | null> => {
      healthReads.current.issued += 1;
      const seq = healthReads.current.issued;
      const res = await recorderApi.health();
      const report = res.ok ? res.data : null;
      if (lands(healthReads.current, seq)) {
        if (report !== null) setHealth(report);
        setHealthFailed(report === null);
      }
      return report;
    };
    const [storage, healthReport] = await Promise.all([readStorage(), readHealth()]);
    return { storage, health: healthReport };
  }, []);

  useEffect(() => {
    void read();
    const every = setInterval(() => void read(), SAMPLE_EVERY_MS);
    return () => clearInterval(every);
  }, [read]);

  useEffect(() => {
    const tick = setInterval(() => setNowMs(clock.current()), CLOCK_TICK_MS);
    return () => clearInterval(tick);
  }, []);

  const report = sampledAt(seed) > sampledAt(own) ? seed : (own ?? seed);
  return {
    report,
    failed,
    loading: !answered && report === null,
    health,
    healthFailed,
    nowMs,
    retry: read,
  };
}
