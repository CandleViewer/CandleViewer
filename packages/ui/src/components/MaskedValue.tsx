import { useCallback, useEffect, useId, useRef, useState, type JSX } from "react";
import { flushSync } from "react-dom";
import { CopyButton } from "./CopyButton.js";
import { Countdown } from "./Countdown.js";
import { IconButton } from "./IconButton.js";
import { MonoText } from "./Typography.js";

/** S4: eight mask characters whatever the value's length, so the mask never tells the length. */
const MASK = "•".repeat(8);

/** The default auto-hide (S3, catalogue `autoHideMs` default). */
export const MASKED_VALUE_AUTO_HIDE_MS = 10_000;
/** G19's proposed cap: a longer `autoHideMs` is clamped to it. */
export const MASKED_VALUE_AUTO_HIDE_MAX_MS = 30_000;
/** The floor: the 2 s warning needs at least one whole second of reveal before it to be spoken. */
export const MASKED_VALUE_AUTO_HIDE_MIN_MS = 3_000;
/** The warning lead: the re-mask is announced once, this long before it happens. */
const WARN_MS = 2_000;
const WARN_S = WARN_MS / 1000;

export type MaskedValueState = "masked" | "revealed" | "expiring";

/** `autoHideMs` within [3 s, 30 s]; anything not a finite number takes the 10 s default. */
export function clampAutoHide(ms: number | undefined): number {
  if (ms === undefined || !Number.isFinite(ms)) return MASKED_VALUE_AUTO_HIDE_MS;
  return Math.min(MASKED_VALUE_AUTO_HIDE_MAX_MS, Math.max(MASKED_VALUE_AUTO_HIDE_MIN_MS, ms));
}

interface Entry {
  mask: () => void;
}

/** S1's page registry: at most one value is revealed at a time; revealing another masks it. */
let active: Entry | null = null;

/**
 * Masks the revealed value on the page, if any. The app calls it on a route change, the idle lock and
 * sign-out (S1): `packages/ui` imports no router. Unmounting masks too, by dropping the state.
 *
 * The mask lands after the caller returns, in a microtask, committed synchronously there: the timing is
 * the same from an event handler, an effect or plain code, and no in-effect `flushSync` warning appears.
 */
export function maskAllValues(): void {
  queueMicrotask(() => {
    const current = active;
    if (current !== null) flushSync(() => current.mask());
  });
}

export interface MaskedValueProps {
  /**
   * A key or secret the user has just entered in this flow, held in memory only (S6, C-2.7). Never in the
   * DOM, an attribute, a name, the status or a log while masked; never passed to any callback.
   */
  value: string;
  /** What it is, e.g. "API secret": names the group and the buttons ("Show API secret"). */
  label: string;
  /**
   * The host's veto. `false` masks at once (after a submit, on sign-out) and, while it stands, a press of
   * the toggle does nothing and emits nothing. `true` (or absent) never reveals by itself: only a press of
   * the toggle does (S1, S2), so a value is never revealed at mount.
   */
  revealed?: boolean;
  /**
   * Called with the new state on every change: a press, the auto-hide and every re-mask; never for a press
   * under `revealed={false}` and never for the host's own veto. It never receives the value.
   */
  onToggleReveal?: (revealed: boolean) => void;
  /** Re-masks this long after the press: 10 s by default, clamped to [3 s, 30 s] (S3, G19). */
  autoHideMs?: number;
  /** Adds CMP-033 "Copy {label}", enabled only while revealed (G19's default). */
  copyable?: boolean;
  /** Emits `data-density` on the nested buttons; absent = inherit. */
  density?: "comfortable" | "compact";
}

/** "API secret" -> "API secret will hide in 2 seconds"; "secret" -> "Secret will hide in 2 seconds". */
const warning = (label: string): string =>
  `${label.charAt(0).toUpperCase()}${label.slice(1)} will hide in ${WARN_S} seconds`;

/**
 * CMP-034 MaskedValue: a box holding an 8-dot mask and, only after an explicit press of the toggle, the
 * value. The toggle is a ghost CMP-002 whose name ("Show/Hide {label}") carries the state, so no
 * `aria-pressed`. While revealed a CMP-035 count reads "Hides in 10 s" and speaks one warning 2 s before
 * the re-mask; the re-mask itself is silent and keeps focus. The window losing focus, a hidden tab, print,
 * history navigation, another value's reveal and `maskAllValues()` re-mask at once (S1-S7).
 */
