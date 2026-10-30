// The program cache (E11-S02, 26 §3.4): each program compiles and links lazily, on the first batch
// that draws with it (B9: cold init is dominated by compilation), and its uniform locations are
// resolved once then. A compile or link failure is a typed error the backend reports (BQ-52).
import { PROGRAM } from "../scene/instance-layout.js";
import type { PaneUniforms } from "../viewport/transform.js";
import { GL, type GL2Like, type GLObject } from "./gl-types.js";
import type { GlRegistry, Handle } from "./registry.js";
import { BAR_CELL } from "./shaders/bar-cell-stub.js";
import { LINE } from "./shaders/line.js";
import { QUAD } from "./shaders/quad.js";
import { SDF_TEXT } from "./shaders/sdf-text.js";

export const ENGINE_SHADER_COMPILE_FAILED = "ENGINE_SHADER_COMPILE_FAILED";
/** BQ-52: the driver's info log is trimmed to this many characters in `message`. */
export const INFO_LOG_MAX = 512;

export interface ProgramSource {
  readonly name: string;
  readonly vertex: string;
  readonly fragment: string;
  readonly uniforms: readonly string[];
}

/** A null object or a false status on a lost context: the loss path, never a compile failure. */
export class ContextLostError extends Error {
  constructor() {
    super("chart-engine: the WebGL2 context is lost");
  }
}

/** A batch's `program` number (shared with the 2D backend, BQ-87) indexes this table. */
export const PROGRAMS: readonly ProgramSource[] = [LINE, QUAD, SDF_TEXT, BAR_CELL];
export { PROGRAM };

/** A compile or link failure; `log` is the driver's info log (trimmed in the backend's message). */
export class ProgramCompileError extends Error {
  constructor(
    readonly program: string,
    readonly log: string,
  ) {
    super(`chart-engine: program "${program}" failed to compile or link`);
  }
}

export interface LinkedProgram {
  readonly handle: Handle<"program">;
  /** Uniform name to location, resolved once at link time. */
  readonly uniforms: Readonly<Record<string, unknown>>;
}

export class ProgramCache {
  /** The compile count and `engine.gl.program_compile_ms`. */
  readonly stats = { compiles: 0, compileMs: 0 };
  private readonly linked: (LinkedProgram | undefined)[] = [];

  constructor(
    private readonly gl: GL2Like,
    private readonly registry: GlRegistry,
    private readonly now: () => number = () => 0,
    private readonly sources: readonly ProgramSource[] = PROGRAMS,
  ) {}

  /** The linked program `id`, compiling it on first use; throws `ProgramCompileError`. */
  use(id: number): LinkedProgram {
    return (this.linked[id] ??= this.compile(id));
  }

  /** Forgets every linked program (its handle freed) and returns their ids, to relink on restore. */
  forget(): number[] {
    const ids: number[] = [];
    this.linked.forEach((p, id) => {
      if (p === undefined) return;
      this.registry.release(p.handle);
      ids.push(id);
    });
    this.linked.length = 0;
    return ids;
  }

  /** Makes `id` the current program. */
  bind(id: number): void {
    this.gl.useProgram(this.registry.get(this.use(id).handle));
  }

  /** Writes a pane's block into the current program `id`: only the uniforms it declares. */
  setUniforms(id: number, block: PaneUniforms): void {
    const u = this.use(id).uniforms;
    const { ints: i, floats: f } = block;
    // No per-frame closure (31-chart-engine): the four locations are read and tested inline.
    const ib = u["u_indexBase"];
    const tb = u["u_tickBase"];
    const k = u["u_k"];
    const vp = u["u_viewport"];
    if (ib !== undefined && ib !== null) this.gl.uniform1i(ib, i[0] ?? 0);
    if (tb !== undefined && tb !== null) this.gl.uniform1i(tb, i[1] ?? 0);
    if (k !== undefined && k !== null)
      this.gl.uniform4f(k, f[0] ?? 0, f[1] ?? 0, f[2] ?? 0, f[3] ?? 0);
    if (vp !== undefined && vp !== null) this.gl.uniform2f(vp, f[4] ?? 0, f[5] ?? 0);
  }

  private compile(id: number): LinkedProgram {
    const src = this.sources[id];
    if (src === undefined) throw new ProgramCompileError(`#${id}`, "no such program");
    const start = this.now();
    const handle = this.registry.create("program");
    const shaders: GLObject[] = [];
    // m2: a lost context answers null and false everywhere; that is the loss path (BQ-49).
    const fail = (log: string): Error =>
      this.gl.isContextLost() ? new ContextLostError() : new ProgramCompileError(src.name, log);
    try {
      const program = this.registry.get(handle);
      if (program === null) throw fail("no program object");
      for (const [type, text] of [
        [GL.VERTEX_SHADER, src.vertex],
        [GL.FRAGMENT_SHADER, src.fragment],
      ] as const) {
        const shader = this.gl.createShader(type);
        if (shader === null) throw fail("no shader object");
        shaders.push(shader);
        this.gl.shaderSource(shader, text);
        this.gl.compileShader(shader);
        if (this.gl.getShaderParameter(shader, GL.COMPILE_STATUS) !== true) {
          throw fail(this.gl.getShaderInfoLog(shader) ?? "");
        }
        this.gl.attachShader(program, shader);
      }
      this.gl.linkProgram(program);
      if (this.gl.getProgramParameter(program, GL.LINK_STATUS) !== true) {
        throw fail(this.gl.getProgramInfoLog(program) ?? "");
      }
      const uniforms: Record<string, unknown> = {};
      for (const name of src.uniforms) uniforms[name] = this.gl.getUniformLocation(program, name);
      return { handle, uniforms };
    } catch (e) {
      this.registry.release(handle);
      throw e;
    } finally {
      for (const shader of shaders) this.gl.deleteShader(shader);
      this.stats.compiles += 1;
      this.stats.compileMs += this.now() - start;
    }
  }
}
