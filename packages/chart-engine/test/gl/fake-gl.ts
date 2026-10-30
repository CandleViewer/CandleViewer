// A hand-written fake WebGL2 context (E11-S02, README BQ-63: no headless-gl dependency). It logs
// every call, behaves like a lost context after `loseContext()` (calls no-op, `getError` is
// CONTEXT_LOST_WEBGL, `create*` returns null), and can fail call N (`failAt`) to inject faults.
import { probeCapabilities, type CapabilityReport } from "../../src/gl/capability.js";
import { GL, type ContextAttributes, type GL2Like, type GLObject } from "../../src/gl/gl-types.js";

export interface FakeGlOptions {
  /** `getParameter` answers; anything missing is null. */
  params?: Readonly<Record<number, unknown>>;
  /** Extensions present (name to the object `getExtension` returns). */
  extensions?: Readonly<Record<string, object>>;
  /** What `getContextAttributes()` reports. */
  attributes?: ContextAttributes;
}

/** Limits above every BQ-50 floor. */
export const ROOMY = {
  [GL.MAX_TEXTURE_SIZE]: 16384,
  [GL.MAX_VERTEX_ATTRIBS]: 16,
  [GL.MAX_TEXTURE_IMAGE_UNITS]: 16,
};

export class FakeGl implements GL2Like {
  readonly log: string[] = [];
  /** Objects created and neither deleted nor dropped by a loss. */
  readonly alive = new Set<GLObject>();
  lost = false;
  /** 1-based call number that throws (a driver fault), or 0 for none. */
  failAt = 0;
  private calls = 0;
  private seq = 0;

  constructor(private readonly opts: FakeGlOptions = {}) {}

  loseContext(): void {
    this.lost = true;
    this.alive.clear();
  }

  restoreContext(): void {
    this.lost = false;
  }

  private call(name: string): boolean {
    this.calls += 1;
    this.log.push(name);
    if (this.calls === this.failAt) throw new Error(`fake GL fault at call ${this.calls}: ${name}`);
    return !this.lost;
  }

  private make(kind: string): GLObject | null {
    if (!this.call(`create${kind}`)) return null;
    this.seq += 1;
    const o = { kind, id: this.seq };
    this.alive.add(o);
    return o;
  }

  private remove(kind: string, o: GLObject | null): void {
    if (this.call(`delete${kind}`) && o !== null) this.alive.delete(o);
  }

  getParameter(pname: number): unknown {
    return this.call("getParameter") ? (this.opts.params?.[pname] ?? null) : null;
  }
  getExtension(name: string): unknown {
    if (!this.call("getExtension")) return null;
    if (name === "WEBGL_lose_context") {
      return { loseContext: () => this.loseContext(), restoreContext: () => this.restoreContext() };
    }
    return this.opts.extensions?.[name] ?? null;
  }
  getContextAttributes(): ContextAttributes | null {
    return this.call("getContextAttributes") ? (this.opts.attributes ?? {}) : null;
  }
  getError(): number {
    return this.call("getError") ? GL.NO_ERROR : GL.CONTEXT_LOST_WEBGL;
  }
  isContextLost(): boolean {
    this.call("isContextLost");
    return this.lost;
  }
  createProgram = (): GLObject | null => this.make("Program");
  deleteProgram = (o: GLObject | null): void => this.remove("Program", o);
  createBuffer = (): GLObject | null => this.make("Buffer");
  deleteBuffer = (o: GLObject | null): void => this.remove("Buffer", o);
  createTexture = (): GLObject | null => this.make("Texture");
  deleteTexture = (o: GLObject | null): void => this.remove("Texture", o);
  createVertexArray = (): GLObject | null => this.make("VertexArray");
  deleteVertexArray = (o: GLObject | null): void => this.remove("VertexArray", o);
}

/** The `full` report a roomy context yields: the stub probe of the worker and host tests. */
export const FULL: CapabilityReport = probeCapabilities(new FakeGl({ params: ROOMY }));
