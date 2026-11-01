// THROWAWAY SPIKE HARNESS (E15-K01 #371). The stand-in pane scene (BQ-02 option b, BQ-13): real WebGL2
// instanced draws of the shape the engine will issue, one canvas and one context per pane (BQ-05). It runs
// unchanged on the main thread (inline row) or in the render worker (headline). The 100k-bar series comes from
// lib.mjs's generator (seed 20260928), which mirrors the bench's fixture shape; nothing is imported from the
// engine package (BQ-02 ruling). Nothing here is product code.
import { generateBars } from "./lib.mjs";
import { ProxyLoad } from "./load.mjs";

export const SEED = 20260928;
export const BAR_PX = 6; // 6 px per bar: the visible window follows the pane width
export const DRAWINGS = 200;

// One program for every mark: a quad from p0 to p1, `w` px wide (bodies, wicks, lines, bars, drawings).
const VS = `#version 300 es
in vec4 seg; uniform vec2 px; uniform float w;
void main(){
  int v = gl_VertexID; vec2 a = seg.xy, b = seg.zw; vec2 d = b - a;
  vec2 n = length(d * px) > 0.0 ? normalize(vec2(-d.y * px.y, d.x * px.x)) : vec2(1.0, 0.0);
  vec2 p = ((v & 1) == 0 ? a : b) + n / px * w * (((v >> 1) & 1) == 0 ? -0.5 : 0.5);
  gl_Position = vec4(p * 2.0 - 1.0, 0.0, 1.0);
}`;
const FS = `#version 300 es
precision mediump float; uniform vec4 col; out vec4 o; void main(){ o = col; }`;

/** The seeded series and the R1-stack stand-in indicators, computed once per thread. */
export function makeData() {
  const bars = generateBars({ seed: SEED, count: 100_000 });
  const n = bars.length;
  const o = new Float64Array(n),
    h = new Float64Array(n),
    l = new Float64Array(n);
  const c = new Float64Array(n),
    v = new Float64Array(n),
    t = new Float64Array(n);
  bars.forEach(
    (b, i) => (
      (o[i] = b.o),
      (h[i] = b.h),
      (l[i] = b.l),
      (c[i] = b.c),
      (v[i] = b.v),
      (t[i] = b.tOpenMs)
    ),
  );
  const ema = (src, len) => {
    const out = new Float64Array(n),
      k = 2 / (len + 1);
    out[0] = src[0];
    for (let i = 1; i < n; i += 1) out[i] = src[i] * k + out[i - 1] * (1 - k);
    return out;
  };
  const sma = (src, len) => {
    const out = new Float64Array(n);
    let s = 0;
    for (let i = 0; i < n; i += 1)
      ((s += src[i] - (i >= len ? src[i - len] : 0)), (out[i] = s / Math.min(i + 1, len)));
    return out;
  };
  const sd = (len, mid) => {
    const out = new Float64Array(n);
    for (let i = 0; i < n; i += 1) {
      let s = 0;
      for (let j = Math.max(0, i - len + 1); j <= i; j += 1) s += (c[j] - mid[i]) ** 2;
      out[i] = Math.sqrt(s / len);
    }
    return out;
  };
  const mid = sma(c, 20),
    dev = sd(20, mid);
  const tr = new Float64Array(n),
    obv = new Float64Array(n),
    vw = new Float64Array(n);
  let pv = 0,
    vv = 0;
  for (let i = 0; i < n; i += 1) {
    tr[i] = i
      ? Math.max(h[i] - l[i], Math.abs(h[i] - c[i - 1]), Math.abs(l[i] - c[i - 1]))
      : h[i] - l[i];
    obv[i] = (i ? obv[i - 1] : 0) + (i && c[i] < c[i - 1] ? -v[i] : v[i]);
    if (i % 1440 === 0) pv = vv = 0; // session VWAP
    pv += ((h[i] + l[i] + c[i]) / 3) * v[i];
    vv += v[i];
    vw[i] = pv / vv;
  }
  const up = new Float64Array(n),
    dn = new Float64Array(n),
    rsiUp = new Float64Array(n),
    rsiDn = new Float64Array(n);
  for (let i = 1; i < n; i += 1)
    ((rsiUp[i] = Math.max(0, c[i] - c[i - 1])), (rsiDn[i] = Math.max(0, c[i - 1] - c[i])));
  const au = ema(rsiUp, 27),
    ad = ema(rsiDn, 27),
    rsi = new Float64Array(n);
  for (let i = 0; i < n; i += 1)
    ((up[i] = mid[i] + 2 * dev[i]),
      (dn[i] = mid[i] - 2 * dev[i]),
      (rsi[i] = 100 - 100 / (1 + au[i] / (ad[i] || 1))));
  const ema26 = ema(c, 26);
  const macd = ema(c, 12).map((x, i) => x - ema26[i]);
  const stochK = new Float64Array(n);
  for (let i = 0; i < n; i += 1) {
    let lo = Infinity,
      hi = -Infinity;
    for (let j = Math.max(0, i - 13); j <= i; j += 1)
      ((lo = Math.min(lo, l[j])), (hi = Math.max(hi, h[j])));
    stochK[i] = hi > lo ? (100 * (c[i] - lo)) / (hi - lo) : 50;
  }
  // R1 stand-in (E13 v1 set): 7 overlay lines and 4 sub-panes (volume + MA, RSI, MACD + signal + histogram, Stoch).
  const overlays = [sma(c, 20), ema(c, 50), ema(c, 200), vw, up, mid, dn];
  const signal = ema(macd, 9),
    hist = macd.map((x, i) => x - signal[i]);
  const subs = [
    { lines: [sma(v, 20)], hist: v },
    { lines: [rsi], hist: null },
    { lines: [macd, signal], hist },
    { lines: [stochK, sma(stochK, 3), ema(tr, 14), sma(obv, 50)], hist: null },
  ];
  return { n, o, h, l, c, t, overlays, subs };
}

