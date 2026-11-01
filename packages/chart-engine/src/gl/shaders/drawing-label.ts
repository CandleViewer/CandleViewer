// `drawing-label` (E14-T03 PR 2): one instanced quad per label glyph, the drawings layer's third
// and last draw call (26 §3.10: lines, fills, labels; 26 §3.7: drawing labels are a pane's third
// text batch). The anchor arrives in chart space as `drawing-line`'s ivec4 (int bar index and
// tick, then their fractions' bits) and is re-projected from the pane block (BQ-75, BQ-113), so a
// pan or zoom is a uniform write; the glyph box is device px from the projected anchor (y down),
// so a label keeps its CSS size at any zoom and changes only with the DPR. The fragment reads the
// SDF atlas (E11-S11's, #336; texture 0 until then) with an `fwidth` band (26 §3.7) and writes
// the premultiplied colour (alpha × the flatten opacity) × coverage. Static source.
export const DRAWING_LABEL = {
  name: "drawing-label",
  uniforms: ["u_viewport", "u_indexBase", "u_tickBase", "u_k", "u_log", "u_atlas"],
  vertex: `#version 300 es
layout(location = 0) in ivec4 a_anchor;
layout(location = 1) in ivec4 a_glyph;
layout(location = 2) in ivec4 a_uv;
layout(location = 3) in ivec4 a_color;
uniform vec2 u_viewport;
uniform int u_indexBase;
uniform int u_tickBase;
uniform vec4 u_k;
uniform vec2 u_log;
out vec2 v_uv;
flat out vec4 v_color;
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
  vec4 box = intBitsToFloat(a_glyph);
  vec4 uv = intBitsToFloat(a_uv);
  vec2 p = project(a_anchor) + box.xy + corner * box.zw;
  v_uv = mix(uv.xy, uv.zw, corner);
  v_color = intBitsToFloat(a_color);
  gl_Position = vec4(p.x / u_viewport.x * 2.0 - 1.0, 1.0 - p.y / u_viewport.y * 2.0, 0.0, 1.0);
}`,
  fragment: `#version 300 es
precision highp float;
uniform sampler2D u_atlas;
in vec2 v_uv;
flat in vec4 v_color;
out vec4 o_color;
void main() {
  float sdf = texture(u_atlas, v_uv).r;
  float w = max(fwidth(sdf), 1e-4);
  float a = smoothstep(0.5 - w, 0.5 + w, sdf);
  if (a <= 0.0) discard;
  o_color = v_color * a; // premultiplied in, premultiplied out
}`,
} as const;
