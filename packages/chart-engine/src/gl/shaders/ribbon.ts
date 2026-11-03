// `ribbon` (E12-S07 PR B, E12-D06 §3.2, §5.5): the line, area and baseline series, every part
// from one program over the series' `CandleRing` (BQ-1: no CPU projection, so a pan writes
// uniforms only). Static source only. Corners come from gl_VertexID (a 4-vertex strip). The
// instance is the ring's physical slot: `a_ohlc` / `a_meta` its bar, `a_next` / `a_nextMeta`
// the next slot (the +1 instance binding; the ring's guard slot mirrors slot 0, so the last
// slot reads in range). Bar i = (slot - head) & mask, its next bar is i + 1 on a wrapped ring
// too. `u_batch` = (part, head, mask, n), part as `RIBBON_PART`: 0 stroke, 1 join, 2 last disc,
// 3 area fill, 4 / 5 the baseline fills above / below B, 6 B's hairline. `u_base`: B (the last
// close for the disc). `u_geom[0]` = (stroke, join r, disc r, hairline) device px, `u_geom[1]`
// = (dpr, L2, plot right, spacing), `u_geom[2].x` the plot bottom (0: the canvas's). `u_palette` = line, area, above, below, base. Ints are subtracted
// before any float (BQ-75); y is the candle's `yOf`. Mirrors `src/layers/ribbon/geometry.ts`.
/**
 * The ring as the shader's `layout(location)` ints: a_ohlc at 0 and a_meta at 1 (this slot),
 * a_next at 2 and a_nextMeta at 3 (the next slot: the same words one stride on). The stride is
 * the CandleRing's 5 words (`CANDLE_STRIDE`; test/scene/instance-layout.test.ts pins both). An
 * `AttributeLayout` structurally: a type import of src/gl/buffers.ts here would close a cycle
 * through the program cache.
 */
export const RIBBON_ATTRIBUTES = {
  stride: 5,
  ints: [
    [0, 0, 4],
    [1, 4, 1],
    [2, 5, 4],
    [3, 9, 1],
  ],
} as const;

export const RIBBON = {
  name: "ribbon",
  uniforms: [
    "u_viewport",
    "u_indexBase",
    "u_tickBase",
    "u_k",
    "u_log",
    "u_batch",
    "u_geom",
    "u_palette",
    "u_base",
  ],
  vertex: `#version 300 es
layout(location = 0) in ivec4 a_ohlc;
layout(location = 1) in int a_meta;
layout(location = 2) in ivec4 a_next;
layout(location = 3) in int a_nextMeta;
uniform vec2 u_viewport;
uniform int u_indexBase;
uniform int u_tickBase;
uniform vec4 u_k;
uniform vec2 u_log;
uniform ivec4 u_batch;
uniform vec4 u_geom[3];
uniform vec4 u_palette[5];
uniform int u_base;
out vec4 v_color;
out vec2 v_local;
flat out float v_radius;
float yOf(int tick) {
  float t = float(tick - u_tickBase);
  float r = max(t * u_log.x, -0.999999);
  float series = r * (1.0 - r * (0.5 - r * (0.33333333 - r * 0.25)));
  float l = mix(log(1.0 + r), series, step(abs(r), 0.05));
  return mix(t, l, u_log.y) * u_k.y + u_k.z;
}
float xOf(int i) {
  float x = (float(i - u_indexBase) + 0.5 - u_k.w) * u_k.x;
  return u_geom[1].y > 0.5 ? floor(x) + 0.5 : x; // L2: the device-pixel column's centre
}
void main() {
  int part = u_batch.x;
  int n = u_batch.w;
  bool single = part == 2 || part == 6;
  int i = single ? n - 1 : (gl_InstanceID - u_batch.y) & u_batch.z;
  bool seg = part == 0 || (part >= 3 && part <= 5);
  vec2 corner = vec2(float(gl_VertexID & 1), float(gl_VertexID >> 1));
  v_radius = 0.0;
  v_local = vec2(0.0);
  // R-2: a segment into a gap_before bar (flags bit 0) is never drawn; nor one past the last bar.
  if (i < 0 || i >= n || (seg && (i + 1 >= n || (a_nextMeta & 1) != 0))) {
    gl_Position = vec4(2.0, 2.0, 0.0, 1.0);
    return;
  }
  int row = part <= 2 ? 0 : part - 2; // line, then area, above, below, base
  v_color = u_palette[row];
  float x0 = xOf(i);
  vec2 p;
  if (part == 1 || part == 2) {
    float r = part == 1 ? u_geom[0].y : u_geom[0].z;
    float m = r + 1.0;
    v_local = (corner * 2.0 - 1.0) * m;
    v_radius = r;
    p = vec2(x0, yOf(part == 2 ? u_base : a_ohlc.w)) + v_local;
  } else if (part == 6) {
    float h = u_geom[0].w;
    p = vec2(corner.x * (u_geom[1].z > 0.0 ? u_geom[1].z : u_viewport.x), floor(yOf(u_base) - h * 0.5 + 0.5) + corner.y * h);
  } else {
    float y0 = yOf(a_ohlc.w);
    float x1 = xOf(i + 1);
    float y1 = yOf(a_next.w);
    if (part == 0) {
      vec2 v = vec2(x1 - x0 + 1e-6, y1 - y0);
      vec2 d = v / length(v);
      float w = u_geom[0].x * 0.5 * (corner.y * 2.0 - 1.0);
      p = vec2(x0 + (x1 - x0) * corner.x - d.y * w, y0 + (y1 - y0) * corner.x + d.x * w);
    } else {
      // The fills: corner.y 0 on the line (clamped to its side of B), 1 on the edge it closes to.
      float yb = part == 3 ? (u_geom[2].x > 0.0 ? u_geom[2].x : u_viewport.y) : yOf(u_base);
      float s = part == 5 ? -1.0 : 1.0;
      bool in0 = part == 3 || (yb - y0) * s >= 0.0;
      bool in1 = part == 3 || (yb - y1) * s >= 0.0;
      if (!in0 && !in1) {
        gl_Position = vec4(2.0, 2.0, 0.0, 1.0);
        return;
      }
      float dy = y1 - y0;
      float xc = dy != 0.0 ? x0 + (x1 - x0) * (yb - y0) / dy : x0; // the exact crossing
      float ex = corner.x < 0.5 ? (in0 ? x0 : xc) : (in1 ? x1 : xc);
      float ey = corner.x < 0.5 ? (in0 ? y0 : yb) : (in1 ? y1 : yb);
      p = vec2(ex, corner.y < 0.5 ? ey : yb);
    }
  }
  gl_Position = vec4(p.x / u_viewport.x * 2.0 - 1.0, 1.0 - p.y / u_viewport.y * 2.0, 0.0, 1.0);
}`,
  fragment: `#version 300 es
precision mediump float;
in vec4 v_color;
in vec2 v_local;
flat in float v_radius;
out vec4 o_color;
void main() {
  if (v_radius > 0.0 && dot(v_local, v_local) > v_radius * v_radius) discard; // the disc
  o_color = v_color;
}`,
} as const;
