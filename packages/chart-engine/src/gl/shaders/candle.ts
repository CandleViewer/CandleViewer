// `candle` (E12-S06, plan §3): one program for both parts of a candle series, two batches sharing
// one CandleRing (BQ-1). Static source only. Corners come from gl_VertexID (a 4-vertex strip),
// so no corner buffer is bound. The instance is the ring's physical slot: its logical bar index
// is (gl_InstanceID - head) & mask, and slots at or past n collapse to a degenerate quad, so a
// prepend, an eviction and a pan are uniform writes (BQ-14). Ints are subtracted before any
// float (BQ-75); y is bar-cell's log1p / series mix (BQ-113). `u_batch` = (part, head, mask, n):
// part 0 the wick, 1 the body. `u_geom[0]` = (body, hairline, tick) device px and spacing CSS px;
// `u_geom[1].x` the DPR. Mirrors `src/layers/candle/geometry.ts` line for line.
// `u_palette` = up, down, wick, up tint, down tint, neutral (E12-D06 §2-§4).
export const CANDLE = {
  name: "candle",
  uniforms: [
    "u_viewport",
    "u_indexBase",
    "u_tickBase",
    "u_k",
    "u_log",
    "u_batch",
    "u_geom",
    "u_palette",
  ],
  vertex: `#version 300 es
layout(location = 0) in ivec4 a_ohlc;
layout(location = 1) in int a_meta;
uniform vec2 u_viewport;
uniform int u_indexBase;
uniform int u_tickBase;
uniform vec4 u_k;
uniform vec2 u_log;
uniform ivec4 u_batch;
uniform vec4 u_geom[2];
uniform vec4 u_palette[6];
out vec4 v_color;
out vec4 v_fill;
out vec2 v_local;
out vec2 v_size;
flat out int v_outline;
float yOf(int tick) {
  float t = float(tick - u_tickBase);
  float r = max(t * u_log.x, -0.999999);
  float series = r * (1.0 - r * (0.5 - r * (0.33333333 - r * 0.25)));
  float l = mix(log(1.0 + r), series, step(abs(r), 0.05));
  return mix(t, l, u_log.y) * u_k.y + u_k.z;
}
void main() {
  int i = (gl_InstanceID - u_batch.y) & u_batch.z;
  vec2 corner = vec2(float(gl_VertexID & 1), float(gl_VertexID >> 1));
  if (i >= u_batch.w) {
    gl_Position = vec4(2.0, 2.0, 0.0, 1.0);
    return;
  }
  int dir = (a_meta >> 4) & 3;
  float h = u_geom[0].y;
  float body = u_geom[0].x;
  float left = floor((float(i - u_indexBase) + 0.5 - u_k.w) * u_k.x - body * 0.5 + 0.5);
  float w;
  float y0;
  float y1;
  v_outline = 0;
  if (u_batch.x == 0) {
    w = dir == 1 ? 2.0 * h : h;
    y0 = yOf(a_ohlc.z);
    y1 = yOf(a_ohlc.y);
    v_color = u_palette[2];
    v_fill = v_color;
  } else {
    w = body;
    y0 = yOf(a_ohlc.x);
    y1 = yOf(a_ohlc.w);
    if (dir >= 2) {
      float tall = u_geom[0].w < 8.0 ? h : 2.0 * h;
      if (dir == 3) w = max(w, 3.0 * h);
      y0 = floor(y0 - tall * 0.5 + 0.5);
      y1 = y0 + tall;
      v_color = u_palette[2];
      v_fill = v_color;
    } else if (dir == 0) {
      v_color = u_palette[0];
      v_fill = u_palette[3];
      v_outline = w >= 3.0 * u_geom[1].x ? 2 : 1; // D06 §3.2: from 3 CSS px
    } else {
      v_color = u_palette[1];
      v_fill = v_color;
    }
  }
  float top = min(y0, y1);
  float bottom = max(max(y0, y1), top + h);
  vec2 size = vec2(w, bottom - top);
  // D06 §3.1: the wick on the centre column, a down wick widened to the column on its right.
  float x0 = left + floor((body - (u_batch.x == 0 ? h : w)) * 0.5);
  vec2 p = vec2(x0, top) + corner * size;
  v_local = corner * size;
  v_size = size;
  gl_Position = vec4(p.x / u_viewport.x * 2.0 - 1.0, 1.0 - p.y / u_viewport.y * 2.0, 0.0, 1.0);
}`,
  fragment: `#version 300 es
precision mediump float;
uniform vec4 u_geom[2];
in vec4 v_color;
in vec4 v_fill;
in vec2 v_local;
in vec2 v_size;
flat in int v_outline;
out vec4 o_color;
void main() {
  float h = u_geom[0].y;
  bool edgeY = v_local.y < h || v_local.y > v_size.y - h;
  bool edgeX = v_outline == 2 && (v_local.x < h || v_local.x > v_size.x - h);
  o_color = v_outline == 0 || edgeX || edgeY ? v_color : v_fill;
}`,
} as const;
