// THROWAWAY SPIKE HARNESS (E15-K01 #371). The order-flow proxy pane (BQ-13): a stand-in for a footprint /
// DOM-heatmap pane, the same shape as the bench's B3/B4 GL load (8 instanced draws of 2,500 quads and a 512-row
// heatmap column uploaded every 100 ms), written here, not imported (BQ-02 ruling). An ESTIMATE: no footprint or
// DOM layer exists yet; re-measured when they ship. It does not wait for the GPU itself: the measured loop
// flushes every context and reads one pixel back (scene.mjs `runLoop`).
const QUADS = 2500;
const TEX_W = 2048;
const TEX_H = 512;
const VS = `#version 300 es
in vec4 inst; uniform float t;
void main(){
  vec2 c = vec2(float(gl_VertexID & 1), float((gl_VertexID >> 1) & 1));
  vec2 p = inst.xy + c * 0.004 + vec2(sin(t + inst.z) * 0.001, 0.0);
  gl_Position = vec4(p * 2.0 - 1.0, 0.0, 1.0);
}`;
const FS = `#version 300 es
precision mediump float; out vec4 o; void main(){ o = vec4(0.2, 0.6, 0.9, 0.5); }`;

export class ProxyLoad {
  constructor(canvas) {
    const gl = canvas.getContext("webgl2", {
      antialias: false,
      powerPreference: "high-performance",
    });
    if (!gl) throw new Error("webgl2 unavailable");
    this.gl = gl;
    const prog = gl.createProgram();
    for (const [type, src] of [
      [gl.VERTEX_SHADER, VS],
      [gl.FRAGMENT_SHADER, FS],
    ]) {
      const s = gl.createShader(type);
      gl.shaderSource(s, src);
      gl.compileShader(s);
      if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s));
      gl.attachShader(prog, s);
    }
    gl.linkProgram(prog);
    gl.useProgram(prog);
    this.tLoc = gl.getUniformLocation(prog, "t");
    const inst = new Float32Array(QUADS * 4);
    for (let i = 0; i < inst.length; i += 1) inst[i] = ((i * 2654435761) >>> 0) / 4294967296; // deterministic
    gl.bindBuffer(gl.ARRAY_BUFFER, gl.createBuffer());
    gl.bufferData(gl.ARRAY_BUFFER, inst, gl.STATIC_DRAW);
    const loc = gl.getAttribLocation(prog, "inst");
    gl.enableVertexAttribArray(loc);
    gl.vertexAttribPointer(loc, 4, gl.FLOAT, false, 0, 0);
    gl.vertexAttribDivisor(loc, 1);
    this.tex = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, this.tex);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.R8, TEX_W, TEX_H, 0, gl.RED, gl.UNSIGNED_BYTE, null);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
    gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1);
    gl.enable(gl.BLEND);
    gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
    this.column = new Uint8Array(TEX_H);
    this.col = 0;
  }

  /** One heatmap column (512 bytes) into the ring texture. */
  uploadColumn() {
    const { gl } = this;
    for (let i = 0; i < TEX_H; i += 1) this.column[i] = (i * 31 + this.col) & 0xff;
    gl.texSubImage2D(
      gl.TEXTURE_2D,
      0,
      this.col % TEX_W,
      0,
      1,
      TEX_H,
      gl.RED,
      gl.UNSIGNED_BYTE,
      this.column,
    );
    this.col += 1;
  }

  /** `drawCalls` instanced draws of 2,500 quads; does not wait for the GPU. */
  draw(drawCalls, tSec) {
    const { gl } = this;
    gl.clearColor(0.04, 0.05, 0.07, 1);
    gl.clear(gl.COLOR_BUFFER_BIT);
    gl.uniform1f(this.tLoc, tSec);
    for (let d = 0; d < drawCalls; d += 1) gl.drawArraysInstanced(gl.TRIANGLE_STRIP, 0, 4, QUADS);
  }
}
