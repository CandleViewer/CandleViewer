// `bar-cell` (E11-S02 stub): registered for E18/E19 to implement candles and footprint cells
// against. The stub subtracts `u_priceOrigin` in float; E18 moves it before the float conversion.
export const BAR_CELL = {
  name: "bar-cell",
  uniforms: ["u_viewport", "u_priceOrigin"],
  vertex: `#version 300 es
in vec2 a_corner;
in vec4 a_rect;
uniform vec2 u_viewport;
uniform float u_priceOrigin;
void main() {
  vec2 p = a_rect.xy - vec2(0.0, u_priceOrigin) + a_corner * a_rect.zw;
  gl_Position = vec4(p / u_viewport * 2.0 - 1.0, 0.0, 1.0);
}`,
  fragment: `#version 300 es
precision mediump float;
out vec4 o_color;
void main() { o_color = vec4(1.0); }`,
} as const;
