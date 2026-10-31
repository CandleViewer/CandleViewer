// E11-X02 (CE-E03): ProgramCache hands a ProgramSource field to the GPU unchanged.
interface Gl {
  shaderSource(shader: object, source: string): void;
}
interface ProgramSource {
  vertex: string;
  fragment: string;
}
declare const theme: { precision: string };

export class ProgramCache {
  constructor(private readonly gl: Gl) {}

  compileOk(shader: object, src: ProgramSource): void {
    for (const text of [src.vertex, src.fragment]) {
      this.gl.shaderSource(shader, text); // ok: cv-engine-shader-source-dynamic
    }
  }

  compileBad(shader: object, src: ProgramSource): void {
    this.gl.shaderSource(shader, `precision ${theme.precision} float;\n` + src.fragment); // ruleid: cv-engine-shader-source-dynamic
    this.gl.shaderSource(shader, src.vertex.replace("#X", theme.precision)); // ruleid: cv-engine-shader-source-dynamic
  }
}
