// THROWAWAY SPIKE HARNESS (E11-K01, BQ-179/184/185). WebGL2 (SwiftShader in headless Chromium) draws every
// mono glyph from the atlas with §3.7's `fwidth` band and with the shipped fixed 0.45–0.55 band, next to
// native `fillText` at the same device size; per-glyph SSIM and confusable-pair separation are computed.
const VS = `#version 300 es
in vec2 a_corner; in vec4 a_rect; in vec4 a_uv; uniform vec2 u_vp; out vec2 v_uv;
void main() { v_uv = a_uv.xy + a_corner * a_uv.zw; vec2 p = (a_rect.xy + a_corner * a_rect.zw) / u_vp;
  gl_Position = vec4(p.x * 2.0 - 1.0, 1.0 - p.y * 2.0, 0.0, 1.0); }`;
const FS = (band) => `#version 300 es
precision mediump float; uniform sampler2D u_atlas; in vec2 v_uv; out vec4 o;
void main() { float d = texture(u_atlas, v_uv).r; ${band} o = vec4(a, a, a, 1.0); }`;
const BANDS = {
  fwidth: "float w = fwidth(d); float a = smoothstep(0.5 - w, 0.5 + w, d);",
  fixed: "float a = smoothstep(0.45, 0.55, d);",
};

function glSetup(atlas, size) {
  const cv = document.createElement("canvas");
  const gl = cv.getContext("webgl2", { antialias: false, preserveDrawingBuffer: true });
  const progs = {};
  for (const [k, band] of Object.entries(BANDS)) {
    const p = gl.createProgram();
    for (const [t, src] of [
      [gl.VERTEX_SHADER, VS],
      [gl.FRAGMENT_SHADER, FS(band)],
    ]) {
      const s = gl.createShader(t);
      gl.shaderSource(s, src);
      gl.compileShader(s);
      if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s));
      gl.attachShader(p, s);
    }
    gl.linkProgram(p);
    progs[k] = p;
  }
  gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1);
  const tex = gl.createTexture();
  gl.bindTexture(gl.TEXTURE_2D, tex);
  gl.texImage2D(
    gl.TEXTURE_2D,
    0,
    gl.R8,
    size,
    size,
    0,
    gl.RED,
    gl.UNSIGNED_BYTE,
    new Uint8Array(atlas),
  );
  for (const [k, v] of [
    [gl.TEXTURE_MIN_FILTER, gl.LINEAR],
    [gl.TEXTURE_MAG_FILTER, gl.LINEAR],
  ])
    gl.texParameteri(gl.TEXTURE_2D, k, v);
  const vao = gl.createVertexArray();
  gl.bindVertexArray(vao);
  const quad = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, quad);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([0, 0, 1, 0, 0, 1, 1, 1]), gl.STATIC_DRAW);
  const inst = gl.createBuffer();
  return { cv, gl, progs, quad, inst, vao };
}

function drawSdf(g, prog, items, size, W, H) {
  const { gl, cv } = g;
  [cv.width, cv.height] = [W, H];
  gl.viewport(0, 0, W, H);
  gl.clearColor(0, 0, 0, 1);
  gl.clear(gl.COLOR_BUFFER_BIT);
  gl.useProgram(prog);
  const data = new Float32Array(items.length * 8);
  items.forEach(({ m, x, y, s }, i) =>
    data.set(
      [
        x + m.ox * s,
        y + m.oy * s,
        m.w * s,
        m.h * s,
        m.x / size,
        m.y / size,
        m.w / size,
        m.h / size,
      ],
      i * 8,
    ),
  );
  gl.bindBuffer(gl.ARRAY_BUFFER, g.quad);
  const loc = (n) => gl.getAttribLocation(prog, n);
  gl.enableVertexAttribArray(loc("a_corner"));
  gl.vertexAttribPointer(loc("a_corner"), 2, gl.FLOAT, false, 0, 0);
  gl.bindBuffer(gl.ARRAY_BUFFER, g.inst);
  gl.bufferData(gl.ARRAY_BUFFER, data, gl.STREAM_DRAW);
  for (const [n, off] of [
    ["a_rect", 0],
    ["a_uv", 16],
  ]) {
    gl.enableVertexAttribArray(loc(n));
    gl.vertexAttribPointer(loc(n), 4, gl.FLOAT, false, 32, off);
    gl.vertexAttribDivisor(loc(n), 1);
  }
  gl.uniform2f(gl.getUniformLocation(prog, "u_vp"), W, H);
  gl.enable(gl.BLEND);
  gl.blendFunc(gl.ONE, gl.ONE); // glyph boxes may overlap their neighbours' padding; ink adds
  gl.drawArraysInstanced(gl.TRIANGLE_STRIP, 0, 4, items.length);
  const px = new Uint8Array(W * H * 4);
  gl.readPixels(0, 0, W, H, gl.RGBA, gl.UNSIGNED_BYTE, px);
  const out = new Uint8Array(W * H);
  for (let y = 0; y < H; y += 1)
    for (let x = 0; x < W; x += 1) out[y * W + x] = px[((H - 1 - y) * W + x) * 4];
  return out;
}

