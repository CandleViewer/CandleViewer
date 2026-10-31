import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type KeyboardEvent,
  type PointerEvent,
} from "react";

/** The gate a hold confirm passed (E05-S03 plan §3 item 4). */
export type HoldGate = "pointer-hold" | "key-hold" | "double-press";

/** H2: the hold's default, and the user setting's range (US-SET-003), ms. */
export const HOLD_DEFAULT_MS = 800;
export const HOLD_MIN_MS = 300;
export const HOLD_MAX_MS = 2000;
/** H25: a second press counts only at least this long after the first, and within the window. */
export const PRESS_GAP_MS = 250;
export const PRESS_WINDOW_MS = 5000;
/**
 * A second press counts only when a `keyup` came between it and the first, at least this long before its
 * `keydown`: an input stack that sends auto-repeat as keyup/keydown pairs never makes two presses of one.
 */
export const KEYUP_FLOOR_MS = 50;
/** The ring redraws at up to 10 updates a second; its text twin at up to 2 (every fifth tick). */
const TICK_MS = 100;
const TEXT_EVERY = 5;

/** `holdDurationMs` clamped to H2's range; a missing or non-finite value is the 800 ms default. */
export const clampHold = (ms: number | undefined): number =>
  ms === undefined || !Number.isFinite(ms)
    ? HOLD_DEFAULT_MS
    : Math.min(HOLD_MAX_MS, Math.max(HOLD_MIN_MS, ms));

export interface HoldGateOptions {
  readonly durationMs: number;
  /** A press may start: the dialog is open, Confirm is available, not busy and not yet fired. */
  readonly enabled: boolean;
  /** The monotonic clock, ms. */
  readonly clock: () => number;
  /** False inside the activation guard: a press that begins then is ignored whatever its length. */
  readonly canStart: (at: number) => boolean;
  readonly onFire: (gate: HoldGate) => void;
  /** The first discrete press armed the button (the host renames it and speaks once). */
  readonly onArm: () => void;
  /** The armed press's window ran out unanswered (the host speaks once); not called on Esc, blur or a fire. */
  readonly onLapse: () => void;
  /** A pointer hold began (a key hold is announced by `onArm`). */
  readonly onHoldStart?: () => void;
  /** A pointer hold was released before completing; fired once per early release. */
  readonly onHoldCancel?: () => void;
  /** A new value drops any hold and the armed press: the intent changed under them (the guard's rearm). */
  readonly resetKey: string;
}

export interface HoldGateState {
  /** The ring's fill, 0–1, at up to 10 updates a second. */
  readonly progress: number;
  /** The text twin and `aria-valuenow`, a whole percentage, at up to 2 updates a second. */
  readonly percent: number;
  readonly holding: boolean;
  /** The armed press's clock time, or null. */
  readonly armedAt: number | null;
  readonly handlers: {
    onPointerDown: (event: PointerEvent<HTMLButtonElement>) => void;
    onPointerUp: () => void;
    onPointerCancel: () => void;
    onPointerLeave: () => void;
    onLostPointerCapture: () => void;
    onContextMenu: (event: { preventDefault: () => void }) => void;
    onKeyDown: (event: KeyboardEvent<HTMLButtonElement>) => void;
    onKeyUp: (event: KeyboardEvent<HTMLButtonElement>) => void;
    onBlur: () => void;
  };
}

interface Hold {
  readonly kind: "pointer" | "key";
  readonly start: number;
}

/**
 * CMP-044's hold gate (H25, E39-D03 §5). Pointer: press and hold for `durationMs`; an early release resets
 * the progress and fires nothing. Keyboard: hold `Enter` for the same time, or two non-repeat presses of
 * `Enter` or `Space` at least 250 ms apart within 5 s, a keyup between them (E39-D03 §5); the first press
 * arms. `Space` counts on its keyup and never holds. Key repeats never count; clicks are never read, so a
 * synthetic `click()` confirms nothing and a pointer press never arms. `Esc` or blur disarms silently; a
 * window that runs out calls `onLapse`. Completion is read from the clock, never a timer alone.
 */