/** The drawings fixture: 200 two-anchor trend lines over the series, seeded. */
export function makeDrawings(data, rand) {
  const out = new Float64Array(DRAWINGS * 4);
  for (let k = 0; k < DRAWINGS; k += 1) {
    const i0 = Math.floor(rand() * (data.n - 600)),
      i1 = i0 + 20 + Math.floor(rand() * 500);
    out.set([i0, data.c[i0], i1, data.c[i1]], k * 4);
  }
  return out;
}

const put = (f, k, a, b, c, d) => (
  (f[k * 4] = a),
  (f[k * 4 + 1] = b),
  (f[k * 4 + 2] = c),
  (f[k * 4 + 3] = d)
);
const px1 = new Uint8Array(4);

export class Pane {
  // `canvas` is the pane's own canvas (one context per pane), or `{ gl, rect }`: a region of one shared
  // context (one canvas for every pane, a viewport and scissor per pane; the shared-context topology).
  constructor(canvas, density, data, drawings, phase) {
    this.density = density;
    this.data = data;
    this.drawings = drawings;
    this.start = 1000 + phase * 7919; // each pane pans its own window of the same series
    if (density === "orderflow-proxy") {
      this.proxy = new ProxyLoad(canvas); // the B3/B4-shaped stand-in (load.mjs; BQ-13 proxy row)
      return;
    }
    const gl =
      canvas.gl ??
      canvas.getContext("webgl2", { antialias: false, powerPreference: "high-performance" });
    if (!gl) throw new Error("webgl2 unavailable");
    this.gl = gl;
    this.rect = canvas.rect ?? { x: 0, y: 0, w: canvas.width, h: canvas.height };
    this.w = this.rect.w;
    this.h = this.rect.h;
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
    this.prog = prog;
    this.u = {
      px: gl.getUniformLocation(prog, "px"),
      w: gl.getUniformLocation(prog, "w"),
      col: gl.getUniformLocation(prog, "col"),
    };
    this.vis = Math.max(20, Math.floor(this.w / BAR_PX));
    this.buf = new Float32Array(Math.max(this.vis * 4, DRAWINGS * 4, 64)); // reused every frame (no per-frame allocation)
    // one buffer per draw slot, as the engine keeps one per series: re-filling a buffer a pending draw still
    // reads would serialise the draws (a stand-in artefact the smoke run showed on SwiftShader)
    this.loc = gl.getAttribLocation(prog, "seg");
    this.vbos = [];
    gl.enableVertexAttribArray(this.loc);
    gl.vertexAttribDivisor(this.loc, 1);
    gl.enable(gl.BLEND);
    gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
  }

