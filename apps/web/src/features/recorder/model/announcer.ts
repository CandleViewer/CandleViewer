/**
 * SCR-140's summary-region cadence (E16-D02 §9.3; E16-D06 SR-01, SR-05, SR-06, BG-01, BG-06):
 * changes of state only, at most one polite utterance per 10 s window, the changes of a window
 * spoken as one batch so none is lost. The assertive set (the level-3 and incident banners and a
 * failed purge, BG-05) is said once per key while its condition holds; coalescing never swallows
 * one, and one that arrives while a batch is waiting is spoken right after that batch (BG-06), those
 * waiting together as one write, and not at all once its condition has ended. Those that arrive in
 * one turn with no batch waiting are one write too, at the turn's end (the page's region commits a
 * tick's last write only), said ahead of a batch that turn brings. Ticking numbers never come here
 * (BG-04). The page owns the regions and passes `say`.
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
  /** The condition ended: `key` may be said again when it next holds; a row still waiting is dropped. */
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
  /** The assertive rows waiting behind the batch, by key, in the order they came. */
  const held = new Map<string, string>();
  const said = new Set<string>();
  let lastBatchAt = Number.NEGATIVE_INFINITY;
  let timer: Timer | null = null;
  /** The assertive rows of this turn (no batch was waiting), said together once the turn ends. */
  const turn = new Map<string, string>();
  let turnTimer: Timer | null = null;

  const sayTurn = (): void => {
    if (turnTimer !== null) clock.clearTimer(turnTimer);
    turnTimer = null;
    if (turn.size > 0) say("assertive", [...turn.values()].join(" "));
    turn.clear();
  };

  const flush = (): void => {
    timer = null;
    sayTurn(); // the turn's alerts came before this batch was due: they are said ahead of it
    if (pending.length > 0) {
      say("polite", pending.join("; "));
      lastBatchAt = clock.now();
      pending = [];
    }
    // One write for all of them: two in one tick would commit only the last, and that swallows the first.
    if (held.size > 0) say("assertive", [...held.values()].join(" "));
    held.clear();
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
      if (timer !== null) {
        held.set(key, text);
        return;
      }
      // Two alerts in one turn are one write (#5309's re-check (b)): two `say`s in a tick commit only the last.
      turn.set(key, text);
      turnTimer ??= clock.setTimer(sayTurn, 0);
    },
    release(key) {
      said.delete(key);
      held.delete(key); // its condition ended while it waited: nothing is left to say
      turn.delete(key);
    },
    dispose() {
      if (timer !== null) clock.clearTimer(timer);
      if (turnTimer !== null) clock.clearTimer(turnTimer);
      timer = null;
      turnTimer = null;
      pending = [];
      held.clear();
      turn.clear();
    },
  };
}
