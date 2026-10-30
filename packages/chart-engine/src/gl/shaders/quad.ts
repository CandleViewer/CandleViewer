// `quad` (E11-S02): solid instanced rectangles (backgrounds, bodies, cells). Static source only.
export const QUAD = {
  name: "quad",
  uniforms: ["u_viewport"],
  vertex: `#version 300 es
in vec2 a_corner;
in vec4 a_rect;
in vec4 a_color;
uniform vec2 u_viewport;
out vec4 v_color;
void main() {
  v_color = a_color;
  gl_Position = vec4((a_rect.xy + a_corner * a_rect.zw) / u_viewport * 2.0 - 1.0, 0.0, 1.0);
}`,
  fragment: `#version 300 es
precision mediump float;
in vec4 v_color;
out vec4 o_color;
void main() { o_color = v_color; }`,
} as const;
