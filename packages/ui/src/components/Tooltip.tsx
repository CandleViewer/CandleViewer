import {
  cloneElement,
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
  type FocusEvent,
  type JSX,
  type PointerEvent,
  type ReactElement,
} from "react";
import { createPortal } from "react-dom";
import { cx } from "./internal/cx.js";
import { useExemptWithAnchor } from "./internal/inertOutside.js";
import { useLayerPortal } from "./internal/layers.js";
import { useAnchoredPosition, type AnchoredSide } from "./internal/useAnchoredPosition.js";

export type TooltipSide = AnchoredSide;
export type TooltipMode = "describes" | "echo";

/** The props Tooltip composes onto its trigger; the trigger's own handlers still run first. */
export interface TooltipTriggerProps {
  "aria-describedby"?: string | undefined;
  onPointerEnter?: (event: PointerEvent<HTMLElement>) => void;
  onPointerLeave?: (event: PointerEvent<HTMLElement>) => void;
  onPointerCancel?: (event: PointerEvent<HTMLElement>) => void;
  onPointerDown?: (event: PointerEvent<HTMLElement>) => void;
  onFocus?: (event: FocusEvent<HTMLElement>) => void;
  onBlur?: (event: FocusEvent<HTMLElement>) => void;
}

export interface TooltipProps {
  /**
   * Text only (H10): a link or a control belongs in CMP-017 Popover. Empty or whitespace-only renders no
   * node and never shows, so a host can keep one stable tree while its echo comes and goes.
   */
  content: string;
  /**
   * `describes` (default): the text is the trigger's description, linked by `aria-describedby`.
   * `echo`: a visual copy of a name or a reason that lives elsewhere (the trigger's `aria-label`, a
   * T2 reason node); the tooltip is `aria-hidden` so nothing is read twice.
   */
  mode?: TooltipMode;
  /** The preferred side; it flips when the viewport has no room. */
  side?: TooltipSide;
  /** Hover delay in ms (default 300). Keyboard focus shows it at once. */
  delay?: number;
  /** Always true (keyboard parity): the type admits no `false`. */
  triggerOnFocus?: true;
  className?: string;
  /**
   * One focusable element (a button, a link, a T2 control with `aria-disabled`), never a static atom
   * (#265 ruling 8, WCAG 1.4.13). A trigger that cannot take focus never shows the tooltip.
   */
  children: ReactElement<TooltipTriggerProps>;
}

/** Leave grace (H10): the pointer may cross the gap to the tooltip. CMP-049's echo shares it. */
export const LEAVE_GRACE_MS = 100;
/** Skip window: hovering to a second trigger this soon after a tooltip hid shows its tooltip at once. */
const SKIP_WINDOW_MS = 300;
/**
 * Shared module state, on purpose: the skip window spans every Tooltip on the page. It is stamped when
 * a shown tooltip starts to go (the pointer leaves it, `Esc`, blur), so moving straight from one
 * trigger to the next opens the next at once. Tests isolate it by moving the clock between cases.
 */
let lastHiddenAt = Number.NEGATIVE_INFINITY;

/** Elements that can take focus (a tab stop or not: a roving `tabindex="-1"` item counts). */
const FOCUSABLE = [
  "a[href]",
  "button",
  "input",
  "select",
  "textarea",
  "summary",
  "[tabindex]",
  '[contenteditable]:not([contenteditable="false"])',
].join(",");

const isFocusable = (element: HTMLElement): boolean =>
  element.matches(FOCUSABLE) &&
  !element.matches(":disabled") &&
  element.closest("[inert]") === null;

/** Keyboard focus shows the tooltip at once; a pointer focus waits for the hover delay. */
const isFocusVisible = (element: HTMLElement): boolean => {
  try {
    return element.matches(":focus-visible");
  } catch {
    return true;
  }
};

const warnUnfocusable = (): void => {
  if (import.meta.env?.DEV)
    console.warn("Tooltip: the trigger cannot take focus, so the tooltip never shows (CMP-016).");
};

/**
 * CMP-016: a short text that describes or echoes its trigger (H10). It shows after `delay` on hover
 * and at once on keyboard focus, stays while the pointer is on the trigger or on the tooltip (WCAG
 * 1.4.13), and hides on leave after a 100 ms grace, on blur and on `Esc`, which stops there and keeps
 * focus on the trigger (APG Tooltip). Never on a timer, never focused. The node is in the DOM from
 * mount, `hidden` until shown; the document `Esc` listener and the positioning listeners exist only
 * while it is shown.
 */
