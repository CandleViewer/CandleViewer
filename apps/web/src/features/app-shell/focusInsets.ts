/**
 * Focus not obscured (WCAG 2.4.11, E47-S05 slice 4, Gherkin "A focused control is never hidden").
 *
 * Sticky chrome that can sit over a scroll container registers itself with the edge it covers. The
 * insets are the part of each registered element that overlaps the container's visible band, so
 * chrome laid out beside the container (the shell's grid rows today) costs nothing, and chrome that
 * overlays it (a sticky bar, an overlay at a reflow breakpoint) is cleared automatically. Two
 * consumers: `scroll-padding-top/bottom` on the container, so the browser's own focus scroll honours
 * the insets, and `scrollFocusIntoView` on `focusin`, the safety net for a focus the browser left
 * under the chrome. Both read geometry from events and the ResizeObserver callback only (layout is
 * already clean there), never from a render frame or a rAF loop.
 */
export type InsetEdge = "top" | "bottom";

export interface VerticalSpan {
  readonly top: number;
  readonly bottom: number;
}

export interface FocusInsets {
  readonly top: number;
  readonly bottom: number;
}

const registry = new Map<HTMLElement, InsetEdge>();
const listeners = new Set<() => void>();

const notify = (): void => {
  for (const l of listeners) l();
};

/** Registers sticky chrome covering `edge`; returns the teardown. */
export function registerFocusInset(el: HTMLElement, edge: InsetEdge): () => void {
  registry.set(el, edge);
  notify();
  return () => {
    registry.delete(el);
    notify();
  };
}

/** The part of each registered element that covers `band`, per edge (the largest wins). */
export function measureFocusInsets(band: VerticalSpan): FocusInsets {
  let top = 0;
  let bottom = 0;
  for (const [el, edge] of registry) {
    const r = el.getBoundingClientRect();
    if (r.bottom <= band.top || r.top >= band.bottom) continue;
    if (edge === "top") top = Math.max(top, r.bottom - band.top);
    else bottom = Math.max(bottom, band.bottom - r.top);
  }
  return { top, bottom };
}

/**
 * How far to scroll so `target` lies inside `band` less the insets: negative scrolls up. A target
 * taller than the clear band is aligned to its top edge, so its start is what stays visible.
 */
export function focusScrollDelta(target: VerticalSpan, band: VerticalSpan, i: FocusInsets): number {
  const top = band.top + i.top;
  const bottom = band.bottom - i.bottom;
  if (target.top < top) return target.top - top;
  if (target.bottom > bottom) return Math.min(target.bottom - bottom, target.top - top);
  return 0;
}

const scrolls = (el: HTMLElement): boolean => {
  const overflow = getComputedStyle(el).overflowY;
  return (overflow === "auto" || overflow === "scroll") && el.scrollHeight > el.clientHeight;
};

function scrollerOf(target: Element): HTMLElement | null {
  for (let p = target.parentElement; p !== null; p = p.parentElement) {
    if (p === document.body || p === document.documentElement) break;
    if (scrolls(p)) return p;
  }
  return document.scrollingElement as HTMLElement | null;
}

function bandOf(scroller: HTMLElement): VerticalSpan {
  if (scroller === document.scrollingElement) return { top: 0, bottom: window.innerHeight };
  const r = scroller.getBoundingClientRect();
  return { top: r.top, bottom: r.bottom };
}

/** Scrolls the nearest scroller (the viewport last) until `target` is clear of the registered chrome. */
export function scrollFocusIntoView(target: Element): void {
  const scroller = scrollerOf(target);
  if (scroller === null) return;
  const band = bandOf(scroller);
  const r = target.getBoundingClientRect();
  const delta = focusScrollDelta(r, band, measureFocusInsets(band));
  if (Math.abs(delta) >= 1) scroller.scrollTop += delta;
}

/**
 * Wires one scroll container: `scroll-padding-top/bottom` follow the measured insets (re-measured
 * when the container or any registered chrome resizes, a zoom or density change included), and a
 * `focusin` inside it runs `scrollFocusIntoView`. Returns the teardown.
 */
export function installFocusInsets(container: HTMLElement): () => void {
  const sync = (): void => {
    const i = measureFocusInsets(bandOf(container));
    container.style.scrollPaddingTop = `${i.top}px`;
    container.style.scrollPaddingBottom = `${i.bottom}px`;
  };
  const onFocusIn = (e: FocusEvent): void => {
    if (e.target instanceof Element) scrollFocusIntoView(e.target);
  };
  const ro = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(sync);
  const watch = (): void => {
    ro?.disconnect();
    ro?.observe(container);
    for (const el of registry.keys()) ro?.observe(el);
    sync();
  };
  listeners.add(watch);
  watch();
  container.addEventListener("focusin", onFocusIn);
  return () => {
    listeners.delete(watch);
    ro?.disconnect();
    container.removeEventListener("focusin", onFocusIn);
    container.style.removeProperty("scroll-padding-top");
    container.style.removeProperty("scroll-padding-bottom");
  };
}
