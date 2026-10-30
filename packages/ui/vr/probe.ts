/**
 * The capture's page probe (E05-T04). `installProbe` is an init script: it runs in every document before
 * Storybook or a story does. It holds `Date` at the capture's instant except while a play function runs
 * (timers, frames and `performance.now()` stay the browser's, as in the storybook job where the play
 * functions are proven), starts the document with empty storage, counts DOM mutations and tracks the
 * page's timers, so that once Storybook finished a story the capture can wait for it to hold still
 * (`settleCell`) and then stop it (`freezeCell`) before measuring the clip.
 * Playwright serialises `installProbe` and the in-page steps below, so none of them closes over anything;
 * the steps reach the probe through the handle it leaves on `window`.
 */

export interface ProbeOptions {
  /** The instant `Date` holds, in epoch ms; it moves on from there only while a play function runs. */
  readonly now: number;
}

/** The settle rule (settings.ts's `SETTLE`). */
export interface SettleOptions {
  /** A timer due within this many ms of the start is let fire first; a later one is frozen, never awaited. */
  readonly horizonMs: number;
  /** Consecutive animation frames with no DOM mutation and no such timer pending. */
  readonly quietFrames: number;
  /** The longest a cell waits; a page still changing then fails the cell, naming what moved. */
  readonly capMs: number;
}

export interface Settled {
  readonly ok: boolean;
  /** How long the page took, in whole ms. */
  readonly ms: number;
  /** Why it did not settle; empty when it did. */
  readonly reason: string;
}

/** What the probe leaves on `window.__cvVr`. */
export interface VrProbe {
  settle(options: SettleOptions): Promise<Settled>;
  freeze(): void;
  /** Resolves after `count` animation frames, frozen or not (the capture's own waits). */
  frames(count: number): Promise<void>;
}

