import { useEffect, useRef, useState, type KeyboardEvent, type PointerEvent } from "react";

/** The gate a hold confirm passed (E05-S03 plan §3 item 4). */
export type HoldGate = "pointer-hold" | "key-hold" | "double-press";

/** H2: the hold's default, and the user setting's range (US-SET-003), ms. */
export const HOLD_DEFAULT_MS = 800;
export const HOLD_MIN_MS = 300;
export const HOLD_MAX_MS = 2000;
/** H25: a second press counts only at least this long after the first, and within the window. */
export const PRESS_GAP_MS = 250;
export const PRESS_WINDOW_MS = 5000;
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
 * `Enter` or `Space` at least 250 ms apart within 5 s; the first press arms. `Space` counts on its keyup and
 * never holds. Key repeats never count; clicks are never read, so a synthetic `click()` confirms nothing and
 * a pointer press never arms. `Esc` or blur disarms. Completion is read from the clock, never a timer alone.
 */
export function useHoldGate({
  durationMs,
  enabled,
  clock,
  canStart,
  onFire,
  onArm,
}: HoldGateOptions): HoldGateState {
  const [progress, setProgress] = useState(0);
  const [percent, setPercent] = useState(0);
  const [holding, setHolding] = useState(false);
  const [armedAt, setArmedAt] = useState<number | null>(null);
  const hold = useRef<Hold | null>(null);
  const armed = useRef<number | null>(null);
  const spaceDown = useRef(false);
  const tickTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const windowTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const ticks = useRef(0);
  // The latest options, read by the timers without restarting them.
  const latest = useRef({ durationMs, enabled, clock, canStart, onFire, onArm });
  latest.current = { durationMs, enabled, clock, canStart, onFire, onArm };

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

  const startHold = (kind: Hold["kind"], at: number): void => {
    if (hold.current !== null) return;
    hold.current = { kind, start: at };
    ticks.current = 0;
    setHolding(true);
    tickTimer.current = setTimeout(tick, Math.min(TICK_MS, latest.current.durationMs));
  };

  /** One discrete press (Enter keydown or Space keyup): arms, or confirms a valid second press. */
  const press = (at: number, kind: "enter" | "space"): void => {
    const first = armed.current;
    if (first !== null && at - first <= PRESS_WINDOW_MS) {
      if (at - first >= PRESS_GAP_MS) fire("double-press");
      // Too soon after the first: a bounce, ignored; the window keeps its start.
      return;
    }
    armed.current = at;
    setArmedAt(at);
    clearTimeout(windowTimer.current);
    windowTimer.current = setTimeout(disarm, PRESS_WINDOW_MS);
    latest.current.onArm();
    if (kind === "enter") startHold("key", at);
  };

  // Confirm going unavailable (busy, gated, closed, a mismatch) drops any hold and the armed press.
  useEffect(() => {
    if (enabled) return;
    clearTimeout(tickTimer.current);
    clearTimeout(windowTimer.current);
    hold.current = null;
    armed.current = null;
    spaceDown.current = false;
    setHolding(false);
    setProgress(0);
    setPercent(0);
    setArmedAt(null);
  }, [enabled]);

  useEffect(
    () => () => {
      clearTimeout(tickTimer.current);
      clearTimeout(windowTimer.current);
    },
    [],
  );

  const release = (kind: Hold["kind"]): void => {
    if (hold.current?.kind === kind) stopHold();
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
        startHold("pointer", at);
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
        if (event.key === " ") spaceDown.current = true;
        else press(at, "enter");
      },
      onKeyUp: (event) => {
        if (event.key === "Enter") {
          release("key");
          return;
        }
        if (event.key !== " ") return;
        const began = spaceDown.current;
        spaceDown.current = false;
        if (!latest.current.enabled) return;
        event.preventDefault();
        if (began) press(latest.current.clock(), "space");
      },
      onBlur: () => {
        stopHold();
        disarm();
      },
    },
  };
}
