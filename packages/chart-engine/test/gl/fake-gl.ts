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
  /** A shader whose source contains this fails COMPILE_STATUS with `infoLog`. */
  failCompile?: string;
  infoLog?: string;
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
  /** Buffer writes: `full <bytes>` or `sub <dstByte> <srcOffset> <length>`. */
  readonly writes: string[] = [];
  /** The colour of each `clear`, as `#rrggbb`: the fake's pixels. */
  readonly clears: string[] = [];
  private color = "#000000";
  private readonly sources = new Map<GLObject, string>();
  lost = false;
  /** 1-based call number that throws (a driver fault), or 0 for none. */
  failAt = 0;
  /** 1-based call number at which the context is lost (before the call runs), or 0 for none. */
  loseAt = 0;
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
    if (this.calls === this.loseAt) this.loseContext();
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
  createShader = (): GLObject | null => this.make("Shader");
  deleteShader = (o: GLObject | null): void => this.remove("Shader", o);
  shaderSource(shader: GLObject, source: string): void {
    if (this.call("shaderSource")) this.sources.set(shader, source);
  }
  private fails(shader: GLObject): boolean {
    const bad = this.opts.failCompile;
    return bad !== undefined && (this.sources.get(shader) ?? "").includes(bad);
  }
  getShaderParameter(shader: GLObject): unknown {
    return this.call("getShaderParameter") && !this.fails(shader);
  }
  getShaderInfoLog(shader: GLObject): string | null {
    return this.call("getShaderInfoLog") && this.fails(shader) ? (this.opts.infoLog ?? "") : "";
  }
  getProgramParameter = (): unknown => this.call("getProgramParameter");
  getProgramInfoLog = (): string | null => (this.call("getProgramInfoLog") ? "" : null);
  getUniformLocation(_p: GLObject, name: string): unknown {
    return this.call("getUniformLocation") ? { name } : null;
  }
  bufferData(_t: number, data: ArrayBufferView): void {
    if (this.call("bufferData")) this.writes.push(`full ${data.byteLength}`);
  }
  bufferSubData(_t: number, dst: number, _src: ArrayBufferView, from: number, n: number): void {
    if (this.call("bufferSubData")) this.writes.push(`sub ${dst} ${from} ${n}`);
  }
  compileShader = (): void => void this.call("compileShader");
  attachShader = (): void => void this.call("attachShader");
  linkProgram = (): void => void this.call("linkProgram");
  useProgram = (): void => void this.call("useProgram");
  bindBuffer = (): void => void this.call("bindBuffer");
  bindVertexArray = (): void => void this.call("bindVertexArray");
  activeTexture = (): void => void this.call("activeTexture");
  bindTexture = (): void => void this.call("bindTexture");
  texParameteri = (): void => void this.call("texParameteri");
  texImage2D = (): void => void this.call("texImage2D");
  texSubImage2D = (): void => void this.call("texSubImage2D");
  viewport = (): void => void this.call("viewport");
  clearColor(...rgba: number[]): void {
    const hex = (v: number): string =>
      Math.round(v * 255)
        .toString(16)
        .padStart(2, "0");
    if (this.call("clearColor")) this.color = `#${rgba.slice(0, 3).map(hex).join("")}`;
  }
  clear(): void {
    if (this.call("clear")) this.clears.push(this.color);
  }
  drawArraysInstanced = (): void => void this.call("drawArraysInstanced");
}

/** The `full` report a roomy context yields: the stub probe of the worker and host tests. */
export const FULL: CapabilityReport = probeCapabilities(new FakeGl({ params: ROOMY }));
