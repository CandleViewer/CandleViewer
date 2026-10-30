// The program cache (E11-S02, 26 §3.4): each program compiles and links lazily, on the first batch
// that draws with it (B9: cold init is dominated by compilation), and its uniform locations are
// resolved once then. A compile or link failure is a typed error the backend reports (BQ-52).
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

/** A batch's `program` number indexes this table: the state-sort key of 26 §3.1. */
export const PROGRAMS: readonly ProgramSource[] = [LINE, QUAD, SDF_TEXT, BAR_CELL];
export const PROGRAM = { line: 0, quad: 1, sdfText: 2, barCell: 3 } as const;

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

  /** Makes `id` the current program. */
  bind(id: number): void {
    this.gl.useProgram(this.registry.get(this.use(id).handle));
  }

  private compile(id: number): LinkedProgram {
    const src = this.sources[id];
    if (src === undefined) throw new ProgramCompileError(`#${id}`, "no such program");
    const start = this.now();
    const handle = this.registry.create("program");
    const shaders: GLObject[] = [];
    try {
      const program = this.registry.get(handle);
      if (program === null) throw new ProgramCompileError(src.name, "no program object");
      for (const [type, text] of [
        [GL.VERTEX_SHADER, src.vertex],
        [GL.FRAGMENT_SHADER, src.fragment],
      ] as const) {
        const shader = this.gl.createShader(type);
        if (shader === null) throw new ProgramCompileError(src.name, "no shader object");
        shaders.push(shader);
        this.gl.shaderSource(shader, text);
        this.gl.compileShader(shader);
        if (this.gl.getShaderParameter(shader, GL.COMPILE_STATUS) !== true) {
          throw new ProgramCompileError(src.name, this.gl.getShaderInfoLog(shader) ?? "");
        }
        this.gl.attachShader(program, shader);
      }
      this.gl.linkProgram(program);
      if (this.gl.getProgramParameter(program, GL.LINK_STATUS) !== true) {
        throw new ProgramCompileError(src.name, this.gl.getProgramInfoLog(program) ?? "");
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
