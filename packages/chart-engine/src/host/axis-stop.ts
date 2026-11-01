// The interim axis stops (E11-S06, README BQ-197, BQ-198, BQ-200; E11-D02 §7.1, §7.2, §12): one
// focusable `role="group"` surrogate per axis over its gutter, named by the worker ("Price axis,
// 63,900 to 64,300, linear, auto"). Their keys go to the worker as key rows carrying the stop as
// target (BQ-194); `Shift+F10` or the Menu key on the price stop opens SCR-043's menu (`byKey`)
// and `Esc` hands focus back to the chart. The retained labels are mirrored as one `<ul>` per axis
// in the DOM mirror (05 §6.1), text swapped in place. The engine owns no live region (ruling on
// BQ-198): announcements go out as `candleviewer:announce` events `{ politeness, text, key }`,
// coalesced on E06-D03 D5's cadence (latest state, 2/s while a key repeats, the final state within
// 250 ms of the last key), for the app's shell announcer. The stops
// let pointers through to the canvas (the gutters keep their drags); E11-S13 moves them into its
// Tab order (G-53). DOM program: it reaches the document through the container only.
import { axisKeyCode, TARGET } from "../interaction/axis-keys.js";
import { MOD } from "../interaction/wheel.js";
import { PRICE_GUTTER_PX, TIME_GUTTER_PX } from "../scene/layout-engine.js";
import { type FromWorker, INPUT } from "../worker/protocol.js";
import { type InputSink, PRICE_SCALE_MENU_EVENT } from "./input-router.js";

export const ANNOUNCE_EVENT = "candleviewer:announce";
/** The writer's key in the shell announcer: each message replaces the last (latest state). */
export const ANNOUNCE_KEY = "chart:axis";
/** E06-D03 D5 `repeatWindow`: while requests keep coming, at most one announcement per window. */
export const ANNOUNCE_WINDOW_MS = 500;
/** E06-D03 D5 `trailingFlush`: the final state is announced within this long of the last request. */
export const ANNOUNCE_TRAILING_MS = 250;

export type AxesMessage = Extract<FromWorker, { t: "axes" }>;

/** The timer the announcer waits on (the page's, or a test's fake). */
export interface AnnounceClock {
  now(): number;
  setTimer(cb: () => void, ms: number): void;
}

export interface AxisStops {
  readonly price: HTMLElement;
  readonly time: HTMLElement;
  /** Applies a worker `axes` message: names, gutter, mirror lists and its announcement. */
  update(msg: AxesMessage): void;
  setTheme(colors: Readonly<Record<string, string>>): void;
  dispose(): void;
}

/**
 * BQ-198 on E06-D03 D5's cadence (`leadDelay` 0, `repeatWindow` 500 ms, `trailingFlush` 250 ms):
 * a request with none pending and the window passed dispatches at once; later ones are coalesced
 * to the latest state, dispatched at each window's end while they keep coming, and the final state
 * lands at most 250 ms after the last request (which may be inside a window: a bounded one-off per
 * release, as D5 allows). A pending state is dropped once the target is unmounted.
 */
export function createAnnouncer(target: HTMLElement, clock: AnnounceClock): (text: string) => void {
  let last = Number.NEGATIVE_INFINITY;
  let lastAsk = 0;
  let pending: string | null = null;
  let repeatArmed = false;
  let trailArmed = false;
  const emit = (text: string): void => {
    last = clock.now();
    const Custom = target.ownerDocument.defaultView?.CustomEvent;
    if (typeof Custom !== "function") return;
    const detail = { politeness: "polite", text, key: ANNOUNCE_KEY };
    target.dispatchEvent(new Custom(ANNOUNCE_EVENT, { bubbles: true, detail }));
  };
  const flush = (): void => {
    if (pending === null) return;
    const text = pending;
    pending = null;
    if (target.isConnected !== false) emit(text); // unmounted: drop it
  };
  // The clock has no cancel: a timer that fires early (a flush moved the window, or a newer
  // request moved the trailing deadline) re-arms for what is left.
  const onRepeat = (): void => {
    repeatArmed = false;
    if (pending === null) return;
    const wait = last + ANNOUNCE_WINDOW_MS - clock.now();
    if (wait > 0) {
      repeatArmed = true;
      clock.setTimer(onRepeat, wait);
      return;
    }
    flush();
  };
  const onTrail = (): void => {
    trailArmed = false;
    if (pending === null) return;
    const wait = lastAsk + ANNOUNCE_TRAILING_MS - clock.now();
    if (wait > 0) {
      trailArmed = true;
      clock.setTimer(onTrail, wait);
      return;
    }
    flush();
  };
  return (text) => {
    const now = clock.now();
    if (pending === null && now - last >= ANNOUNCE_WINDOW_MS) {
      emit(text);
      return;
    }
    pending = text;
    lastAsk = now;
    if (!repeatArmed) {
      repeatArmed = true;
      clock.setTimer(onRepeat, Math.max(0, last + ANNOUNCE_WINDOW_MS - now));
    }
    if (!trailArmed) {
      trailArmed = true;
      clock.setTimer(onTrail, ANNOUNCE_TRAILING_MS);
    }
  };
}

