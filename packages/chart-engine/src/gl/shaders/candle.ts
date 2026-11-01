// `candle` (E12-S06, plan §3): one program for every part of a candle or OHLC series, batches
// sharing one CandleRing (BQ-1). Static source only. Corners come from gl_VertexID, so no corner
// buffer is bound: a 4-vertex strip, or for the OHLC ticks a 10-vertex strip, two quads joined by
// degenerate bridges (BQ-15). The instance is the ring's physical slot (the seam's: the slot in
// `a_ohlc.x`): its logical bar index is (slot - head) & mask, and slots at or past n collapse to
// a degenerate quad, so a prepend, an eviction and a pan are uniform writes (BQ-14). Ints are
// subtracted before any float (BQ-75); y is bar-cell's log1p / series mix (BQ-113). `u_batch` =
// (part, head, mask, n), part as `CANDLE_PART`: 0 wick, 1 body, 2 OHLC ticks, 3 OHLC stem, 4 the
// gap seam. `u_geom[0]` = (body, hairline, tick) device px and spacing CSS px; `u_geom[1].x` the
// DPR. Mirrors `src/layers/candle/geometry.ts` line for line.
// `u_palette` = up, down, wick, up tint, down tint, neutral (E12-D06 §2-§4, §9).
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
  int part = u_batch.x;
  int i = ((part == 4 ? a_ohlc.x : gl_InstanceID) - u_batch.y) & u_batch.z;
  int vid = gl_VertexID;
  int sub = 0;
  if (part == 2) {
    sub = vid >= 5 ? 1 : 0;
    vid = sub == 0 ? min(vid, 3) : max(vid - 6, 0);
  }
  vec2 corner = vec2(float(vid & 1), float(vid >> 1));
  if (i >= u_batch.w) {
    gl_Position = vec4(2.0, 2.0, 0.0, 1.0);
    return;
  }
  int dir = (a_meta >> 4) & 3;
  float h = u_geom[0].y;
  float body = u_geom[0].x;
  float centre = (float(i - u_indexBase) + 0.5 - u_k.w) * u_k.x;
  float x0;
  float w;
  float y0;
  float y1;
  v_outline = 0;
  if (part == 4) {
    // BQ-8: the slot's left edge, a hairline over the whole pane.
    x0 = floor(centre - u_k.x * 0.5 - h * 0.5 + 0.5);
    w = h;
    y0 = 0.0;
    y1 = u_viewport.y;
  } else {
    float left = floor(centre - body * 0.5 + 0.5);
    float weight = dir == 1 ? 2.0 * h : h;
    float stem = left + floor((body - h) * 0.5);
    x0 = stem;
    w = weight;
    if (part == 2) {
      float tick = u_geom[0].z;
      if (dir == 3) {
        w = 0.0; // the stem draws the zero-range mark
      } else {
        x0 = sub == 0 ? stem - tick : stem + weight;
        w = tick;
      }
      y0 = floor(yOf(sub == 0 ? a_ohlc.x : a_ohlc.w) - weight * 0.5 + 0.5);
      y1 = y0 + weight;
    } else if (part == 1 || (part == 3 && dir == 3)) {
      w = body;
      y0 = yOf(a_ohlc.x);
      y1 = yOf(a_ohlc.w);
      if (dir >= 2) {
        // D06 §9: a doji is 2 hairlines tall (1 below 8 px); a zero-range bar 2 hairlines always,
        // max(body, roundHalfUp(3 dpr)) wide.
        float tall = dir == 3 || u_geom[0].w >= 8.0 ? 2.0 * h : h;
        if (dir == 3) w = max(w, floor(3.0 * u_geom[1].x + 0.5));
        y0 = floor(y0 - tall * 0.5 + 0.5);
        y1 = y0 + tall;
      }
      x0 = left + floor((body - w) * 0.5);
    } else {
      // The wick (candles) or the stem (OHLC): high to low on the centre column.
      y0 = yOf(a_ohlc.z);
      y1 = yOf(a_ohlc.y);
    }
  }
  // partColor: the wick, the seam, doji and zero-range neutral; else up or down.
  v_color = u_palette[part == 0 || part == 4 || dir >= 2 ? 2 : dir];
  v_fill = v_color;
  if (part == 1 && dir == 0) {
    v_fill = u_palette[3];
    v_outline = w >= 3.0 * u_geom[1].x ? 2 : 1; // D06 §3.2: from 3 CSS px
  }
  float top = min(y0, y1);
  float bottom = max(max(y0, y1), top + h);
  vec2 size = vec2(w, bottom - top);
  vec2 p = vec2(x0, top) + corner * size;
  v_local = corner * size;
  v_size = size;
  gl_Position = vec4(p.x / u_viewport.x * 2.0 - 1.0, 1.0 - p.y / u_viewport.y * 2.0, 0.0, 1.0);
}`,
  fragment: `#version 300 es
precision highp float; // u_geom is shared with the vertex stage: one precision (ESSL 3.00 link)
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