export function useHoldGate({
  durationMs,
  enabled,
  clock,
  canStart,
  onFire,
  onArm,
  onLapse,
  onHoldStart,
  onHoldCancel,
  resetKey,
}: HoldGateOptions): HoldGateState {
  const [progress, setProgress] = useState(0);
  const [percent, setPercent] = useState(0);
  const [holding, setHolding] = useState(false);
  const [armedAt, setArmedAt] = useState<number | null>(null);
  const hold = useRef<Hold | null>(null);
  const armed = useRef<number | null>(null);
  const spaceDown = useRef(false);
  /** The last `Enter` / `Space` keyup on Confirm, by the clock. */
  const lastUp = useRef<number | null>(null);
  /** The pending `Space` press was separated from the armed one by a keyup (read on its own keyup). */
  const spaceSeparated = useRef(false);
  const tickTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const windowTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const ticks = useRef(0);
  // The latest options, read by the timers without restarting them.
  const latest = useRef({
    durationMs,
    enabled,
    clock,
    canStart,
    onFire,
    onArm,
    onLapse,
    onHoldStart,
    onHoldCancel,
  });
  latest.current = {
    durationMs,
    enabled,
    clock,
    canStart,
    onFire,
    onArm,
    onLapse,
    onHoldStart,
    onHoldCancel,
  };

  const stopHold = (): void => {
    clearTimeout(tickTimer.current);
    tickTimer.current = undefined;
    if (hold.current === null) return;
    hold.current = null;
    setHolding(false);
    setProgress(0);
    setPercent(0);
  };

  const disarm = (): void => {
    clearTimeout(windowTimer.current);
    windowTimer.current = undefined;
    spaceDown.current = false;
    if (armed.current === null) return;
    armed.current = null;
    setArmedAt(null);
  };

  const fire = (gate: HoldGate): void => {
    stopHold();
    disarm();
    latest.current.onFire(gate);
  };

  const tick = (): void => {
    const current = hold.current;
    if (current === null) return;
    const { clock: read, durationMs: total } = latest.current;
    const elapsed = read() - current.start;
    if (elapsed >= total) {
      fire(current.kind === "pointer" ? "pointer-hold" : "key-hold");
      return;
    }
    const share = Math.max(0, elapsed / total);
    setProgress(share);
    ticks.current += 1;
    if (ticks.current % TEXT_EVERY === 0) setPercent(Math.floor(share * 100));
    tickTimer.current = setTimeout(tick, Math.max(1, Math.min(TICK_MS, total - elapsed)));
  };

  /** True when a hold really began (none was running). */
  const startHold = (kind: Hold["kind"], at: number): boolean => {
    if (hold.current !== null) return false;
    hold.current = { kind, start: at };
    ticks.current = 0;
    setHolding(true);
    tickTimer.current = setTimeout(tick, Math.min(TICK_MS, latest.current.durationMs));
    return true;
  };

  const lapse = (): void => {
    if (armed.current === null) return;
    disarm();
    latest.current.onLapse();
  };

  /** A key going down at `at` is a new press: a keyup of an earlier one came at least the floor before it. */
  const separatedAt = (at: number): boolean => {
    const first = armed.current;
    const up = lastUp.current;
    return first !== null && up !== null && up >= first && at - up >= KEYUP_FLOOR_MS;
  };

  /**
   * One discrete press (Enter keydown or Space keyup): arms, or confirms a valid second press. `separated`:
   * its key went down after a keyup of the armed press, past the floor.
   */
  const press = (at: number, kind: "enter" | "space", separated: boolean): void => {
    const first = armed.current;
    if (first !== null && at - first <= PRESS_WINDOW_MS) {
      if (separated && at - first >= PRESS_GAP_MS) fire("double-press");
      // Too soon after the first, or no keyup between: a bounce or a repeat, ignored; the window keeps its start.
      return;
    }
    armed.current = at;
    setArmedAt(at);
    clearTimeout(windowTimer.current);
    windowTimer.current = setTimeout(lapse, PRESS_WINDOW_MS);
    latest.current.onArm();
    if (kind === "enter") startHold("key", at);
  };

  // Deliberately silent: Esc, blur and these resets drop a hold without a message (Esc cancels the dialog,
  // which is its own event; a reset is a new intent, spoken by its own title).
  // Confirm going unavailable (busy, gated, closed, a mismatch) or a new intent (`resetKey`) drops any hold
  // and the armed press, before a pending tick can complete the hold.
  const seenKey = useRef(resetKey);
  useLayoutEffect(() => {
    const changed = seenKey.current !== resetKey;
    seenKey.current = resetKey;
    if (enabled && !changed) return;
    clearTimeout(tickTimer.current);
    clearTimeout(windowTimer.current);
    hold.current = null;
    armed.current = null;
    spaceDown.current = false;
    setHolding(false);
    setProgress(0);
    setPercent(0);
    setArmedAt(null);
  }, [enabled, resetKey]);

  useEffect(
    () => () => {
      clearTimeout(tickTimer.current);
      clearTimeout(windowTimer.current);
    },
    [],
  );

  const release = (kind: Hold["kind"]): void => {
    if (hold.current?.kind !== kind) return;
    stopHold();
    // A key release is a discrete press (it armed; `onArm` spoke): only a pointer release is an early cancel.
    if (kind === "pointer") latest.current.onHoldCancel?.();
  };

  return {
    progress,
    percent,
    holding,
    armedAt,
    handlers: {
      onPointerDown: (event) => {
        if (event.button !== 0 || !latest.current.enabled) return;
        const at = latest.current.clock();
        if (!latest.current.canStart(at)) return;
        // Keep the press on Confirm while the pointer is down; jsdom has no capture.
        if (typeof event.currentTarget.setPointerCapture === "function") {
          try {
            event.currentTarget.setPointerCapture(event.pointerId);
          } catch {
            // An inactive pointer id (a synthetic event): the leave and up handlers still release.
          }
        }
        if (startHold("pointer", at)) latest.current.onHoldStart?.();
      },
      onPointerUp: () => release("pointer"),
      onPointerCancel: () => release("pointer"),
      onPointerLeave: () => release("pointer"),
      onLostPointerCapture: () => release("pointer"),
      // A long touch press opens no context menu over Confirm.
      onContextMenu: (event) => event.preventDefault(),
      onKeyDown: (event) => {
        if (event.key === "Escape") {
          // Disarms; the dialog's own Esc then cancels.
          stopHold();
          disarm();
          return;
        }
        if (event.key !== "Enter" && event.key !== " ") return;
        if (event.repeat) {
          event.preventDefault();
          return;
        }
        // Unavailable: the native click stays, so a T2 Confirm can re-show its reason.
        if (!latest.current.enabled) return;
        event.preventDefault();
        const at = latest.current.clock();
        if (!latest.current.canStart(at)) {
          if (event.key === " ") spaceDown.current = false;
          return;
        }
        if (event.key === " ") {
          spaceDown.current = true;
          spaceSeparated.current = separatedAt(at);
        } else press(at, "enter", separatedAt(at));
      },
      onKeyUp: (event) => {
        if (event.key !== "Enter" && event.key !== " ") return;
        const at = latest.current.clock();
        if (event.key === "Enter") {
          lastUp.current = at;
          release("key");
          return;
        }
        const began = spaceDown.current;
        spaceDown.current = false;
        if (latest.current.enabled) {
          event.preventDefault();
          if (began) press(at, "space", spaceSeparated.current);
        }
        // After the press: a Space that arms is its own keyup, so the next press is measured from it.
        lastUp.current = at;
      },
      onBlur: () => {
        stopHold();
        disarm();
      },
    },
  };
}