const modsOf = (e: KeyboardEvent): number =>
  (e.shiftKey ? MOD.shift : 0) |
  (e.ctrlKey ? MOD.ctrl : 0) |
  (e.altKey ? MOD.alt : 0) |
  (e.metaKey ? MOD.meta : 0);

export function createAxisStops(
  container: HTMLElement,
  mirrorRoot: HTMLElement,
  host: InputSink,
  colors: Readonly<Record<string, string>>,
  clock: AnnounceClock,
): AxisStops {
  const doc = container.ownerDocument;
  let theme = colors;
  const say = createAnnouncer(container, clock);
  const stop = (target: number, name: string): HTMLElement => {
    const el = doc.createElement("div");
    el.setAttribute("role", "group");
    el.setAttribute("tabindex", "0");
    el.setAttribute("aria-label", name);
    el.setAttribute("data-cv-axis-stop", target === TARGET.price ? "price" : "time");
    const s = el.style;
    s.position = "absolute";
    s.pointerEvents = "none"; // pointers reach the canvas: the gutter keeps its drag and wheel
    s.outlineOffset = "-2px"; // the CMP-039 ring, inside the gutter (E11-D02 §7.1)
    el.addEventListener(
      "focus",
      () => (s.outline = `2px solid ${theme["color.focus.ring"] ?? ""}`),
    );
    el.addEventListener("blur", () => (s.outline = "none"));
    el.addEventListener("keydown", (e) => onKey(e, target));
    container.appendChild(el);
    return el;
  };
  const list = (name: string): HTMLUListElement => {
    const ul = doc.createElement("ul");
    ul.setAttribute("aria-label", name);
    mirrorRoot.appendChild(ul);
    return ul;
  };
  const price = stop(TARGET.price, "Price axis");
  const time = stop(TARGET.time, "UTC time axis");
  const lists = [list("Time axis labels"), list("Price axis labels")] as const;

  function onKey(e: KeyboardEvent, target: number): void {
    const menu = e.key === "ContextMenu" || (e.key === "F10" && e.shiftKey);
    if (menu && target === TARGET.price) {
      const r = price.getBoundingClientRect?.();
      const detail = { pane: 0, x: r?.left ?? 0, y: r?.top ?? 0, byKey: true };
      const Custom = doc.defaultView?.CustomEvent;
      if (typeof Custom === "function") {
        price.dispatchEvent(new Custom(PRICE_SCALE_MENU_EVENT, { bubbles: true, detail }));
      }
    } else if (e.key === "Escape") container.focus({ preventScroll: true });
    else {
      const mods = modsOf(e);
      const code = axisKeyCode(e.key, e.code, mods);
      if (code === 0) return; // Tab and the page's own keys pass
      host.input("key", [INPUT.key, code, target, 0, mods, 0]);
    }
    e.preventDefault();
    e.stopPropagation(); // the chart's plot keys never see an axis key
  }

  function mirror(ul: HTMLUListElement, labels: readonly string[]): void {
    for (let i = 0; i < labels.length; i += 1) {
      let li = ul.children[i];
      if (li === undefined) li = ul.appendChild(doc.createElement("li"));
      if (li.textContent !== labels[i]) li.textContent = labels[i] ?? "";
    }
    while (ul.children.length > labels.length) ul.children[ul.children.length - 1]?.remove();
  }

  const place = (gutter: number): void => {
    Object.assign(price.style, { top: "0px", right: "0px", width: `${gutter}px` });
    price.style.bottom = `${TIME_GUTTER_PX}px`;
    Object.assign(time.style, { left: "0px", bottom: "0px", right: `${gutter}px` });
    time.style.height = `${TIME_GUTTER_PX}px`;
  };
  place(PRICE_GUTTER_PX);

  return {
    price,
    time,
    update(msg: AxesMessage): void {
      price.setAttribute("aria-label", msg.priceName);
      time.setAttribute("aria-label", msg.timeName);
      place(msg.priceGutter);
      mirror(lists[0], msg.time);
      mirror(lists[1], msg.price);
      if (msg.say !== undefined) say(msg.say);
    },
    setTheme(next: Readonly<Record<string, string>>): void {
      theme = next;
    },
    dispose(): void {
      price.remove();
      time.remove();
      for (const ul of lists) ul.remove();
    },
  };
}
