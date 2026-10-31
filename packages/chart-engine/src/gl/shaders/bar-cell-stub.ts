// `bar-cell` (E11-S02 stub): registered for E18/E19 to implement candles and footprint cells
// against. E11-S03: positions arrive as int (bar index, tick); the pane block's int
// `u_indexBase` and `u_tickBase` are subtracted before the float conversion, so no float here
// holds an absolute price or bar index (BQ-75). E11-S05 (BQ-113): one `u_log` = [tickSize /
// p(u_tickBase), on]; log is `log1p` of the relative tick times that ratio, a 4-term series for
// |x| < 0.05 (float32 `log(1 + x)` loses digits there), mixed in without a branch. Affine modes
// send [0, 0]: `mix(t, 0, 0)` is `t`, so linear is bit-identical. The floor keeps it finite.
export const BAR_CELL = {
  name: "bar-cell",
  uniforms: ["u_viewport", "u_indexBase", "u_tickBase", "u_k", "u_log"],
  vertex: `#version 300 es
in vec2 a_corner;
in ivec2 a_cell;
in vec2 a_size;
in vec4 a_color;
uniform vec2 u_viewport;
uniform int u_indexBase;
uniform int u_tickBase;
uniform vec4 u_k;
uniform vec2 u_log;
out vec4 v_color;
void main() {
  v_color = a_color;
  vec2 rel = vec2(a_cell - ivec2(u_indexBase, u_tickBase));
  float x = (rel.x + 0.5 - u_k.w + (a_corner.x - 0.5) * a_size.x) * u_k.x;
  float t = rel.y + a_corner.y * a_size.y;
  float r = max(t * u_log.x, -0.999999);
  float series = r * (1.0 - r * (0.5 - r * (0.33333333 - r * 0.25)));
  float l = mix(log(1.0 + r), series, step(abs(r), 0.05));
  float y = mix(t, l, u_log.y) * u_k.y + u_k.z;
  gl_Position = vec4(x / u_viewport.x * 2.0 - 1.0, 1.0 - y / u_viewport.y * 2.0, 0.0, 1.0);
}`,
  fragment: `#version 300 es
precision mediump float;
in vec4 v_color;
out vec4 o_color;
void main() { o_color = v_color; }`,
} as const;