export function MaskedValue({
  value,
  label,
  revealed,
  onToggleReveal,
  autoHideMs,
  copyable = false,
  density,
}: MaskedValueProps): JSX.Element {
  const boxId = useId();
  // The press time while revealed; null while masked. The value itself is never copied into state.
  const [revealedAt, setRevealedAt] = useState<number | null>(null);
  const [expiring, setExpiring] = useState(false);
  const hideMs = clampAutoHide(autoHideMs);
  const shown = revealedAt !== null && revealed !== false;
  const shownAt = shown ? revealedAt : null;

  const latest = useRef(onToggleReveal);
  useEffect(() => {
    latest.current = onToggleReveal;
  });
  // Set synchronously, so two re-mask events in one tick notify the host once.
  const live = useRef(false);
  const actions = useRef<HTMLSpanElement>(null);

  const mask = useCallback((notify: boolean): void => {
    if (!live.current) return;
    live.current = false;
    // Copy is disabled by the mask: focus inside the actions moves to the toggle, never to <body>.
    const area = actions.current;
    const toggleEl = area?.querySelector<HTMLButtonElement>(":scope > button");
    const focused = document.activeElement;
    if (area && toggleEl && focused !== toggleEl && focused !== null && area.contains(focused))
      toggleEl.focus();
    setRevealedAt(null);
    setExpiring(false);
    if (notify) latest.current?.(false);
  }, []);
  const entry = useRef<Entry>({ mask: () => mask(true) });

  // The host's veto: `revealed={false}` drops a reveal, so a later `true` cannot bring it back unpressed.
  useEffect(() => {
    if (revealed === false && revealedAt !== null) mask(false);
  }, [revealed, revealedAt, mask]);

  useEffect(() => {
    if (shownAt === null) return undefined;
    const self = entry.current;
    if (active !== null && active !== self) active.mask();
    active = self;
    // The browser and timer triggers commit the mask synchronously, before the event returns: a page
    // snapshot (pagehide), a print (beforeprint) or a screen grab after blur never sees a pending reveal.
    const hideNow = (): void => {
      if (!live.current) return;
      flushSync(() => self.mask());
    };
    const onVisibility = (): void => {
      if (document.visibilityState === "hidden") hideNow();
    };
    const deadline = shownAt + hideMs;
    const left = (): number => Math.max(0, deadline - Date.now());
    const warn = setTimeout(() => setExpiring(true), Math.max(0, left() - WARN_MS));
    const hide = setTimeout(hideNow, left());
    const events = ["blur", "pagehide", "beforeprint", "popstate", "hashchange"] as const;
    events.forEach((type) => window.addEventListener(type, hideNow));
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      clearTimeout(warn);
      clearTimeout(hide);
      events.forEach((type) => window.removeEventListener(type, hideNow));
      document.removeEventListener("visibilitychange", onVisibility);
      if (active === self) active = null;
    };
  }, [shownAt, hideMs]);

  const onPress = (): void => {
    // Under a standing veto a press does nothing and tells the host nothing (S2).
    if (revealed === false) return;
    if (shown) {
      mask(true);
      return;
    }
    // The handoff happens here, in this event's commit, so no frame paints two values (S1).
    if (active !== null && active !== entry.current) active.mask();
    live.current = true;
    setExpiring(false);
    setRevealedAt(Date.now());
    latest.current?.(true);
  };

  const state: MaskedValueState = !shown ? "masked" : expiring ? "expiring" : "revealed";
  const densityProp = density === undefined ? {} : { density };
  return (
    <div
      className="cv-masked-value"
      role="group"
      aria-label={label}
      data-cmp="CMP-034"
      data-state={state}
    >
      <div className="cv-masked-value__row">
        <div className="cv-masked-value__box" id={boxId} translate="no">
          {shown ? (
            <MonoText size="base" className="cv-masked-value__value">
              {value}
            </MonoText>
          ) : (
            <>
              <MonoText size="base" className="cv-masked-value__mask" aria-hidden="true">
                {MASK}
              </MonoText>
              <span className="cv-visually-hidden">{`${label}, hidden`}</span>
            </>
          )}
        </div>
        <span className="cv-masked-value__actions" ref={actions}>
          <IconButton
            icon={shown ? "hide" : "show"}
            label={`${shown ? "Hide" : "Show"} ${label}`}
            variant="ghost"
            size="md"
            aria-controls={boxId}
            {...densityProp}
            onClick={onPress}
          />
          {copyable ? (
            <CopyButton
              // A new copy control per mask state: its status resets with the mask.
              key={shown ? "revealed" : "masked"}
              value={shown ? value : ""}
              label={`Copy ${label}`}
              disabled={!shown}
              {...densityProp}
            />
          ) : null}
        </span>
      </div>
      {shownAt === null ? null : (
        <span className="cv-masked-value__countdown">
          Hides in{" "}
          <Countdown
            expiresAt={shownAt + hideMs}
            format="words"
            thresholds={[WARN_S]}
            announce={() => warning(label)}
          />
        </span>
      )}
    </div>
  );
}
