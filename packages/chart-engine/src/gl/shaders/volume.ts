// `volume` (E12-S08 PR 1, E12-D06 §12): one instanced column per bar from 0 to the bar's volume,
// on the same ring slot as the price series' bar (BQ-14: index spacing on time and non-time bars
// alike). Static source only; corners from gl_VertexID, a 4-vertex strip. The instance is the
// ring's physical slot, its logical index (slot - head) & mask; slots at or past n collapse. The
// column is the candle body's width and centre (`u_geom[0].x`, the candle's `u_k` / `u_indexBase`
// arithmetic) and runs from the tick-0 line to the volume line, LINEAR only (volume is never log
// scaled): its height is never changed by the bar's direction, so a doji or zero-range bar draws
// a full-height column (the candle shader's doji hairline rule is deliberately absent). Unavailable
// (`a_meta` bit 6) collapses the instance: no sentinel position. `a_vol.x` = volume in int32
// ticks; `a_meta >> 4` = dir (bits 0..1), unavailable (2), neutral (3, a decimated tier's column,
// D06 §12 L1 / L2: always `color.candle.wick`, solid). `u_batch` = (0, head, mask, n);
// `u_palette` = up, down, wick, up tint (the candle rows). Mirrors `layers/volume/geometry.ts`.
export const VOLUME = {
  name: "volume",
  uniforms: ["u_viewport", "u_indexBase", "u_tickBase", "u_k", "u_batch", "u_geom", "u_palette"],
  vertex: `#version 300 es
layout(location = 0) in ivec4 a_vol;
layout(location = 1) in int a_meta;
uniform vec2 u_viewport;
uniform int u_indexBase;
uniform int u_tickBase;
uniform vec4 u_k;
uniform ivec4 u_batch;
uniform vec4 u_geom[2];
uniform vec4 u_palette[6];
out vec4 v_color;
out vec4 v_fill;
out vec2 v_local;
out vec2 v_size;
flat out int v_outline;
float yOf(int tick) {
  return float(tick - u_tickBase) * u_k.y + u_k.z;
}
void main() {
  int i = (gl_InstanceID - u_batch.y) & u_batch.z;
  int mark = a_meta >> 4;
  if (i >= u_batch.w || (mark & 4) != 0) {
    gl_Position = vec4(2.0, 2.0, 0.0, 1.0);
    return;
  }
  vec2 corner = vec2(float(gl_VertexID & 1), float(gl_VertexID >> 1));
  int dir = mark & 3;
  bool neutral = (mark & 8) != 0 || dir >= 2;
  float h = u_geom[0].y;
  float body = u_geom[0].x;
  float centre = (float(i - u_indexBase) + 0.5 - u_k.w) * u_k.x;
  float x0 = floor(centre - body * 0.5 + 0.5);
  float y0 = yOf(a_vol.x);
  float y1 = yOf(0);
  float top = min(y0, y1);
  float tall = a_vol.x == 0 ? 0.0 : max(max(y0, y1) - top, h);
  v_color = u_palette[neutral ? 2 : dir];
  v_fill = v_color;
  v_outline = 0;
  if (!neutral && dir == 0) {
    v_fill = u_palette[3];
    v_outline = body >= 3.0 * u_geom[1].x ? 2 : 1; // D06 §3.2: every side from 3 CSS px
  }
  vec2 size = vec2(body, tall);
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
  bool edge = v_outline == 0 || edgeX || edgeY;
  o_color = edge ? v_color : v_fill;
}`,
} as const;
