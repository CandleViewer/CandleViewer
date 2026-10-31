// The DOM half of the InputRouter (E11-S04 PR 1, 26 §3.11, README BQ-98 to BQ-102): pointer,
// touch, double-click and wheel events on the chart container become packed rows that reach the
// worker at most once per frame per kind through the host. Pointers are captured, so a drag that
// leaves the container still ends; `pointercancel` or a lost capture ends it with no coast. The
// wheel is non-passive and always prevented over the chart; its delta is normalised to px and
// folded per frame by class (zoom, pan) and region. Every gesture's meaning is the worker's
// (src/interaction/gestures.ts). Keys (PR 2, BQ-106 to BQ-109) are heard on the container only,
// never the window: the navigator's keys are prevented, Space only mid-drag, and a held Space is
// released on focus loss. E11-S05 (BQ-124): a right-click over the price gutter dispatches
// `candleviewer:pricescalemenu` for the app's menu (E11-S06's axis stop adds the keys). DOM
// program (tsconfig.dom.json); O(1) per event, and no allocation but `getCoalescedEvents()`'s array.
import { isSpace, keyCode } from "../interaction/navigator.js";
import { MOD, plotHeightOf, REGION, regionAt, wheelPx } from "../interaction/wheel.js";
import { INPUT, KEY, type InputKind } from "../worker/protocol.js";

/** The `ChartHost` members the router uses (structural: no import cycle with worker/host.ts). */
export interface InputSink {
  input(
    kind: InputKind,
    row: readonly [number, number, number, number, number, number],
    fold?: number,
  ): void;
}

interface Modded {
  shiftKey: boolean;
  ctrlKey: boolean;
  altKey: boolean;
  metaKey: boolean;
}

const modifiers = (e: Modded): number =>
  (e.shiftKey ? MOD.shift : 0) |
  (e.ctrlKey ? MOD.ctrl : 0) |
  (e.altKey ? MOD.alt : 0) |
  (e.metaKey ? MOD.meta : 0);

/** The app's SCR-043 menu listens for it (detail `{ pane, x, y, byKey }`, client px). */
export const PRICE_SCALE_MENU_EVENT = "candleviewer:pricescalemenu";

const DOWN = { pointerdown: INPUT.down, pointerup: INPUT.up, pointermove: INPUT.move } as const;

