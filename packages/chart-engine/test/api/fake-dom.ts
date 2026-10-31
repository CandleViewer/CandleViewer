// A minimal structural DOM for the node-environment unit project: just what src/host touches.
// The package has no jsdom (no new dependency); apps/web's binding tests run the real thing.
import { FakeGl, ROOMY } from "../gl/fake-gl.js";

export interface FakeContext2D {
  fillStyle: string;
  readonly fills: { color: string; w: number; h: number }[];
  clears: number;
  clearRect(x: number, y: number, w: number, h: number): void;
  fillRect(x: number, y: number, w: number, h: number): void;
}

/** WebGL2 here is the E11-S02 fake with every BQ-50 floor met (the `full` profile). */
export type FakeWebGl2 = FakeGl;

/** Listeners and a synchronous `dispatch` (elements and, for E11-S04's motion event, documents). */
export class FakeTarget {
  readonly listeners = new Map<string, Set<(e: unknown) => void>>();

  addEventListener(type: string, cb: (e: unknown) => void): void {
    let set = this.listeners.get(type);
    if (set === undefined) {
      set = new Set();
      this.listeners.set(type, set);
    }
    set.add(cb);
  }

  removeEventListener(type: string, cb: (e: unknown) => void): void {
    this.listeners.get(type)?.delete(cb);
  }

  /** `EventTarget.dispatchEvent` over `dispatch` (E11-S05's `candleviewer:pricescalemenu`). */
  dispatchEvent(event: { type: string }): boolean {
    return !this.dispatch(event.type, event);
  }

  /** Delivers `event` to every listener; returns whether one called `preventDefault`. */
  dispatch(type: string, event: object): boolean {
    let prevented = false;
    const preventDefault = (): void => void (prevented = true);
    for (const cb of this.listeners.get(type) ?? []) cb({ type, preventDefault, ...event });
    return prevented;
  }
}

export class FakeElement extends FakeTarget {
  readonly tagName: string;
  readonly attributes = new Map<string, string>();
  readonly style: Record<string, string> = {};
  readonly children: FakeElement[] = [];
  parent: FakeElement | null = null;
  width = 0;
  height = 0;
  clientWidth = 0;
  clientHeight = 0;
  ownerDocument: FakeDocument;
  context2d: FakeContext2D | null = null;
  webgl2: FakeWebGl2 | null = null;
  blob: Blob | null = null;
  transferred = false;
  textContent = "";

  constructor(tagName: string, doc: FakeDocument) {
    super();
    this.tagName = tagName.toUpperCase();
    this.ownerDocument = doc;
  }

  setAttribute(name: string, value: string): void {
    this.attributes.set(name, value);
  }

  getAttribute(name: string): string | null {
    return this.attributes.get(name) ?? null;
  }

  /** Pointer ids captured by `setPointerCapture` (E11-S04), in order. */
  readonly captured: number[] = [];

  setPointerCapture(id: number): void {
    this.captured.push(id);
  }

  /** Moves the document's `activeElement` here (E11-S05's badge hand-off). */
  focus(): void {
    this.ownerDocument.activeElement = this;
  }

  insertBefore(child: FakeElement, ref: FakeElement): FakeElement {
    child.parent = this;
    const i = this.children.indexOf(ref);
    this.children.splice(i < 0 ? this.children.length : i, 0, child);
    return child;
  }

  appendChild(child: FakeElement): FakeElement {
    child.parent = this;
    this.children.push(child);
    return child;
  }

  remove(): void {
    const siblings = this.parent?.children;
    if (siblings !== undefined) siblings.splice(siblings.indexOf(this), 1);
    this.parent = null;
  }

  getContext(kind: string): unknown {
    if (kind === "2d") return this.context2d;
    if (kind === "webgl2") return this.webgl2;
    return null;
  }

  toBlob(cb: (b: Blob | null) => void): void {
    cb(this.blob);
  }

  /** Present only when the document is set up for worker mode (`offscreenAvailable`). */
  transferControlToOffscreen?: () => FakeOffscreen;
}

/** The OffscreenCanvas a fake canvas hands over: it draws into the element's own context. */
export class FakeOffscreen {
  constructor(private readonly el: FakeElement) {}
  get width(): number {
    return this.el.width;
  }
  set width(w: number) {
    this.el.width = w;
  }
  get height(): number {
    return this.el.height;
  }
  set height(h: number) {
    this.el.height = h;
  }
  getContext(kind: string): unknown {
    return this.el.getContext(kind);
  }
  convertToBlob(): Promise<Blob> {
    const blob = this.el.blob;
    return blob === null ? Promise.reject(new Error("encode")) : Promise.resolve(blob);
  }
}