export function Tooltip({
  content,
  mode = "describes",
  side = "top",
  delay = 300,
  className,
  children,
}: TooltipProps): JSX.Element {
  const id = useId();
  // Inside a Dialog it portals into the dialog's layer, so the inert page does not take it.
  const portalRoot = useLayerPortal();
  const empty = content.trim() === "";
  const [open, setOpen] = useState(false);
  const trigger = useRef<HTMLElement | null>(null);
  const surface = useRef<HTMLDivElement | null>(null);
  const showTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const hideTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const shown = useRef(false);
  const hovered = useRef(false);
  /** Keyboard focus only: a pointer focus does not keep the tooltip past the pointer's leave. */
  const focused = useRef(false);
  /** Set by `Esc`: the tooltip stays hidden until the pointer leaves or focus moves. */
  const dismissed = useRef(false);
  /** The development warning fires once per instance, not on every hover. */
  const warned = useRef(false);

  const clearTimers = useCallback((): void => {
    clearTimeout(showTimer.current);
    clearTimeout(hideTimer.current);
  }, []);
  const hide = useCallback((): void => {
    clearTimers();
    if (shown.current) lastHiddenAt = Date.now();
    setOpen(false);
  }, [clearTimers]);
  const show = (): void => {
    clearTimers();
    if (!dismissed.current && !empty) setOpen(true);
  };
  const leave = (): void => {
    hovered.current = false;
    // A shown tooltip starts to go now: the next trigger within the skip window opens at once.
    if (shown.current && !focused.current) lastHiddenAt = Date.now();
    clearTimeout(showTimer.current);
    if (focused.current) return;
    clearTimeout(hideTimer.current);
    hideTimer.current = setTimeout(hide, LEAVE_GRACE_MS);
  };

  // Unmount clears both timers: a pending show never fires on an unmounted trigger.
  useEffect(() => clearTimers, [clearTimers]);
  useEffect(() => {
    shown.current = open;
  }, [open]);
  // The content emptied while shown (a gate lifted): it goes, with its Esc listener. Content that arrives while
  // the trigger holds keyboard focus or the pointer (a gate engaging) shows at once, unless `Esc` dismissed it or
  // the trigger has since become natively disabled (it fires no pointer leave, so its hover is stale).
  useEffect(() => {
    if (empty) hide();
    else if ((focused.current || hovered.current) && !dismissed.current) {
      const element = trigger.current;
      if (element !== null && !isFocusable(element)) hovered.current = false;
      else setOpen(true);
    }
  }, [empty, hide]);

  useEffect(() => {
    if (!open) return undefined;
    const onKeyDown = (event: KeyboardEvent): void => {
      if (event.key !== "Escape") return;
      // The topmost layer takes Esc and stops it there (conventions 32); focus is never moved.
      event.preventDefault();
      event.stopPropagation();
      dismissed.current = true;
      hide();
    };
    document.addEventListener("keydown", onKeyDown, true);
    return () => document.removeEventListener("keydown", onKeyDown, true);
  }, [open, hide]);

  useAnchoredPosition({ open, reference: trigger, floating: surface, side });
  // On a trigger in an exempt region (the TopBar) it stays live while a Dialog is open.
  useExemptWithAnchor(open, trigger, surface);

  const own = children.props;
  const triggerProps: TooltipTriggerProps = {
    "aria-describedby":
      mode === "describes" && !empty
        ? [own["aria-describedby"], id].filter((v) => v !== undefined && v !== "").join(" ")
        : own["aria-describedby"],
    onPointerEnter: (event) => {
      own.onPointerEnter?.(event);
      const element = event.currentTarget;
      if (empty) {
        // Remembered, so content that arrives while the pointer is still here shows (the effect below).
        trigger.current = element;
        hovered.current = isFocusable(element);
        return;
      }
      if (!isFocusable(element)) {
        if (!warned.current) warnUnfocusable();
        warned.current = true;
        return;
      }
      trigger.current = element;
      hovered.current = true;
      clearTimeout(hideTimer.current);
      if (open || dismissed.current) return;
      const wait = Date.now() - lastHiddenAt < SKIP_WINDOW_MS ? 0 : delay;
      clearTimeout(showTimer.current);
      showTimer.current = setTimeout(show, wait);
    },
    onPointerLeave: (event) => {
      own.onPointerLeave?.(event);
      dismissed.current = false;
      leave();
    },
    // Pressing the trigger activates it: the echo goes (APG Tooltip) so the next `Esc` belongs to what the press
    // opened (a Popover), not to a tooltip left over from the hover; it stays away until the pointer leaves or focus moves.
    onPointerDown: (event) => {
      own.onPointerDown?.(event);
      dismissed.current = true;
      hide();
    },
    // A cancelled pointer (a touch turned into a scroll, a lost capture) is no longer on the trigger.
    onPointerCancel: (event) => {
      own.onPointerCancel?.(event);
      leave();
    },
    onFocus: (event) => {
      own.onFocus?.(event);
      const element = event.currentTarget;
      trigger.current = element;
      focused.current = isFocusVisible(element);
      dismissed.current = false;
      if (focused.current) show();
    },
    onBlur: (event) => {
      own.onBlur?.(event);
      focused.current = false;
      dismissed.current = false;
      // A trigger that went natively disabled blurs and never fires its pointer leave: forget the hover.
      if (!isFocusable(event.currentTarget)) hovered.current = false;
      if (!hovered.current) hide();
    },
  };

  const tooltip = (
    <div
      ref={surface}
      id={id}
      role="tooltip"
      className={cx("cv-tooltip", className)}
      data-cmp="CMP-016"
      data-mode={mode}
      data-side={side}
      aria-hidden={mode === "echo" ? true : undefined}
      hidden={!open}
      onPointerEnter={() => {
        hovered.current = true;
        clearTimeout(hideTimer.current);
      }}
      onPointerLeave={leave}
    >
      {content}
    </div>
  );

  return (
    <>
      {cloneElement(children, triggerProps)}
      {empty || portalRoot === null ? null : createPortal(tooltip, portalRoot)}
    </>
  );
}
