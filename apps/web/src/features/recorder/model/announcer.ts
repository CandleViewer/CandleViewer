/**
 * SCR-140's summary-region cadence (E16-D02 §9.3; E16-D06 SR-01, SR-05, SR-06, BG-01, BG-06):
 * changes of state only, at most one polite utterance per 10 s window, the changes of a window
 * spoken as one batch so none is lost. The assertive set (the level-3 and incident banners and a
 * failed purge, BG-05) is said once per key while its condition holds; coalescing never swallows
 * one, and one that arrives while a batch is waiting is spoken right after that batch (BG-06).
 * Ticking numbers never come here (BG-04). The page owns the regions and passes `say`.
 */
export const BATCH_WINDOW_MS = 10_000;

export type Politeness = "polite" | "assertive";
type Timer = ReturnType<typeof setTimeout>;

export interface AnnouncerClock {
  readonly now: () => number;
  readonly setTimer: (run: () => void, ms: number) => Timer;
  readonly clearTimer: (timer: Timer) => void;
}

export interface BatchAnnouncer {
  /** Queues phrases ("ETHUSDT degraded") for the window's batch, joined with "; ". */
  push(phrases: readonly string[]): void;
  /** An assertive row, once per `key` until `release(key)`. */
  alert(key: string, text: string): void;
  /** The condition ended: `key` may be said again when it next holds. */
  release(key: string): void;
  dispose(): void;
}

const SYSTEM_CLOCK: AnnouncerClock = {
  now: () => Date.now(),
  setTimer: (run, ms) => setTimeout(run, ms),
  clearTimer: (timer) => clearTimeout(timer),
};

export function createBatchAnnouncer(
  say: (politeness: Politeness, text: string) => void,
  clock: AnnouncerClock = SYSTEM_CLOCK,
): BatchAnnouncer {
  let pending: string[] = [];
  let held: string[] = [];
  const said = new Set<string>();
  let lastBatchAt = Number.NEGATIVE_INFINITY;
  let timer: Timer | null = null;

  const flush = (): void => {
    timer = null;
    if (pending.length > 0) {
      say("polite", pending.join("; "));
      lastBatchAt = clock.now();
      pending = [];
    }
    for (const text of held) say("assertive", text);
    held = [];
  };

  return {
    push(phrases) {
      for (const phrase of phrases) if (!pending.includes(phrase)) pending.push(phrase);
      if (pending.length === 0 || timer !== null) return;
      const wait = lastBatchAt + BATCH_WINDOW_MS - clock.now();
      if (wait <= 0) flush();
      else timer = clock.setTimer(flush, wait);
    },
    alert(key, text) {
      if (said.has(key)) return;
      said.add(key);
      if (timer === null) say("assertive", text);
      else held.push(text);
    },
    release(key) {
      said.delete(key);
    },
    dispose() {
      if (timer !== null) clock.clearTimer(timer);
      timer = null;
      pending = [];
      held = [];
    },
  };
}
