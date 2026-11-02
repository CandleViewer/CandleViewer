// The WebGL2 surface the backend uses, hand-written (README BQ-48): src/gl compiles under
// tsconfig.core.json, which has no DOM lib, so `WebGL2RenderingContext` does not exist here. A
// real context fits `GL2Like` structurally; test/gl/fake-gl.ts implements it by hand (BQ-63).

/** An opaque GL object: a WebGLProgram, WebGLBuffer, WebGLTexture or WebGLVertexArrayObject. */
export type GLObject = object;

/** `WebGLContextAttributes`, the members the engine requests or records. */
export interface ContextAttributes {
  readonly alpha?: boolean;
  readonly antialias?: boolean;
  readonly depth?: boolean;
  readonly stencil?: boolean;
  readonly premultipliedAlpha?: boolean;
  readonly preserveDrawingBuffer?: boolean;
  readonly powerPreference?: string;
  readonly desynchronized?: boolean;
}

/** The WebGL2 members the backend calls; grows only with a caller (C-2.16: no DOM type). */
export interface GL2Like {
  getParameter(pname: number): unknown;
  getExtension(name: string): unknown;
  getContextAttributes(): ContextAttributes | null;
  getError(): number;
  isContextLost(): boolean;
  createProgram(): GLObject | null;
  deleteProgram(program: GLObject | null): void;
  createBuffer(): GLObject | null;
  deleteBuffer(buffer: GLObject | null): void;
  createTexture(): GLObject | null;
  deleteTexture(texture: GLObject | null): void;
  createVertexArray(): GLObject | null;
  deleteVertexArray(vao: GLObject | null): void;
  // Programs (program-cache.ts); shaders live only while their program links.
  createShader(type: number): GLObject | null;
  shaderSource(shader: GLObject, source: string): void;
  compileShader(shader: GLObject): void;
  getShaderParameter(shader: GLObject, pname: number): unknown;
  getShaderInfoLog(shader: GLObject): string | null;
  deleteShader(shader: GLObject | null): void;
  attachShader(program: GLObject, shader: GLObject): void;
  linkProgram(program: GLObject): void;
  getProgramParameter(program: GLObject, pname: number): unknown;
  getProgramInfoLog(program: GLObject): string | null;
  getUniformLocation(program: GLObject, name: string): unknown;
  useProgram(program: GLObject | null): void;
  // The pane uniform block (E11-S03, BQ-76): typed setters on the current program.
  uniform1i(location: unknown, x: number): void;
  uniform2f(location: unknown, x: number, y: number): void;
  uniform4f(location: unknown, x: number, y: number, z: number, w: number): void;
  // E12-S06: per-batch blocks (candle `u_batch`, `u_palette`) and int instance attributes.
  uniform4i(location: unknown, x: number, y: number, z: number, w: number): void;
  uniform4fv(location: unknown, data: Float32Array): void;
  enableVertexAttribArray(index: number): void;
  vertexAttribIPointer(
    index: number,
    size: number,
    type: number,
    stride: number,
    offset: number,
  ): void;
  vertexAttribDivisor(index: number, divisor: number): void;
  // Buffers, textures and submission.
  bindBuffer(target: number, buffer: GLObject | null): void;
  bufferData(target: number, data: ArrayBufferView, usage: number): void;
  bufferSubData(target: number, dst: number, src: ArrayBufferView, from: number, n: number): void;
  bindVertexArray(vao: GLObject | null): void;
  activeTexture(unit: number): void;
  bindTexture(target: number, texture: GLObject | null): void;
  texParameteri(target: number, pname: number, param: number): void;
  pixelStorei(pname: number, param: number): void;
  texImage2D(
    ...a: [number, number, number, number, number, number, number, number, ArrayBufferView | null]
  ): void;
  texSubImage2D(
    ...a: [number, number, number, number, number, number, number, number, ArrayBufferView]
  ): void;
  viewport(x: number, y: number, width: number, height: number): void;
  clearColor(r: number, g: number, b: number, a: number): void;
  clear(mask: number): void;
  drawArraysInstanced(mode: number, first: number, count: number, instances: number): void;
}

/** The numeric GL enums the backend reads (values from the WebGL 1/2 specifications). */
export const GL = {
  NO_ERROR: 0,
  MAX_TEXTURE_SIZE: 0x0d33,
  MAX_VERTEX_ATTRIBS: 0x8869,
  MAX_TEXTURE_IMAGE_UNITS: 0x8872,
  CONTEXT_LOST_WEBGL: 0x9242,
  /** `WEBGL_debug_renderer_info` only (ticket Security: shown in SCR-046 alone). */
  UNMASKED_RENDERER_WEBGL: 0x9246,
  VERTEX_SHADER: 0x8b31,
  FRAGMENT_SHADER: 0x8b30,
  COMPILE_STATUS: 0x8b81,
  LINK_STATUS: 0x8b82,
  ARRAY_BUFFER: 0x8892,
  DYNAMIC_DRAW: 0x88e8,
  TEXTURE_2D: 0x0de1,
  TEXTURE0: 0x84c0,
  TEXTURE_MIN_FILTER: 0x2801,
  TEXTURE_MAG_FILTER: 0x2800,
  LINEAR: 0x2601,
  TEXTURE_WRAP_S: 0x2802,
  TEXTURE_WRAP_T: 0x2803,
  CLAMP_TO_EDGE: 0x812f,
  RGBA: 0x1908,
  RGBA8: 0x8058,
  R8: 0x8229,
  RED: 0x1903,
  UNPACK_ALIGNMENT: 0x0cf5,
  UNSIGNED_BYTE: 0x1401,
  INT: 0x1404,
  TRIANGLE_STRIP: 0x0005,
  COLOR_BUFFER_BIT: 0x4000,
} as const;
