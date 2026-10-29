// A minimal structural DOM for the node-environment unit project: just what src/host touches.
// The package has no jsdom (no new dependency); apps/web's binding tests run the real thing.

export interface FakeContext2D {
  fillStyle: string;
  readonly fills: { color: string; w: number; h: number }[];
  clears: number;
  clearRect(x: number, y: number, w: number, h: number): void;
  fillRect(x: number, y: number, w: number, h: number): void;
}

export interface FakeWebGl2 {
  lost: boolean;
  getExtension(name: string): { loseContext(): void } | null;
}

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

  constructor(tagName: string, doc: FakeDocument) {
    this.tagName = tagName.toUpperCase();
    this.ownerDocument = doc;
  }

  setAttribute(name: string, value: string): void {
    this.attributes.set(name, value);
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
}

export class FakeDocument {
  defaultView: { devicePixelRatio: number } | null = { devicePixelRatio: 2 };
  readonly created: FakeElement[] = [];
  webgl2Available = true;
  context2dAvailable = true;

  createElement(tag: string): FakeElement {
    const el = new FakeElement(tag, this);
    if (tag === "canvas") {
      el.webgl2 = this.webgl2Available ? makeWebGl2() : null;
      el.context2d = this.context2dAvailable ? makeContext() : null;
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
  const gl: FakeWebGl2 = {
    lost: false,
    getExtension(name: string) {
      if (name !== "WEBGL_lose_context") return null;
      return {
        loseContext(): void {
          gl.lost = true;
        },
      };
    },
  };
  return gl;
}
