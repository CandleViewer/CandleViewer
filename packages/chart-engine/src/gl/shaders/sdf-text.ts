// `sdf-text` and `sdf-text-outline` (E11-S11 PR B, 26 §3.7, README BQ-267): glyph quads sampling
// the R8 SDF atlas, stride 12 (`a_rect`, `a_uv`, `a_color`: colour per instance, no `u_color`).
// The edge is the `fwidth` band, so any class and DPR is one smoothstep a screen pixel wide. The
// outline is a second constant-source program that composites in the same pass (one draw call,
// C-101): its threshold is `u_text.x` device px over the atlas's spread at this quad's scale.
// `a_uv` is (u, v, du, dv) and may run upward (a negative dv); `u_text` is (outlinePx, spread,
// atlas width, atlas height), set once per frame. Static source only (CE-E04).
const VERTEX = `#version 300 es
in vec2 a_corner;
in vec4 a_rect;
in vec4 a_uv;
in vec4 a_color;
uniform vec2 u_viewport;
uniform vec4 u_text;
out vec2 v_uv;
out vec4 v_color;
out float v_scale;
void main() {
  v_uv = a_uv.xy + a_corner * a_uv.zw;
  v_color = a_color;
  v_scale = a_rect.z / max(abs(a_uv.z) * u_text.z, 1e-6);
  gl_Position = vec4((a_rect.xy + a_corner * a_rect.zw) / u_viewport * 2.0 - 1.0, 0.0, 1.0);
}`;

export const SDF_TEXT = {
  name: "sdf-text",
  uniforms: ["u_viewport", "u_atlas", "u_text"],
  vertex: VERTEX,
  fragment: `#version 300 es
precision mediump float;
uniform sampler2D u_atlas;
in highp vec2 v_uv; // a 1,024 px atlas needs fp32 UVs on fp16 hardware
in vec4 v_color;
in float v_scale;
out vec4 o_color;
void main() {
  float d = texture(u_atlas, v_uv).r;
  float w = fwidth(d);
  float a = smoothstep(0.5 - w, 0.5 + w, d);
  o_color = vec4(v_color.rgb, v_color.a * a);
}`,
} as const;

export const SDF_TEXT_OUTLINE = {
  name: "sdf-text-outline",
  uniforms: ["u_viewport", "u_atlas", "u_text", "u_outlineColor"],
  vertex: VERTEX,
  fragment: `#version 300 es
precision mediump float;
uniform sampler2D u_atlas;
uniform vec4 u_text;
uniform vec4 u_outlineColor;
in highp vec2 v_uv; // a 1,024 px atlas needs fp32 UVs on fp16 hardware
in vec4 v_color;
in float v_scale;
out vec4 o_color;
void main() {
  float d = texture(u_atlas, v_uv).r;
  float w = fwidth(d);
  float a = smoothstep(0.5 - w, 0.5 + w, d);
  float o = u_text.x / (2.0 * u_text.y * max(v_scale, 1e-6));
  float ao = smoothstep(0.5 - o - w, 0.5 - o + w, d);
  o_color = mix(vec4(u_outlineColor.rgb, ao * u_outlineColor.a), v_color, a);
}`,
} as const;
