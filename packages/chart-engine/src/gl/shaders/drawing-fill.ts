// `drawing-fill` (E14-T03 slice 3): one instanced quad per filled drawing (rect, band, ellipse),
// the layer's second draw call (26 §3.10: lines, fills, labels). Three chart-space corners A, B, C
// ride as ivec4s (int bar index and tick, then their fractions' bits), re-projected from the pane
// block as `drawing-line` (BQ-75, BQ-113); D = B + C − A is formed in chart space, so a band's
// fourth corner and a rect's far corner match their `drawing-line` outlines under every scale.
// Rect and band: the quad is A, B, C, D itself and the fill stops half a stroke inside every edge
// (the outline is `drawing-line`'s, drawn first: program order), so a fill never tints its own
// stroke. Ellipse: inscribed in the projected box, filled and stroked by a fragment SDF (no
// tessellation); its dashes follow the angle × mean radius, an approximation of arc length.
// Fill and stroke colours arrive premultiplied (alpha × the flatten opacity) and leave so.
// Style = (kind 0 rect / 1 ellipse / 2 band, stroke width in device px, dash index, unused).
// Static source.
export const DRAWING_FILL = {
  name: "drawing-fill",
  uniforms: ["u_viewport", "u_indexBase", "u_tickBase", "u_k", "u_log"],
  vertex: `#version 300 es
layout(location = 0) in ivec4 a_cornerA;
layout(location = 1) in ivec4 a_cornerB;
layout(location = 2) in ivec4 a_cornerC;
layout(location = 3) in ivec4 a_fill;
layout(location = 4) in ivec4 a_stroke;
layout(location = 5) in ivec4 a_style;
uniform vec2 u_viewport;
uniform int u_indexBase;
uniform int u_tickBase;
uniform vec4 u_k;
uniform vec2 u_log;
out vec2 v_p;
flat out vec2 v_a;
flat out vec2 v_b;
flat out vec2 v_c;
flat out vec2 v_d;
flat out vec4 v_style;
flat out vec2 v_dash;
flat out vec4 v_fill;
flat out vec4 v_stroke;
const vec2 DASH[3] = vec2[3](vec2(0.0, 0.0), vec2(3.0, 6.0), vec2(0.0, 3.0));
vec2 project(ivec2 c, vec2 f) {
  vec2 rel = vec2(c - ivec2(u_indexBase, u_tickBase)) + f;
  float x = (rel.x + 0.5 - u_k.w) * u_k.x;
  float r = max(rel.y * u_log.x, -0.999999);
  float series = r * (1.0 - r * (0.5 - r * (0.33333333 - r * 0.25)));
  float l = mix(log(1.0 + r), series, step(abs(r), 0.05));
  return vec2(x, mix(rel.y, l, u_log.y) * u_k.y + u_k.z);
}
void main() {
  vec2 corner = vec2(float(gl_VertexID & 1), float(gl_VertexID >> 1));
  vec4 style = intBitsToFloat(a_style);
  vec2 fa = intBitsToFloat(a_cornerA.zw);
  vec2 fb = intBitsToFloat(a_cornerB.zw);
  vec2 fc = intBitsToFloat(a_cornerC.zw);
  v_a = project(a_cornerA.xy, fa);
  v_b = project(a_cornerB.xy, fb);
  v_c = project(a_cornerC.xy, fc);
  v_d = project(a_cornerB.xy + a_cornerC.xy - a_cornerA.xy, fb + fc - fa);
  float pad = style.y * 0.5 + 1.0;
  vec2 lo = min(v_a, v_d) - pad;
  vec2 hi = max(v_a, v_d) + pad;
  vec2 quad = corner.y < 0.5 ? mix(v_a, v_b, corner.x) : mix(v_c, v_d, corner.x);
  v_p = style.x > 0.5 && style.x < 1.5 ? mix(lo, hi, corner) : quad;
  v_style = style;
  v_dash = DASH[int(style.z)] * style.y;
  v_fill = intBitsToFloat(a_fill);
  v_stroke = intBitsToFloat(a_stroke);
  gl_Position = vec4(v_p.x / u_viewport.x * 2.0 - 1.0, 1.0 - v_p.y / u_viewport.y * 2.0, 0.0, 1.0);
}`,
  fragment: `#version 300 es
precision highp float;
in vec2 v_p;
flat in vec2 v_a;
flat in vec2 v_b;
flat in vec2 v_c;
flat in vec2 v_d;
flat in vec4 v_style;
flat in vec2 v_dash;
flat in vec4 v_fill;
flat in vec4 v_stroke;
out vec4 o_color;
float edge(vec2 p0, vec2 p1, vec2 inside) {
  vec2 e = p1 - p0;
  vec2 n = vec2(-e.y, e.x) / max(length(e), 1e-6);
  float d = dot(v_p - p0, n);
  return dot(inside - p0, n) < 0.0 ? -d : d;
}
void main() {
  float hw = v_style.y * 0.5;
  float fa;
  float sa = 0.0;
  if (v_style.x > 0.5 && v_style.x < 1.5) {
    vec2 c = (v_a + v_d) * 0.5;
    vec2 r = max(abs(v_d - v_a) * 0.5, vec2(1e-3));
    vec2 q = v_p - c;
    float k0 = length(q / r);
    float d = k0 * (k0 - 1.0) / max(length(q / (r * r)), 1e-6);
    fa = clamp(-d - hw + 0.5, 0.0, 1.0);
    float ring = abs(d);
    if (v_dash.y > 0.0) {
      float s = mod(atan(q.y / r.y, q.x / r.x) * 0.5 * (r.x + r.y), v_dash.y);
      ring = length(vec2(min(max(s - v_dash.x, 0.0), v_dash.y - s), ring));
    }
    sa = clamp(hw + 0.5 - ring, 0.0, 1.0);
  } else {
    vec2 m = (v_a + v_d) * 0.5;
    float e = min(edge(v_a, v_b, m), edge(v_b, v_d, m));
    e = min(e, min(edge(v_d, v_c, m), edge(v_c, v_a, m)));
    fa = clamp(e - hw + 0.5, 0.0, 1.0);
  }
  // Premultiplied colours (alpha × flatten opacity): the ring over the fill, "over" in one pass.
  vec4 s = v_stroke * sa;
  vec4 o = s + v_fill * fa * (1.0 - s.a);
  if (o.a <= 0.0) discard;
  o_color = o;
}`,
} as const;