export function installProbe({ now }: ProbeOptions): void {
  const scope = window;
  try {
    scope.localStorage.clear();
    scope.sessionStorage.clear();
  } catch {
    // about:blank has no storage
  }

  const clock = scope.performance.now.bind(scope.performance);

  // `new Date()`, `Date.now()` and `Date()` read the capture's instant, held still while the story renders
  // and while it is captured, so "now" shows the same digits each run. While a play function runs it moves
  // with real time, as in the storybook job, so a countdown the play waits on can count. Explicit dates are
  // untouched.
  let held = now;
  let playing: number | null = null;
  const instant = (): number => (playing === null ? held : held + (clock() - playing));
  const play = (running: boolean): void => {
    if (running && playing === null) playing = clock();
    if (!running && playing !== null) {
      held = instant();
      playing = null;
    }
  };
  const Real = scope.Date;
  const Frozen = function (this: unknown, ...args: unknown[]): Date | string {
    if (new.target === undefined) return new Real(instant()).toString();
    return Reflect.construct(Real, args.length === 0 ? [instant()] : args, new.target) as Date;
  };
  const own = { writable: true, configurable: true };
  Object.defineProperties(Frozen, {
    prototype: { value: Real.prototype },
    now: { value: instant, ...own },
    parse: { value: Real.parse, ...own },
    UTC: { value: Real.UTC, ...own },
  });
  scope.Date = Frozen as unknown as DateConstructor;

  // Storybook's preview channel, through the global it is published on: its `storyRenderPhaseChanged`
  // events say when a play function starts ("playing") and when it is over (any later phase).
  let channel: unknown;
  Object.defineProperty(scope, "__STORYBOOK_ADDONS_CHANNEL__", {
    configurable: true,
    enumerable: true,
    get: () => channel,
    set: (next: unknown) => {
      channel = next;
      const on: unknown = (next as { on?: unknown } | null | undefined)?.on;
      if (typeof on !== "function") return;
      const listener = (event: { newPhase?: unknown } | undefined): void =>
        play(event?.newPhase === "playing");
      Reflect.apply(on, next, ["storyRenderPhaseChanged", listener]);
    },
  });

  // The browser's own timers and frames, kept for the probe; the page gets tracked ones.
  const setTimer = scope.setTimeout.bind(scope);
  const clearTimer = scope.clearTimeout.bind(scope);
  const setRepeat = scope.setInterval.bind(scope);
  const clearRepeat = scope.clearInterval.bind(scope);
  const frame = scope.requestAnimationFrame.bind(scope);
  const cancelFrame = scope.cancelAnimationFrame.bind(scope);
  // Optional: a document without idle callbacks (jsdom) keeps its own.
  const idle = typeof scope.requestIdleCallback === "function" ? scope.requestIdleCallback : null;
  const cancelIdle = scope.cancelIdleCallback;
  /** One-shot timers still pending, by id, with the time each is due. */
  const timeouts = new Map<number, number>();
  const repeats = new Set<number>();
  const frames = new Set<number>();
  const idles = new Set<number>();
  let frozen = false;
  let mutations = 0;

  scope.setTimeout = ((handler: TimerHandler, timeout?: number, ...args: unknown[]): number => {
    if (frozen) return 0;
    if (typeof handler !== "function") return setTimer(handler, timeout, ...args);
    const id = setTimer(
      (...given: unknown[]) => {
        timeouts.delete(id);
        Reflect.apply(handler, undefined, given);
      },
      timeout,
      ...args,
    );
    timeouts.set(id, clock() + Math.max(0, Number(timeout) || 0));
    return id;
  }) as typeof scope.setTimeout;
  scope.clearTimeout = ((id?: number): void => {
    if (id !== undefined) timeouts.delete(id);
    clearTimer(id);
  }) as typeof scope.clearTimeout;
  scope.setInterval = ((handler: TimerHandler, timeout?: number, ...args: unknown[]): number => {
    if (frozen) return 0;
    const id = setRepeat(handler, timeout, ...args);
    repeats.add(id);
    return id;
  }) as typeof scope.setInterval;
  scope.clearInterval = ((id?: number): void => {
    if (id !== undefined) repeats.delete(id);
    clearRepeat(id);
  }) as typeof scope.clearInterval;
  scope.requestAnimationFrame = (callback: FrameRequestCallback): number => {
    if (frozen) return 0;
    const id = frame((time) => {
      frames.delete(id);
      callback(time);
    });
    frames.add(id);
    return id;
  };
  scope.cancelAnimationFrame = (id: number): void => {
    frames.delete(id);
    cancelFrame(id);
  };
  if (idle !== null) {
    scope.requestIdleCallback = (callback, options): number => {
      if (frozen) return 0;
      const id = idle.call(
        scope,
        (deadline) => {
          idles.delete(id);
          callback(deadline);
        },
        options,
      );
      idles.add(id);
      return id;
    };
    scope.cancelIdleCallback = (id: number): void => {
      idles.delete(id);
      cancelIdle.call(scope, id);
    };
  }

  new MutationObserver((records) => {
    mutations += records.length;
  }).observe(scope.document, {
    subtree: true,
    childList: true,
    attributes: true,
    characterData: true,
  });

  const settle = ({ horizonMs, quietFrames, capMs }: SettleOptions): Promise<Settled> =>
    new Promise((resolve) => {
      const start = clock();
      const deadline = start + horizonMs;
      let seen = mutations;
      let quiet = 0;
      const step = (): void => {
        const due = [...timeouts.values()].filter((at) => at <= deadline).length;
        quiet = mutations === seen && due === 0 ? quiet + 1 : 0;
        seen = mutations;
        const ms = Math.round(clock() - start);
        if (quiet >= quietFrames) {
          resolve({ ok: true, ms, reason: "" });
        } else if (ms < capMs) {
          frame(step);
        } else {
          const reason =
            due > 0
              ? `${due} timer(s) due within ${horizonMs} ms had not fired after ${capMs} ms`
              : `the DOM was still changing after ${capMs} ms`;
          resolve({ ok: false, ms, reason });
        }
      };
      frame(step);
    });

  const freeze = (): void => {
    frozen = true;
    for (const id of timeouts.keys()) clearTimer(id);
    for (const id of repeats) clearRepeat(id);
    for (const id of frames) cancelFrame(id);
    for (const id of idles) cancelIdle.call(scope, id);
    timeouts.clear();
    repeats.clear();
    frames.clear();
    idles.clear();
  };

  const wait = (count: number): Promise<void> =>
    new Promise((resolve) => {
      let left = count;
      const step = (): void => {
        left -= 1;
        if (left <= 0) resolve();
        else frame(step);
      };
      frame(step);
    });

  const probe: VrProbe = { settle, freeze, frames: wait };
  Object.defineProperty(scope, "__cvVr", { value: probe, configurable: true });
}

/** In the page, once Storybook finished the story: waits until it holds still (`SETTLE`). */
export function settleCell(options: SettleOptions): Promise<Settled> {
  const probe = (window as unknown as { __cvVr?: VrProbe }).__cvVr;
  if (probe === undefined) {
    return Promise.resolve({
      ok: false,
      ms: 0,
      reason: "the capture's page probe is not installed",
    });
  }
  return probe.settle(options);
}

/**
 * In the page: no timer, interval, frame or idle callback of the page runs again, so nothing moves under
 * the capture.
 */
export function freezeCell(): void {
  (window as unknown as { __cvVr?: VrProbe }).__cvVr?.freeze();
}

/** In the page: resolves after `count` animation frames (the probe's own, which the freeze leaves running). */
export function nextFrames(count: number): Promise<void> {
  const probe = (window as unknown as { __cvVr?: VrProbe }).__cvVr;
  return probe === undefined ? Promise.resolve() : probe.frames(count);
}
