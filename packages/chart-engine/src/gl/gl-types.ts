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
} as const;
