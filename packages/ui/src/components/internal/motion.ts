import { useEffect, useRef, useState } from "react";

/*
 * The exit bookkeeping shared by the modal and side overlays (Dialog, Drawer; conventions 35): an overlay
 * stays rendered through its exit transition, then clears; at once when none runs.
 */

/** The in-app override wins; without one, the OS preference (as the theme runtime reads it). */
export const reducedMotion = (): boolean => {
  const mode = document.documentElement.getAttribute("data-motion");
  if (mode !== null) return mode === "reduce";
  return window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
};

/** The longest transition on `element`, in seconds (0 where the engine computes none). */
export const transitionSeconds = (element: Element): number =>
  Math.max(
    0,
    ...getComputedStyle(element)
      .transitionDuration.split(",")
      .map((part) => Number.parseFloat(part) * (part.trim().endsWith("ms") ? 0.001 : 1))
      .filter(Number.isFinite),
  );

/**
 * True while the overlay should render: from an open until its exit has ended. The exit is the
 * transition on the element `target()` returns once `open` is false; it ends on that element's own
 * `transitionend` or `transitioncancel`, or a timer just past its duration (a removed node, a throttled
 * tab), and at once with no element, no transition, or reduced motion.
 */
export function useExitTransition(
  open: boolean,
  target: () => Element | null | undefined,
): boolean {
  const [exiting, setExiting] = useState(false);
  const latest = useRef(target);
  latest.current = target;
  useEffect(() => {
    if (open) {
      setExiting(true);
      return undefined;
    }
    const node = latest.current();
    const done = (): void => setExiting(false);
    if (node === null || node === undefined) {
      done();
      return undefined;
    }
    const seconds = transitionSeconds(node);
    if (seconds <= 0.001 || reducedMotion()) {
      done();
      return undefined;
    }
    const onEnd = (event: Event): void => {
      if (event.target === node) done();
    };
    const timer = setTimeout(done, seconds * 1000 + 100);
    node.addEventListener("transitionend", onEnd);
    node.addEventListener("transitioncancel", onEnd);
    return () => {
      clearTimeout(timer);
      node.removeEventListener("transitionend", onEnd);
      node.removeEventListener("transitioncancel", onEnd);
    };
  }, [open]);
  return open || exiting;
}