  // one instanced draw of `count` segments from this.buf, in the region [y0, y1] of the pane
  seg(count, width, r, g, b, a) {
    const { gl } = this;
    if (this.draws === this.vbos.length) {
      const b = gl.createBuffer();
      gl.bindBuffer(gl.ARRAY_BUFFER, b);
      gl.bufferData(gl.ARRAY_BUFFER, this.buf.byteLength, gl.DYNAMIC_DRAW);
      this.vbos.push(b);
    }
    gl.bindBuffer(gl.ARRAY_BUFFER, this.vbos[this.draws]);
    gl.bufferSubData(gl.ARRAY_BUFFER, 0, this.buf, 0, count * 4);
    gl.vertexAttribPointer(this.loc, 4, gl.FLOAT, false, 0, 0);
    gl.uniform1f(this.u.w, width);
    gl.uniform4f(this.u.col, r, g, b, a);
    gl.drawArraysInstanced(gl.TRIANGLE_STRIP, 0, 4, count);
    this.draws += 1;
    this.bytes += count * 16;
  }

  line(src, i0, lo, hi, y0, y1, r, g, b) {
    const n = this.vis,
      f = this.buf,
      span = hi - lo || 1,
      bw = 1 / n;
    for (let k = 0; k < n - 1; k += 1) {
      f[k * 4] = (k + 0.5) * bw;
      f[k * 4 + 1] = y0 + ((src[i0 + k] - lo) / span) * (y1 - y0);
      f[k * 4 + 2] = (k + 1.5) * bw;
      f[k * 4 + 3] = y0 + ((src[i0 + k + 1] - lo) / span) * (y1 - y0);
    }
    this.seg(n - 1, 1.5, r, g, b, 1);
  }

