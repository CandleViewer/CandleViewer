import {
  cloneElement,
  useEffect,
  useState,
  useId,
  useLayoutEffect,
  useRef,
  type JSX,
  type MouseEvent,
  type ReactElement,
  type ReactNode,
  type RefObject,
} from "react";
import { createPortal } from "react-dom";
import { cx } from "./internal/cx.js";
import { trapTab, useFocusTrap } from "./internal/focusTrap.js";
import { useExemptWithAnchor } from "./internal/inertOutside.js";
import { useLayer, useLayerPortal } from "./internal/layers.js";
import { tabStopAfter, tabbables } from "./internal/tabbable.js";
import { useAnchoredPosition } from "./internal/useAnchoredPosition.js";
import { useControllable } from "./internal/useControllable.js";

/** The catalogue's Placement axis: the preferred side, flipped when the viewport has no room. */
export type PopoverPlacement = "below" | "above";

/** The props Popover composes onto its anchor; the anchor's own `onClick` still runs first. */
export interface PopoverAnchorProps {
  "aria-haspopup"?: "dialog" | undefined;
  "aria-expanded"?: boolean | undefined;
  "aria-controls"?: string | undefined;
  onClick?: (event: MouseEvent<HTMLElement>) => void;
}

/**
 * The dialog's accessible name, one required (H11): `aria-label`, `aria-labelledby`, or the
 * `heading` alone, which then names it through `aria-labelledby`.
 */
export type PopoverName =
  | { "aria-label": string; "aria-labelledby"?: never; heading?: string }
  | { "aria-labelledby": string; "aria-label"?: never; heading?: string }
  | { heading: string; "aria-label"?: never; "aria-labelledby"?: never };

export interface PopoverBaseProps {
  /** Controlled open state; leave it out to let the anchor toggle it (`defaultOpen`). */
  open?: boolean;
  defaultOpen?: boolean;
  /** Called with `false` on Esc, an outside press, Tab out of a non-modal popover and focus leaving it. */
  onOpenChange?: (open: boolean) => void;
  /** The trigger, one button (CMP-001 or CMP-002): it toggles the popover and gets its ARIA. */
  anchor: ReactElement<PopoverAnchorProps>;
  /** Preferred side (default `below`); it flips when the viewport has no room. */
  placement?: PopoverPlacement;
  /** A trap (APG Dialog (Modal)) with `aria-modal`; non-modal (default) lets Tab leave and close it. */
  modal?: boolean;
  /** Takes focus on open; without it the first control, else the heading, else the panel. */
  initialFocusRef?: RefObject<HTMLElement | null>;
  /** The optional footer: a CMP-001 row, end-aligned. */
  footer?: ReactNode;
  className?: string;
  /** The body: the host's content, which owns its own states. */
  children?: ReactNode;
}

export type PopoverProps = PopoverBaseProps & PopoverName;

/** The in-app override wins; without one, the OS preference (as the theme runtime reads it). */
const reducedMotion = (): boolean => {
  const mode = document.documentElement.getAttribute("data-motion");
  if (mode !== null) return mode === "reduce";
  return window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
};

/**
 * CMP-017: an anchored, portalled `role="dialog"` (H11), positioned by `useAnchoredPosition` below or
 * above its anchor. Opening moves focus into it (conventions 32); `Esc` closes it and returns focus to
 * the anchor; a press that starts and ends outside closes it, focus going to the pressed control,
 * else the anchor. Non-modal: Tab past the last control closes it and moves on from the anchor,
 * Shift+Tab before the first returns to the anchor, and focus leaving it closes it. Modal: Tab cycles
 * inside. It appears at once (it takes focus, conventions 35); the document listeners and the
 * positioning observers exist only while it is open. Closed, the panel is an empty `hidden` shell
 * (so the anchor's `aria-controls` stays valid): its heading, body and footer render only while open
 * and through the exit fade.
 *
 * It is a layer of the overlay stack: `Esc` closes the topmost layer only, a layer opened above it (a
 * menu, a nested popover) keeps it open while focus or a press is there, and inside a CMP-043 Dialog
 * it portals into that dialog's layer, so it stays outside the inert page and inside the trap's scope.
 */
