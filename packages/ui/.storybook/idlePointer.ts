/**
 * The runner's idle pointer, muted while a play runs in Vitest's browser tester (#5274). A play drives its story
 * with synthetic events, and nothing moves the runner's real pointer. That pointer still sits at the page's
 * top-left, where the tester draws the story flush. When a story mounts under it, Chromium sends trusted boundary
 * events there a frame or so later. One that lands after a play's synthetic hover reads as the pointer leaving what
 * the play hovers, and CMP-049's table rightly drops the echo it was about to show: a trusted `pointerover` on the
 * table's caption cleared the echo's timer 20 to 50 ms after the hover. Storybook itself has no tester, so a person's
 * pointer there is never touched.
 */
const IDLE_POINTER_EVENTS = [
  "pointerover",
  "pointerout",
  "pointerenter",
  "pointerleave",
  "pointermove",
  "mouseover",
  "mouseout",
  "mouseenter",
  "mouseleave",
  "mousemove",
] as const;

/** Stops a trusted event before the story sees it; a play's own events are synthetic and pass. */
export function stopTrusted(event: Event): void {
  if (event.isTrusted) event.stopImmediatePropagation();
}

/** Mutes the idle pointer's moves and boundary events on `target`, ahead of every listener; returns the undo. */
export function muteIdlePointer(target: EventTarget = window): () => void {
  for (const type of IDLE_POINTER_EVENTS) target.addEventListener(type, stopTrusted, true);
  return () => {
    for (const type of IDLE_POINTER_EVENTS) target.removeEventListener(type, stopTrusted, true);
  };
}

/** True in Vitest's browser tester, where the storybook project runs the plays; never in Storybook itself. */
export function inVitestTester(): boolean {
  return (globalThis as { __vitest_browser__?: unknown }).__vitest_browser__ === true;
}