function drawNative(font, items, W, H) {
  const cv = new OffscreenCanvas(W, H);
  const ctx = cv.getContext("2d", { willReadFrequently: true });
  ctx.fillStyle = "#000";
  ctx.fillRect(0, 0, W, H);
  ctx.fillStyle = "#fff";
  ctx.font = font;
  for (const { ch, x, y } of items) ctx.fillText(ch, x, y);
  const d = ctx.getImageData(0, 0, W, H).data;
  return Uint8Array.from({ length: W * H }, (_, i) => d[i * 4]);
}

const cellOf = (img, W, c) => {
  const out = [];
  for (let y = c.y; y < c.y + c.h; y += 1)
    for (let x = c.x; x < c.x + c.w; x += 1) out.push(img[y * W + x]);
  return out;
};
function ssim(a, b) {
  const n = a.length;
  const ma = a.reduce((s, v) => s + v, 0) / n;
  const mb = b.reduce((s, v) => s + v, 0) / n;
  let [va, vb, cov] = [0, 0, 0];
  for (let i = 0; i < n; i += 1) {
    va += (a[i] - ma) ** 2;
    vb += (b[i] - mb) ** 2;
    cov += (a[i] - ma) * (b[i] - mb);
  }
  [va, vb, cov] = [va / (n - 1), vb / (n - 1), cov / (n - 1)];
  const [c1, c2] = [(0.01 * 255) ** 2, (0.03 * 255) ** 2];
  return ((2 * ma * mb + c1) * (2 * cov + c2)) / ((ma * ma + mb * mb + c1) * (va + vb + c2));
}
const mad = (a, b) => a.reduce((s, v, i) => s + Math.abs(v - b[i]), 0) / a.length;
const q = (xs, p) => [...xs].sort((a, b) => a - b)[Math.floor(p * (xs.length - 1))];

function toPng(strips) {
  const W = Math.max(...strips.map((s) => s.W));
  const H = strips.reduce((s, x) => s + x.H, 0);
  const cv = document.createElement("canvas");
  [cv.width, cv.height] = [W, H];
  const ctx = cv.getContext("2d");
  let y0 = 0;
  for (const s of strips) {
    const id = ctx.createImageData(s.W, s.H);
    s.img.forEach((v, i) => id.data.set([v, v, v, 255], i * 4));
    ctx.putImageData(id, 0, y0);
    y0 += s.H;
  }
  return cv.toDataURL("image/png");
}