  /** Renders one frame (does not wait for the GPU); returns nothing, counters on `this`. */
  frame(i) {
    this.draws = 0;
    this.bytes = 0;
    if (this.proxy) {
      if (i % 6 === 0) this.proxy.uploadColumn(); // 100 ms heatmap cadence at 60 Hz
      this.proxy.draw(8, i / 60);
      this.draws = 8;
      return;
    }
    const { gl, data, vis } = this;
    const i0 = (this.start + i) % (data.n - vis - 1);
    const { x, y: ry, w, h } = this.rect;
    gl.useProgram(this.prog);
    gl.viewport(x, ry, w, h);
    gl.enable(gl.SCISSOR_TEST);
    gl.scissor(x, ry, w, h);
    gl.uniform2f(this.u.px, this.w, this.h);
    gl.clearColor(0.04, 0.05, 0.07, 1);
    gl.clear(gl.COLOR_BUFFER_BIT);
    const withInd = this.density !== "bare";
    const top = withInd ? 0.45 : 0.05; // the price pane above, four sub-panes below
    let lo = Infinity,
      hi = -Infinity;
    for (let k = 0; k < vis; k += 1)
      ((lo = Math.min(lo, data.l[i0 + k])), (hi = Math.max(hi, data.h[i0 + k])));
    const y = (p) => top + ((p - lo) / (hi - lo || 1)) * (0.97 - top);
    const f = this.buf,
      bw = 1 / vis;
    for (let g = 0; g < 8; g += 1)
      put(f, g, 0, top + (g / 8) * (0.97 - top), 1, top + (g / 8) * (0.97 - top));
    this.seg(8, 1, 0.2, 0.22, 0.25, 1); // grid
    for (let k = 0; k < vis; k += 1)
      put(f, k, (k + 0.5) * bw, y(data.l[i0 + k]), (k + 0.5) * bw, y(data.h[i0 + k]));
    this.seg(vis, 1, 0.6, 0.6, 0.6, 1); // wicks
    for (let k = 0; k < vis; k += 1)
      put(f, k, (k + 0.5) * bw, y(data.o[i0 + k]), (k + 0.5) * bw, y(data.c[i0 + k]) + 1e-4);
    this.seg(vis, BAR_PX - 2, 0.15, 0.7, 0.5, 1); // bodies (one colour: the stand-in does not split up/down)
    if (withInd) {
      for (const s of data.overlays) this.line(s, i0, lo, hi, top, 0.97, 0.9, 0.7, 0.2);
      data.subs.forEach((sub, j) => {
        const y0 = 0.02 + j * 0.105,
          y1 = y0 + 0.095;
        let a = Infinity,
          b = -Infinity;
        for (const s of [...sub.lines, ...(sub.hist ? [sub.hist] : [])])
          for (let k = 0; k < vis; k += 1)
            ((a = Math.min(a, s[i0 + k])), (b = Math.max(b, s[i0 + k])));
        if (sub.hist) {
          const z = y0 + Math.min(1, Math.max(0, -a / (b - a || 1))) * (y1 - y0); // the zero line
          for (let k = 0; k < vis; k += 1)
            put(
              f,
              k,
              (k + 0.5) * bw,
              z,
              (k + 0.5) * bw,
              y0 + ((sub.hist[i0 + k] - a) / (b - a || 1)) * (y1 - y0),
            );
          this.seg(vis, BAR_PX - 2, 0.3, 0.4, 0.6, 0.8);
        }
        for (const s of sub.lines) this.line(s, i0, a, b, y0, y1, 0.5, 0.8, 0.9);
      });
    }
    if (this.density === "drawings") {
      const d = this.drawings,
        xw = (idx) => (idx - i0 + 0.5) * bw;
      for (let k = 0; k < DRAWINGS; k += 1)
        put(f, k, xw(d[k * 4]), y(d[k * 4 + 1]), xw(d[k * 4 + 2]), y(d[k * 4 + 3]));
      this.seg(DRAWINGS, 1.5, 0.9, 0.3, 0.9, 1); // every drawing transformed and submitted (no culling, conservative)
    }
  }

  // A 1x1 readPixels: a full round trip that returns only when the GPU process has executed the frame's
  // commands. gl.finish() does not wait in Chromium (measured in the smoke run: 0.2 ms for 16 panes). With
  // one context per pane, every context is flushed and only the last is read back (the GPU process runs the
  // flushed streams in order), so N panes do not pay N round trips.
  finish() {
    const gl = this.proxy ? this.proxy.gl : this.gl;
    gl.readPixels(0, 0, 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, px1);
  }

  flush() {
    (this.proxy ? this.proxy.gl : this.gl).flush();
  }

  lost() {
    return (this.proxy ? this.proxy.gl : this.gl).isContextLost();
  }
}

/** Runs the measured loop over every pane: one frame = all panes submitted, then each context finished. */
export function runLoop(panes, finishing, { warmMs, windowMs, raf, now }, done) {
  const work = [],
    workAt = [],
    interval = [],
    submit = [],
    warm = [],
    warmAt = [];
  let i = 0,
    t0 = now(),
    last = t0,
    draws = 0,
    bytes = 0;
  const step = () => {
    const s = now();
    for (const p of panes) p.frame(i);
    const m = now();
    for (const p of panes) p.flush();
    for (const p of finishing) p.finish();
    const e = now();
    if (s - t0 < warmMs) {
      warm.push(e - s);
      warmAt.push(s - t0);
    } else {
      work.push(e - s);
      workAt.push(s - t0);
      submit.push(m - s);
      interval.push(s - last);
      draws = 0;
      bytes = 0;
      for (const p of panes) ((draws += p.draws), (bytes += p.bytes));
    }
    last = s;
    i += 1;
    if (e - t0 < warmMs + windowMs) raf(step);
    else
      done({
        work,
        workAt,
        interval,
        submit,
        warm,
        warmAt,
        drawsPerFrame: draws,
        bytesPerFrame: bytes,
        lost: panes.filter((p) => p.lost()).length,
      });
  };
  raf(step);
}
