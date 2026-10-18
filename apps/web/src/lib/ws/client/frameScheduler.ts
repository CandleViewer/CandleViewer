// E17-T04 S3 (23 8.5, C9): rendering follows the display, never the feed. An arrival only drops the
// latest value into a keyed slot and makes sure one frame is requested; the frame callback hands
// everything that arrived since the last frame to `render` in a single call. So 500 frames inside one
// animation frame cost one render, and nothing is ever applied synchronously from the socket.

/** One 60 Hz frame of work (06 4.3, AGENTS.md 5.1: "never render more than ~16 ms of work per frame"). */
export const FRAME_BUDGET_MS = 16;

export type FrameMark = "state.apply" | "paint";

export interface FrameSchedulerOptions<T> {
  /** Called once per frame that saw an arrival, with the latest value of every slot that changed. */
  readonly render: (batch: ReadonlyMap<string, T>) => void;
  readonly raf?: ((callback: (frameTimeMs: number) => void) => number) | undefined;
  readonly caf?: ((handle: number) => void) | undefined;
  /** Monotonic milliseconds. Defaults to `performance.now`. */
  readonly now?: (() => number) | undefined;
  /** Budget #3 stage marks: `state.apply` when a batch starts being applied, `paint` when the frame's work ends. */
  readonly mark?: ((name: FrameMark, atMs: number) => void) | undefined;
  readonly budgetMs?: number | undefined;
}

export interface FrameScheduler<T> {
  /** The arrival path: O(1), never renders. The latest value per key wins. */
  post(key: string, value: T): void;
  /** Cancels the pending frame and drops the slots; later posts are ignored. */
  stop(): void;
  readonly renders: number;
  /** Frames whose `render` ran longer than the budget. */
  readonly overruns: number;
}

export function createFrameScheduler<T>(options: FrameSchedulerOptions<T>): FrameScheduler<T> {
  const raf = options.raf ?? ((callback) => requestAnimationFrame(callback));
  const caf = options.caf ?? ((handle) => cancelAnimationFrame(handle));
  const now = options.now ?? (() => performance.now());
  const budgetMs = options.budgetMs ?? FRAME_BUDGET_MS;
  let slots = new Map<string, T>();
  let frame: number | undefined;
  let stopped = false;
  let renders = 0;
  let overruns = 0;

  const onFrame = (): void => {
    frame = undefined;
    const batch = slots;
    slots = new Map(); // a post made while rendering lands in the next frame
    const start = now();
    options.mark?.("state.apply", start);
    try {
      options.render(batch);
    } finally {
      const end = now();
      options.mark?.("paint", end);
      renders += 1;
      if (end - start > budgetMs) overruns += 1;
    }
  };

  return {
    post: (key, value) => {
      if (stopped) return;
      slots.set(key, value);
      frame ??= raf(onFrame);
    },
    stop: () => {
      stopped = true;
      if (frame !== undefined) caf(frame);
      frame = undefined;
      slots = new Map();
    },
    get renders() {
      return renders;
    },
    get overruns() {
      return overruns;
    },
  };
}