/** @returns per case { px, dpr, band -> { ssimMin, ssimP10, ssimMedian, worst, pairs } } plus PNG data URLs. */
export async function legibility({ keep, size, font, cases, pairs, sample, cellSet, images }) {
  const face = new FontFace(font.family, await (await fetch(font.url)).arrayBuffer(), {
    weight: String(font.weight),
  });
  document.fonts.add(face);
  await face.load();
  const { texture: atlas, metrics } = window.kept[keep];
  const g = glSetup(atlas, size);
  const byCh = new Map(metrics.filter((m) => m.font === 0).map((m) => [m.ch, m]));
  const list = [...font.glyphs].filter((ch) => byCh.get(ch)?.w > 0);
  const results = [];
  const pngs = {};
  for (const { px, dpr } of cases) {
    const dev = px * dpr;
    const s = dev / font.rasterPx;
    const [cw, chH, base] = [
      Math.ceil(dev * 0.75) + 4,
      Math.ceil(dev * 1.5) + 4,
      Math.ceil(dev * 1.15) + 2,
    ];
    const cols = 16;
    const W = cols * cw;
    const H = Math.ceil(list.length / cols) * chH;
    const items = list.map((ch, i) => ({
      ch,
      m: byCh.get(ch),
      s,
      x: (i % cols) * cw + 2,
      y: Math.floor(i / cols) * chH + base,
    }));
    const cells = new Map(
      list.map((ch, i) => [
        ch,
        { x: (i % cols) * cw, y: Math.floor(i / cols) * chH, w: cw, h: chH },
      ]),
    );
    const fontCss = `${font.weight} ${dev}px "${font.family}"`;
    const native = drawNative(fontCss, items, W, H);
    const row = { px, dpr, devicePx: dev };
    for (const [band, prog] of Object.entries(g.progs)) {
      const img = drawSdf(g, prog, items, size, W, H);
      const ss = list.map((ch) => [
        ch,
        ssim(cellOf(img, W, cells.get(ch)), cellOf(native, W, cells.get(ch))),
      ]);
      const vals = ss.map((x) => x[1]);
      const pairRows = pairs.map(([a, b]) => {
        const sd = mad(cellOf(img, W, cells.get(a)), cellOf(img, W, cells.get(b)));
        const nd = mad(cellOf(native, W, cells.get(a)), cellOf(native, W, cells.get(b)));
        return {
          pair: a + b,
          sdf: +sd.toFixed(2),
          native: +nd.toFixed(2),
          ratio: +(sd / nd).toFixed(3),
        };
      });
      row[band] = {
        ssimMin: +Math.min(...vals).toFixed(3),
        ssimP10: +q(vals, 0.1).toFixed(3),
        ssimMedian: +q(vals, 0.5).toFixed(3),
        cellSsimMin: +Math.min(...ss.filter(([c]) => cellSet.includes(c)).map((x) => x[1])).toFixed(
          3,
        ),
        cellSsimMedian: +q(
          ss.filter(([c]) => cellSet.includes(c)).map((x) => x[1]),
          0.5,
        ).toFixed(3),
        worst: ss
          .sort((a, b) => a[1] - b[1])
          .slice(0, 5)
          .map(([c, v]) => `${c}:${v.toFixed(2)}`),
        pairRatioMin: Math.min(...pairRows.map((p) => p.ratio)),
        pairs: pairRows,
      };
    }
    results.push(row);
    if (images) {
      const advance = [...sample].reduce((w, ch) => w + (byCh.get(ch)?.advance ?? 0) * s, 0);
      const [SW, SH, sb] = [
        Math.ceil(advance) + 8,
        Math.ceil(dev * 1.6) + 4,
        Math.ceil(dev * 1.2) + 2,
      ];
      let pen = 4;
      const line = [...sample].map((ch) => {
        const it = { ch, m: byCh.get(ch), s, x: pen, y: sb };
        pen += it.m.advance * s;
        return it;
      });
      const strips = [{ W: SW, H: SH, img: drawNative(fontCss, line, SW, SH) }];
      for (const prog of Object.values(g.progs))
        strips.push({
          W: SW,
          H: SH,
          img: drawSdf(
            g,
            prog,
            line.filter((l) => l.m.w > 0),
            size,
            SW,
            SH,
          ),
        });
      (pngs[dpr] ??= []).push(...strips);
    }
  }
  // BQ-185: ink extent of the cell-text glyphs at each class px (dpr 1), plus a 1 px outline on each side.
  const cv = new OffscreenCanvas(8, 8).getContext("2d");
  const ink = [10, 11, 13].map((px) => {
    cv.font = `${font.weight} ${px}px "${font.family}"`;
    const h = (t) => {
      const m = cv.measureText(t);
      return +(m.actualBoundingBoxAscent + m.actualBoundingBoxDescent).toFixed(2);
    };
    const [cellInk, digitInk] = [h(cellSet), h("0123456789.,-+")];
    return {
      px,
      cellInkPx: cellInk,
      digitInkPx: digitInk,
      minCellWithOutlinePx: Math.ceil(cellInk) + 2,
    };
  });
  const png = Object.fromEntries(Object.entries(pngs).map(([d, st]) => [d, toPng(st)]));
  return { results, ink, png };
}
