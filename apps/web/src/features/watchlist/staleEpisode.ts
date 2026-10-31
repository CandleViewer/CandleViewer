/**
 * SCR-100's stale episode (E08-D07 D17, §4.5; `15` CMP-239): the panel owns no live region. An episode is a period with
 * at least one stale row; on entry it says one polite summary to the app's region, on exit one more, never per tick,
 * row or age change. Flapping within 5 s collapses: the exit is said once the stale set has stayed empty for 5 s, and a
 * row going stale again before then continues the episode in silence. While Disconnected (held) nothing is said: the
 * connection region says that, once. Plain code on injected timers, never a statechart.
 */
import { COPY } from "./copy";

export const EXIT_HOLD_MS = 5_000;
export const LIVE_AGAIN = COPY.liveAgain;

/** "3 watchlist symbols stale: SOLUSDT, DOGEUSDT, PEPEUSDT." — up to three names, then "and N more". */
export function staleSummary(symbols: readonly string[]): string {
  return COPY.staleSummary(symbols);
}

export interface EpisodeTimers {
  readonly setTimeout: (run: () => void, ms: number) => unknown;
  readonly clearTimeout: (id: unknown) => void;
}

/** Reads the globals on every call, so fake timers installed after import still apply. */
export const SYSTEM_EPISODE_TIMERS: EpisodeTimers = {
  setTimeout: (run, ms) => setTimeout(run, ms),
  // `id` is what this object's `setTimeout` returned; the cast only restores that type.
  clearTimeout: (id) => clearTimeout(id as ReturnType<typeof setTimeout>),
};

export interface EpisodeOutput {
  /** One polite message, to the app's region. */
  readonly say: (text: string) => void;
  /** An episode began (`data_confidence.state_entered`). */
  readonly entered: () => void;
}

export interface StaleEpisode {
  /** The stale symbols now, in list order. */
  update(stale: readonly string[]): void;
  /** Disconnected: says nothing and reads nothing until released. */
  hold(on: boolean): void;
  dispose(): void;
}

export function createStaleEpisode(
  out: EpisodeOutput,
  timers: EpisodeTimers = SYSTEM_EPISODE_TIMERS,
): StaleEpisode {
  let open = false;
  let held = false;
  let exit: unknown = null;
  const cancelExit = (): void => {
    if (exit !== null) timers.clearTimeout(exit);
    exit = null;
  };
  return {
    update(stale) {
      if (held) return;
      if (stale.length > 0) {
        cancelExit(); // a flap: the episode goes on
        if (open) return;
        open = true;
        out.say(staleSummary(stale));
        out.entered();
        return;
      }
      if (!open || exit !== null) return;
      exit = timers.setTimeout(() => {
        exit = null;
        open = false;
        out.say(LIVE_AGAIN);
      }, EXIT_HOLD_MS);
    },
    hold(on) {
      held = on;
      if (on) cancelExit();
    },
    dispose() {
      cancelExit();
      held = true;
    },
  };
}
