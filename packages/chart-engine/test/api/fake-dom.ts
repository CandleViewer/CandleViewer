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

export class FakeElement {
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

  constructor(tagName: string, doc: FakeDocument) {
    this.tagName = tagName.toUpperCase();
    this.ownerDocument = doc;
  }

  setAttribute(name: string, value: string): void {
    this.attributes.set(name, value);
  }

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

  dispatch(type: string, event: object): void {
    for (const cb of this.listeners.get(type) ?? []) cb({ type, ...event });
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
    return kind === "2d" ? this.el.context2d : null;
  }
  convertToBlob(): Promise<Blob> {
    const blob = this.el.blob;
    return blob === null ? Promise.reject(new Error("encode")) : Promise.resolve(blob);
  }
}

export interface FakeView {
  devicePixelRatio: number;
  OffscreenCanvas?: unknown;
  ResizeObserver?: unknown;
}

export class FakeDocument {
  defaultView: FakeView | null = { devicePixelRatio: 2 };
  /** Worker mode: the view has OffscreenCanvas and every canvas can transfer its control. */
  offscreenAvailable = false;
  /** `transferControlToOffscreen` exists but throws (a canvas that already has a context). */
  offscreenThrows = false;
  readonly created: FakeElement[] = [];
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
