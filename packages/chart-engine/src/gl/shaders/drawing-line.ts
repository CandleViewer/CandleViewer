// `drawing-line` (E14-T03 slice 2, #358 BQ-5: a new program; `line` stays the grid's): one
// instanced quad per drawn segment of a drawing. Anchors arrive in chart space as an int (bar
// index, tick) plus a float fraction, re-projected through the pane block exactly as `bar-cell`
// (BQ-75, BQ-113), so a pan or zoom is a uniform write and never an upload. The quad is expanded
// around p0 → p1 in device px; the fragment evaluates a signed distance: a capsule (round caps,
// no tessellation) cut by the dash pattern, measured from the anchor p0 so dashes stay put on an
// extended line. `DASH` is the pattern LUT in stroke widths, (dash core, period), round-capped:
// solid; dashed, a 4w dash and a 2w gap; dotted, a 1w dot and a 2w gap (`DRAWING_DASH`, the one
// table: the engine default pending E14-D04's value, BQ-358-7); a test holds this copy equal.
// Colours arrive premultiplied (alpha × the layer's flatten opacity) and leave premultiplied.
// Inputs are ivec4s at fixed locations (the VAO binds ints only; floats ride as bits), the
// corner is gl_VertexID's. Known limit: `mod(v_along, ...)` is float32, so the dash phase
// drifts once |along| reaches ~1e5 px (an anchor far off screen). Static source.
import { DRAWING_DASH } from "../../layers/drawings/model.js";

/** `DRAWING_DASH` under the name the backends read; the GLSL `DASH` copies are held equal. */
export const DASH_LUT = DRAWING_DASH;

export const DRAWING_LINE = {
  name: "drawing-line",
  uniforms: ["u_viewport", "u_indexBase", "u_tickBase", "u_k", "u_log"],
  vertex: `#version 300 es
layout(location = 0) in ivec4 a_anchor0;
layout(location = 1) in ivec4 a_anchor1;
layout(location = 2) in ivec4 a_style;
layout(location = 3) in ivec4 a_color;
uniform vec2 u_viewport;
uniform int u_indexBase;
uniform int u_tickBase;
uniform vec4 u_k;
uniform vec2 u_log;
out float v_along;
out float v_across;
flat out vec2 v_span;
flat out vec2 v_dash;
flat out float v_hw;
out vec4 v_color;
const vec2 DASH[3] = vec2[3](vec2(0.0, 0.0), vec2(3.0, 6.0), vec2(0.0, 3.0));
vec2 project(ivec4 a) {
  vec2 rel = vec2(a.xy - ivec2(u_indexBase, u_tickBase)) + intBitsToFloat(a.zw);
  float x = (rel.x + 0.5 - u_k.w) * u_k.x;
  float r = max(rel.y * u_log.x, -0.999999);
  float series = r * (1.0 - r * (0.5 - r * (0.33333333 - r * 0.25)));
  float l = mix(log(1.0 + r), series, step(abs(r), 0.05));
  return vec2(x, mix(rel.y, l, u_log.y) * u_k.y + u_k.z);
}
void main() {
  vec2 corner = vec2(float(gl_VertexID & 1), float(gl_VertexID >> 1));
  vec4 style = intBitsToFloat(a_style);
  vec2 p0 = project(a_anchor0);
  vec2 p1 = project(a_anchor1);
  vec2 d = p1 - p0;
  float len = length(d);
  vec2 along = len > 1e-6 ? d / len : vec2(1.0, 0.0);
  vec2 dir = style.w > 1.5 ? vec2(0.0, 1.0) : (style.w > 0.5 ? vec2(1.0, 0.0) : along);
  float far = 2.0 * (abs(p0.x) + abs(p0.y) + u_viewport.x + u_viewport.y);
  float hw = style.x * 0.5;
  float pad = hw + 1.0;
  v_span = vec2(style.z > 1.5 ? -far : 0.0, style.z > 0.5 ? far : len);
  v_along = mix(v_span.x - pad, v_span.y + pad, corner.x);
  v_across = (corner.y * 2.0 - 1.0) * pad;
  v_dash = DASH[int(style.y)] * style.x;
  v_hw = hw;
  v_color = intBitsToFloat(a_color);
  vec2 p = p0 + dir * v_along + vec2(-dir.y, dir.x) * v_across;
  gl_Position = vec4(p.x / u_viewport.x * 2.0 - 1.0, 1.0 - p.y / u_viewport.y * 2.0, 0.0, 1.0);
}`,
  fragment: `#version 300 es
precision highp float;
in float v_along;
in float v_across;
flat in vec2 v_span;
flat in vec2 v_dash;
flat in float v_hw;
in vec4 v_color;
out vec4 o_color;
void main() {
  float out_of_span = max(max(v_span.x - v_along, v_along - v_span.y), 0.0);
  float d = length(vec2(out_of_span, v_across));
  if (v_dash.y > 0.0) {
    float s = mod(v_along, v_dash.y);
    float gap = min(max(s - v_dash.x, 0.0), v_dash.y - s);
    d = max(d, length(vec2(gap, v_across)));
  }
  float alpha = clamp(v_hw + 0.5 - d, 0.0, 1.0);
  if (alpha <= 0.0) discard;
  o_color = v_color * alpha; // premultiplied in, premultiplied out
}`,
} as const;
