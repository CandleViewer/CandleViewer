/**
 * One shared 1 Hz tick for every countdown (E24-S03 #778, BQ 2; D02 §14 "one shared 1 s timer"). A tick
 * source holds at most one timer, armed while it has a subscriber and cleared with the last one, and fires
 * just past each whole second of its own clock, so a whole-second deadline changes its floor in the tick
 * that reads it. Its clock is the host's: an app passes the exchange-synced one (`Date.now` plus the measured
 * offset), so every countdown on it reads one time and none can drift from another.
 */
export interface SecondTick {
  /** The tick's clock, epoch ms. */
  now(): number;
  /** Calls `listener` once per whole second of `now()`; the returned function unsubscribes. */
  subscribe(listener: () => void): () => void;
}

export interface SecondTickClock {
  readonly now?: (() => number) | undefined;
  readonly setTimeout?: ((run: () => void, ms: number) => unknown) | undefined;
  readonly clearTimeout?: ((id: unknown) => void) | undefined;
}

/** Past the whole second, so the floor of a whole-second deadline has already moved when the tick reads. */
const LATE_MS = 1;

export function createSecondTick(clock: SecondTickClock = {}): SecondTick {
  // read lazily, so a test's fake timers and clock are the ones in force at each call
  const now = clock.now ?? ((): number => Date.now());
  const set = clock.setTimeout ?? ((run: () => void, ms: number): unknown => setTimeout(run, ms));
  const clear =
    clock.clearTimeout ??
    ((id: unknown): void => clearTimeout(id as ReturnType<typeof setTimeout>));
  const listeners = new Set<() => void>();
  let timer: unknown;
  let armed = false;

  const arm = (): void => {
    const into = ((now() % 1000) + 1000) % 1000;
    timer = set(fire, 1000 - into + LATE_MS);
    armed = true;
  };
  function fire(): void {
    armed = false;
    try {
      for (const listener of [...listeners]) {
        try {
          listener();
        } catch (error) {
          // one listener's fault must not stop the others of this tick; surface it outside the tick
          queueMicrotask(() => {
            throw error;
          });
        }
      }
    } finally {
      // the single timer chain must survive whatever a listener did
      if (listeners.size > 0 && !armed) arm();
    }
  }

  return {
    now,
    subscribe: (listener) => {
      listeners.add(listener);
      if (!armed) arm();
      return () => {
        listeners.delete(listener);
        if (listeners.size === 0 && armed) {
          clear(timer);
          armed = false;
        }
      };
    },
  };
}

/** The default tick on the local clock, shared by every countdown that is given none. */
export const systemSecondTick: SecondTick = createSecondTick();
