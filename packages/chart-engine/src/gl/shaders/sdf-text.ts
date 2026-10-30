// `sdf-text` (E11-S02): glyph quads sampling the SDF atlas E11-S11 supplies. Static source only.
export const SDF_TEXT = {
  name: "sdf-text",
  uniforms: ["u_viewport", "u_atlas", "u_color"],
  vertex: `#version 300 es
in vec2 a_corner;
in vec4 a_rect;
in vec4 a_uv;
uniform vec2 u_viewport;
out vec2 v_uv;
void main() {
  v_uv = a_uv.xy + a_corner * a_uv.zw;
  gl_Position = vec4((a_rect.xy + a_corner * a_rect.zw) / u_viewport * 2.0 - 1.0, 0.0, 1.0);
}`,
  fragment: `#version 300 es
precision mediump float;
uniform sampler2D u_atlas;
uniform vec4 u_color;
in vec2 v_uv;
out vec4 o_color;
void main() {
  float a = smoothstep(0.45, 0.55, texture(u_atlas, v_uv).r);
  o_color = vec4(u_color.rgb, u_color.a * a);
}`,
} as const;