/** Routes `target`'s input into `host`; returns the detach function (size: host/resize.ts). */
export function routeInput(target: HTMLElement, host: InputSink): () => void {
  // `dt` per kind (BQ-99): a wheel between two moves must not shorten the velocity's window.
  const last: Record<InputKind, number> = { pointer: 0, wheel: 0, key: 0, touch: 0 };
  const dt = (kind: InputKind, t: number): number => {
    const d = last[kind] === 0 ? 0 : t - last[kind];
    last[kind] = t;
    return d;
  };
  const active = new Set<number>(); // pointers down and captured
  // One scratch row: the host copies it synchronously, so no tuple is allocated per event.
  const scratch: [number, number, number, number, number, number] = [0, 0, 0, 0, 0, 0];
  type Row = typeof scratch;
  const put = (code: number, x: number, y: number, b: number, mods: number, d: number): Row => {
    scratch[0] = code;
    scratch[1] = x;
    scratch[2] = y;
    scratch[3] = b;
    scratch[4] = mods;
    scratch[5] = d;
    return scratch;
  };
  const row = (kind: InputKind, code: number, p: PointerEvent | MouseEvent, b: number): void => {
    host.input(kind, put(code, p.offsetX, p.offsetY, b, modifiers(p), dt(kind, p.timeStamp)));
  };
  const kindOf = (e: PointerEvent): InputKind => (e.pointerType === "touch" ? "touch" : "pointer");
  // A touch row carries the pointer id in the buttons slot (BQ-102), for the pinch.
  const slot = (e: PointerEvent, p: PointerEvent): number =>
    e.pointerType === "touch" ? e.pointerId : p.buttons;

  const onPointer = (e: PointerEvent): void => {
    const code = DOWN[e.type as keyof typeof DOWN];
    if (code === INPUT.down) {
      active.add(e.pointerId);
      try {
        target.setPointerCapture(e.pointerId);
      } catch {
        // The pointer is already gone (InvalidStateError): its up or cancel follows.
      }
    } else if (code === INPUT.up) active.delete(e.pointerId);
    const list =
      code === INPUT.move && typeof e.getCoalescedEvents === "function"
        ? e.getCoalescedEvents()
        : [];
    if (list.length === 0) row(kindOf(e), code, e, slot(e, e));
    for (const p of list) row(kindOf(e), code, p, slot(e, p));
  };
  // A cancel, or a capture lost before the up (after it, the pointer is no longer active).
  const onCancel = (e: PointerEvent): void => {
    if (active.delete(e.pointerId)) row(kindOf(e), INPUT.cancel, e, slot(e, e));
  };
  // G-29: a mouse or pen leaving the canvas clears the hover pick (a finger has no hover).
  const onLeave = (e: PointerEvent): void => {
    if (e.pointerType !== "touch") row("pointer", INPUT.leave, e, e.buttons);
  };
  const onDblClick = (e: MouseEvent): void => {
    e.preventDefault(); // BQ-101: no text selection; on the price axis it restores auto (BQ-122)
    row("pointer", INPUT.dblclick, e, 0);
  };
  const onWheel = (e: WheelEvent): void => {
    e.preventDefault(); // BQ-100: the page never scrolls or zooms under the chart
    const w = target.clientWidth;
    const h = target.clientHeight;
    const page = Math.max(1, plotHeightOf(h));
    const dx = wheelPx(e.deltaX, e.deltaMode, page);
    const dy = wheelPx(e.deltaY, e.deltaMode, page);
    // Shift+wheel, or a dominant horizontal delta, pans; any other wheel (Ctrl too) zooms time.
    const horizontal = Math.abs(dx) > Math.abs(dy);
    const pan = e.shiftKey || horizontal;
    const delta = horizontal ? dx : dy;
    const mods = modifiers(e) | (pan ? MOD.pan : 0);
    const fold = (pan ? 3 : 0) + regionAt(e.offsetX, e.offsetY, w, h);
    const t = dt("wheel", e.timeStamp);
    host.input("wheel", put(INPUT.wheel, e.offsetX, e.offsetY, delta, mods, t), fold);
  };

  const onContextMenu = (e: MouseEvent): void => {
    if (regionAt(e.offsetX, e.offsetY, target.clientWidth, target.clientHeight) !== REGION.price) {
      return; // the plot's menu is the app's
    }
    e.preventDefault();
    const Custom = target.ownerDocument.defaultView?.CustomEvent;
    if (typeof Custom !== "function") return;
    const detail = { pane: 0, x: e.clientX, y: e.clientY, byKey: false };
    target.dispatchEvent(new Custom(PRICE_SCALE_MENU_EVENT, { bubbles: true, detail }));
  };

  let space = false; // BQ-109: the pan-drag modifier, held
  const key = (code: number, mods: number, t: number): void => {
    host.input("key", put(INPUT.key, code, 0, 0, mods, dt("key", t))); // x is the KEY code
  };
  const onKeyDown = (e: KeyboardEvent): void => {
    if (isSpace(e.key, e.code)) {
      if (active.size > 0) e.preventDefault(); // only mid-drag: Space is the page's otherwise
      if (!space) key(KEY.spaceDown, modifiers(e), e.timeStamp);
      space = true;
      return;
    }
    const code = keyCode(e.key, e.code, modifiers(e));
    if (code === 0) return;
    e.preventDefault(); // the arrows, Home, End and +/- never scroll the page under the chart
    key(code, modifiers(e), e.timeStamp);
  };
  const release = (e: Event): void => {
    if (!space) return;
    space = false;
    key(KEY.spaceUp, 0, e.timeStamp);
  };
  const onKeyUp = (e: KeyboardEvent): void => {
    if (isSpace(e.key, e.code)) release(e);
  };

  const names = Object.keys(DOWN) as (keyof typeof DOWN)[];
  for (const n of names) target.addEventListener(n, onPointer);
  target.addEventListener("pointercancel", onCancel);
  target.addEventListener("lostpointercapture", onCancel);
  target.addEventListener("pointerleave", onLeave);
  target.addEventListener("dblclick", onDblClick);
  target.addEventListener("contextmenu", onContextMenu);
  target.addEventListener("wheel", onWheel, { passive: false });
  target.addEventListener("keydown", onKeyDown);
  target.addEventListener("keyup", onKeyUp);
  target.addEventListener("focusout", release);
  target.style.touchAction = "none"; // the browser neither scrolls nor zooms the page on touch
  return () => {
    for (const n of names) target.removeEventListener(n, onPointer);
    target.removeEventListener("pointercancel", onCancel);
    target.removeEventListener("lostpointercapture", onCancel);
    target.removeEventListener("pointerleave", onLeave);
    target.removeEventListener("dblclick", onDblClick);
    target.removeEventListener("contextmenu", onContextMenu);
    target.removeEventListener("wheel", onWheel);
    target.removeEventListener("keydown", onKeyDown);
    target.removeEventListener("keyup", onKeyUp);
    target.removeEventListener("focusout", release);
  };
}
