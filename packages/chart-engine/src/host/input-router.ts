// The DOM half of the InputRouter (E11-S04 PR 1, 26 §3.11, README BQ-98 to BQ-102): pointer,
// touch, double-click and wheel events on the chart container become packed rows that reach the
// worker at most once per frame per kind through the host. Pointers are captured, so a drag that
// leaves the container still ends; `pointercancel` or a lost capture ends it with no coast. The
// wheel is non-passive and always prevented over the chart; its delta is normalised to px and
// folded per frame by class (zoom, pan) and region. Every gesture's meaning is the worker's
// (src/interaction/gestures.ts). DOM program (tsconfig.dom.json); O(1) per event, and no
// allocation but `getCoalescedEvents()`'s array.
import { MOD, plotHeightOf, regionAt, wheelPx } from "../interaction/wheel.js";
import { INPUT, type InputKind } from "../worker/protocol.js";

/** The `ChartHost` members the router uses (structural: no import cycle with worker/host.ts). */
export interface InputSink {
  input(
    kind: InputKind,
    row: readonly [number, number, number, number, number, number],
    fold?: number,
  ): void;
  resize(width: number, height: number, dpr: number): void;
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

const DOWN = { pointerdown: INPUT.down, pointerup: INPUT.up, pointermove: INPUT.move } as const;

/** Routes `target`'s input and size changes into `host`; returns the detach function. */
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
  const put = (code: number, p: MouseEvent, b: number, mods: number, d: number): typeof scratch => {
    scratch[0] = code;
    scratch[1] = p.offsetX;
    scratch[2] = p.offsetY;
    scratch[3] = b;
    scratch[4] = mods;
    scratch[5] = d;
    return scratch;
  };
  const row = (kind: InputKind, code: number, p: PointerEvent | MouseEvent, b: number): void => {
    host.input(kind, put(code, p, b, modifiers(p), dt(kind, p.timeStamp)));
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
  const onDblClick = (e: MouseEvent): void => {
    e.preventDefault(); // BQ-101: no text selection; the price axis's double-click is a no-op
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
    host.input("wheel", put(INPUT.wheel, e, delta, mods, t), fold);
  };

  const names = Object.keys(DOWN) as (keyof typeof DOWN)[];
  for (const n of names) target.addEventListener(n, onPointer);
  target.addEventListener("pointercancel", onCancel);
  target.addEventListener("lostpointercapture", onCancel);
  target.addEventListener("dblclick", onDblClick);
  target.addEventListener("wheel", onWheel, { passive: false });
  target.style.touchAction = "none"; // the browser neither scrolls nor zooms the page on touch
  const view = target.ownerDocument.defaultView;
  const observer =
    typeof view?.ResizeObserver === "function"
      ? new view.ResizeObserver(() =>
          host.resize(target.clientWidth, target.clientHeight, view.devicePixelRatio),
        )
      : null;
  observer?.observe(target);
  return () => {
    for (const n of names) target.removeEventListener(n, onPointer);
    target.removeEventListener("pointercancel", onCancel);
    target.removeEventListener("lostpointercapture", onCancel);
    target.removeEventListener("dblclick", onDblClick);
    target.removeEventListener("wheel", onWheel);
    observer?.disconnect();
  };
}
