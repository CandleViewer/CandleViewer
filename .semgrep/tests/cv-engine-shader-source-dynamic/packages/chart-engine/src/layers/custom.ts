// E11-X02 (CE-E03): a layer never compiles its own shader, even from a static string.
declare const gl: { shaderSource(shader: object, source: string): void };
declare const shader: object;
const FRAG = "void main() {}";

export function layerBad(): void {
  gl.shaderSource(shader, FRAG); // ruleid: cv-engine-shader-source-dynamic
}

export function layerOk(): string {
  return FRAG; // ok: cv-engine-shader-source-dynamic
}
