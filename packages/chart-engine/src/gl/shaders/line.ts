// `line` (E11-S02, 26 §3.10): grid, sessions, crosshair and indicator lines. One instanced quad per
// segment (p0, p1, width), expanded along the normal in the vertex shader. Static source only.
export const LINE = {
  name: "line",
  uniforms: ["u_viewport", "u_color"],
  vertex: `#version 300 es
in vec2 a_corner;
in vec4 a_segment;
in float a_width;
uniform vec2 u_viewport;
void main() {
  vec2 d = normalize(a_segment.zw - a_segment.xy + vec2(1e-6, 0.0));
  vec2 n = vec2(-d.y, d.x) * a_width * 0.5 * (a_corner.y * 2.0 - 1.0);
  vec2 p = mix(a_segment.xy, a_segment.zw, a_corner.x) + n;
  gl_Position = vec4(p / u_viewport * 2.0 - 1.0, 0.0, 1.0);
}`,
  fragment: `#version 300 es
precision mediump float;
uniform vec4 u_color;
out vec4 o_color;
void main() { o_color = u_color; }`,
} as const;