export function Popover(props: PopoverProps): JSX.Element {
  const {
    open: openProp,
    defaultOpen = false,
    onOpenChange,
    anchor,
    placement = "below",
    modal = false,
    initialFocusRef,
    heading,
    footer,
    className,
    children,
  } = props;
  const label = props["aria-label"];
  const labelledBy = props["aria-labelledby"];
  const id = useId();
  const portalRoot = useLayerPortal();
  const headingId = `${id}-heading`;
  const [open, setHeld] = useControllable(openProp, defaultOpen);
  const trigger = useRef<HTMLElement | null>(null);
  const surface = useRef<HTMLDivElement | null>(null);
  const headingNode = useRef<HTMLHeadingElement | null>(null);
  /** Where the current pointer press started, between `pointerdown` and `pointerup`. */
  const press = useRef<"outside" | "anchor" | null>(null);
  /** The last element focused inside, to take focus back after a press that ends inside. */
  const lastInside = useRef<HTMLElement | null>(null);
  /** Set while this component moves focus out itself, so `blur` does not close it a second time. */
  const leaving = useRef(false);
  /** The content stays rendered through the exit fade, then clears (`transitionend`, or at once). */
  const [exiting, setExiting] = useState(false);
  const rendered = open || exiting;
  /** True from an open until its content has cleared; no fade bookkeeping on a never-opened mount. */
  const opened = useRef(false);
  /** Read at open time only, so a fresh ref object per render neither re-focuses nor closes it. */
  const initialFocus = useRef(initialFocusRef);
  initialFocus.current = initialFocusRef;

  const change = (next: boolean): void => {
    setHeld(next);
    onOpenChange?.(next);
  };
  /** The document listeners outlive a render; they reach the current `change` through this ref. */
  const latest = useRef(change);
  latest.current = change;

  // A controlled open has no click to read the anchor from: it is the element that controls this id.
  useLayoutEffect(() => {
    if (!open) return;
    for (const element of document.querySelectorAll<HTMLElement>("[aria-controls]"))
      if (element.getAttribute("aria-controls") === id) trigger.current = element;
  }, [open, id]);

  // Opened from an exempt region (a TopBar control) while a Dialog is open: the panel stays live too.
  useExemptWithAnchor(open, trigger, surface);

  useAnchoredPosition({
    open,
    reference: trigger,
    floating: surface,
    side: placement === "above" ? "top" : "bottom",
    fit: true,
  });

  // Focus in on open (conventions 32); on close, back to the anchor when focus is inside or lost.
  useEffect(() => {
    const panel = surface.current;
    if (!open || panel === null) return undefined;
    const first =
      initialFocus.current?.current ?? tabbables(panel)[0] ?? headingNode.current ?? panel;
    first.focus({ preventScroll: true });
    lastInside.current = first;
    return () => {
      const active = document.activeElement;
      const lost = active === null || active === document.body || panel.contains(active);
      const back = trigger.current;
      if (lost && back?.isConnected === true) back.focus({ preventScroll: true });
      lastInside.current = null;
    };
  }, [open]);

  // Open: the content renders. Closed: it stays for the exit fade, then clears; at once when no
  // fade runs (reduced motion, or an engine without the discrete `display` transition).
  useEffect(() => {
    const panel = surface.current;
    if (open) {
      opened.current = true;
      setExiting(true);
      return undefined;
    }
    if (!opened.current || panel === null) return undefined;
    const done = (): void => {
      opened.current = false;
      setExiting(false);
    };
    const seconds = Math.max(
      0,
      ...getComputedStyle(panel)
        .transitionDuration.split(",")
        .map((part) => Number.parseFloat(part) * (part.trim().endsWith("ms") ? 0.001 : 1))
        .filter(Number.isFinite),
    );
    if (seconds <= 0.001 || reducedMotion()) {
      done();
      return undefined;
    }
    const onEnd = (event: TransitionEvent): void => {
      if (event.target === panel) done();
    };
    // A fade that never reports its end (a removed node, a throttled tab) still clears.
    const timer = setTimeout(done, seconds * 1000 + 100);
    panel.addEventListener("transitionend", onEnd);
    panel.addEventListener("transitioncancel", onEnd);
    return () => {
      clearTimeout(timer);
      panel.removeEventListener("transitionend", onEnd);
      panel.removeEventListener("transitioncancel", onEnd);
    };
  }, [open]);

  // Esc while it is open but focus is outside it (on the anchor, or lost to the body) reaches the
  // layer stack, which closes the topmost layer. The panel's own handler stops Esc pressed inside; a
  // tooltip's capture listener takes it first (topmost).
  const layer = useLayer(open, {
    element: surface,
    modal,
    onEscape: () => latest.current(false),
  });

  // The outside-press guard: closes only when a press both starts and ends outside (and off the anchor).
  useEffect(() => {
    if (!open) return undefined;
    const within = (ref: RefObject<HTMLElement | null>, target: EventTarget | null): boolean =>
      target instanceof Node && (ref.current?.contains(target) ?? false);
    const onDown = (event: PointerEvent): void => {
      const target = event.target instanceof Node ? event.target : null;
      // A press in a layer opened above this one (a menu from it) is not an outside press.
      if (within(surface, target) || layer.inLayerAbove(target)) press.current = null;
      else press.current = within(trigger, event.target) ? "anchor" : "outside";
    };
    const onUp = (event: PointerEvent): void => {
      const started = press.current;
      press.current = null;
      if (started !== "outside") return;
      if (within(surface, event.target) || within(trigger, event.target)) {
        // A drag that came back in: it stays open, with focus where it was inside.
        if (!within(surface, document.activeElement))
          (lastInside.current ?? surface.current)?.focus({ preventScroll: true });
        return;
      }
      latest.current(false);
    };
    const onCancel = (): void => {
      press.current = null;
    };
    document.addEventListener("pointerdown", onDown, true);
    document.addEventListener("pointerup", onUp, true);
    document.addEventListener("pointercancel", onCancel, true);
    return () => {
      document.removeEventListener("pointerdown", onDown, true);
      document.removeEventListener("pointerup", onUp, true);
      document.removeEventListener("pointercancel", onCancel, true);
      press.current = null;
    };
  }, [open, layer]);

  // Modal only: focus that escapes the trap without a press (a script, a shortcut) is taken back,
  // unless it went into a layer opened above this one.
  useFocusTrap(open && modal, {
    container: surface,
    allow: (node) => layer.inLayerAbove(node),
    paused: () => press.current !== null,
    lastInside,
  });

  const moveOut = (target: HTMLElement): void => {
    leaving.current = true;
    target.focus({ preventScroll: true });
    leaving.current = false;
  };

  const onKeyDown = (event: KeyboardEvent): void => {
    if (event.key === "Escape") {
      // The topmost layer takes Esc and stops there (conventions 32); a tooltip inside takes it first.
      event.preventDefault();
      event.stopPropagation();
      change(false);
      return;
    }
    const panel = surface.current;
    if (event.key !== "Tab" || panel === null) return;
    if (modal) {
      // APG Dialog (Modal): Tab cycles inside, in DOM order from the initial focus.
      trapTab(event, panel);
      return;
    }
    const items = tabbables(panel);
    const first = items[0];
    const last = items[items.length - 1];
    const active = document.activeElement;
    const onItem = items.some((item) => item === active);
    // Non-modal (H11): Shift+Tab before the first control returns to the anchor and closes it;
    // Tab past the last closes it and moves on from the anchor.
    if (event.shiftKey && (first === undefined || active === first || !onItem)) {
      event.preventDefault();
      change(false);
    } else if (!event.shiftKey && (last === undefined || active === last)) {
      event.preventDefault();
      const from = trigger.current;
      const next = from === null ? undefined : (tabStopAfter(from, panel) ?? from);
      if (next !== undefined) moveOut(next);
      change(false);
    }
  };

  const onFocusOut = (event: FocusEvent): void => {
    const next = event.relatedTarget instanceof Node ? event.relatedTarget : null;
    const panel = surface.current;
    if (!open || leaving.current || press.current !== null || next === null || panel === null)
      return;
    if (panel.contains(next) || layer.inLayerAbove(next)) return;
    // Non-modal: focus leaving it closes it. Modal: the document `focusin` guard takes it back.
    if (!modal) change(false);
  };

  const onFocusIn = (event: FocusEvent): void => {
    if (event.target instanceof HTMLElement) lastInside.current = event.target;
  };
  /** The panel's own listeners (not global ones), bound while it is open, reach this render's handlers. */
  const panelHandlers = useRef({ onKeyDown, onFocusOut, onFocusIn });
  panelHandlers.current = { onKeyDown, onFocusOut, onFocusIn };
  useEffect(() => {
    const node = surface.current;
    if (!open || node === null) return undefined;
    const keydown = (event: KeyboardEvent): void => panelHandlers.current.onKeyDown(event);
    const focusout = (event: FocusEvent): void => panelHandlers.current.onFocusOut(event);
    const focusin = (event: FocusEvent): void => panelHandlers.current.onFocusIn(event);
    node.addEventListener("keydown", keydown);
    node.addEventListener("focusout", focusout);
    node.addEventListener("focusin", focusin);
    return () => {
      node.removeEventListener("keydown", keydown);
      node.removeEventListener("focusout", focusout);
      node.removeEventListener("focusin", focusin);
    };
  }, [open]);

  const own = anchor.props;
  const anchorProps: PopoverAnchorProps = {
    "aria-haspopup": "dialog",
    "aria-expanded": open,
    "aria-controls": id,
    onClick: (event) => {
      own.onClick?.(event);
      if (event.defaultPrevented) return;
      trigger.current = event.currentTarget;
      change(!open);
    },
  };

  const named = label === undefined && labelledBy === undefined && heading !== undefined;
  const panel = (
    <div
      ref={surface}
      id={id}
      role="dialog"
      aria-modal={modal ? true : undefined}
      aria-label={label}
      aria-labelledby={labelledBy ?? (named ? headingId : undefined)}
      tabIndex={-1}
      className={cx("cv-popover", className)}
      data-cmp="CMP-017"
      data-placement={placement}
      data-modal={modal ? "" : undefined}
      hidden={!open}
    >
      {!rendered || heading === undefined ? null : (
        <h2 ref={headingNode} id={headingId} className="cv-popover__heading" tabIndex={-1}>
          {heading}
        </h2>
      )}
      {rendered ? <div className="cv-popover__body">{children}</div> : null}
      {!rendered || footer === undefined ? null : (
        <div className="cv-popover__footer">{footer}</div>
      )}
    </div>
  );

  return (
    <>
      {cloneElement(anchor, anchorProps)}
      {portalRoot === null ? null : createPortal(panel, portalRoot)}
    </>
  );
}