export interface FakeView {
  devicePixelRatio: number;
  CustomEvent?: unknown;
  OffscreenCanvas?: unknown;
  ResizeObserver?: unknown;
  matchMedia?: (query: string) => FakeMediaQuery;
}

type Box = { inlineSize: number; blockSize: number };

/**
 * A ResizeObserver double (E11-S10): `fire(device?, css?)` runs the callback with one entry,
 * carrying a device-pixel-content-box and a content-box size when given; `dpcb: false` makes the
 * device box option throw, as a browser without it does. `observed` holds the observe options while observing.
 */
export function fakeResizeObserver(dpcb = true) {
  const state: {
    observed: unknown[];
    fire: (device?: Box, css?: Box) => void;
    ctor: unknown;
  } = {
    observed: [],
    fire: () => undefined,
    ctor: class {
      constructor(cb: (entries: object[]) => void) {
        state.fire = (device, css) =>
          cb([
            {
              ...(device === undefined ? {} : { devicePixelContentBoxSize: [device] }),
              ...(css === undefined ? {} : { contentBoxSize: [css] }),
            },
          ]);
      }
      observe(_t: unknown, opts?: { box?: string }): void {
        if (opts?.box === "device-pixel-content-box" && !dpcb) throw new TypeError("box");
        state.observed.push(opts ?? null);
      }
      disconnect(): void {
        state.observed.length = 0;
      }
    },
  };
  return state;
}

/** One `matchMedia` result; `change()` fires and drops its `once` listeners. */
export class FakeMediaQuery {
  readonly listeners = new Set<() => void>();
  constructor(readonly media: string) {}
  addEventListener(_t: string, cb: () => void): void {
    this.listeners.add(cb);
  }
  removeEventListener(_t: string, cb: () => void): void {
    this.listeners.delete(cb);
  }
  change(): void {
    const all = [...this.listeners];
    this.listeners.clear();
    for (const cb of all) cb();
  }
}

/** Installs `matchMedia` on `view`; `queries` lists every query armed, in order. */
export function fakeMatchMedia(view: FakeView): FakeMediaQuery[] {
  const queries: FakeMediaQuery[] = [];
  view.matchMedia = (media) => {
    const q = new FakeMediaQuery(media);
    queries.push(q);
    return q;
  };
  return queries;
}

export class FakeDocument extends FakeTarget {
  /** The root `data-motion` is read from (E11-S04, BQ-104). */
  readonly documentElement: FakeElement = new FakeElement("html", this);
  defaultView: FakeView | null = { devicePixelRatio: 2 };
  /** Worker mode: the view has OffscreenCanvas and every canvas can transfer its control. */
  offscreenAvailable = false;
  /** `transferControlToOffscreen` exists but throws (a canvas that already has a context). */
  offscreenThrows = false;
  readonly created: FakeElement[] = [];
  activeElement: FakeElement | null = null;
  webgl2Available = true;
  context2dAvailable = true;

  createElement(tag: string): FakeElement {
    const el = new FakeElement(tag, this);
    if (tag === "canvas") {
      el.webgl2 = this.webgl2Available ? makeWebGl2() : null;
      el.context2d = this.context2dAvailable ? makeContext() : null;
      if (this.offscreenAvailable) {
        el.transferControlToOffscreen = () => {
          if (this.offscreenThrows) throw new Error("InvalidStateError: has a context");
          if (el.transferred) throw new Error("InvalidStateError: already transferred");
          el.transferred = true;
          return new FakeOffscreen(el);
        };
      }
    }
    this.created.push(el);
    return el;
  }
}

function makeContext(): FakeContext2D {
  const fills: FakeContext2D["fills"] = [];
  return {
    fillStyle: "",
    fills,
    clears: 0,
    clearRect(): void {
      this.clears += 1;
    },
    fillRect(_x: number, _y: number, w: number, h: number): void {
      fills.push({ color: this.fillStyle, w, h });
    },
  };
}

/** A container of the given CSS size in a fresh fake document. */
export function fakeContainer(width = 400, height = 300): FakeElement {
  const doc = new FakeDocument();
  const el = new FakeElement("div", doc);
  el.clientWidth = width;
  el.clientHeight = height;
  return el;
}

/** The fake as the HTMLElement the engine API takes (structural stand-in, test-only cast). */
export const asHtml = (el: FakeElement): HTMLElement => el as unknown as HTMLElement;

function makeWebGl2(): FakeWebGl2 {
  return new FakeGl({ params: ROOMY });
}
