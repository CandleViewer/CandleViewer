// Pure colour-math helpers for the contrast-matrix gate (E05-T05).
//
// Ports the WCAG relative-luminance/contrast-ratio formulas and the Brettel
// (1997)/Vienot protanopia and deuteranopia simulation validated in
// `docs/research/_tools/cvd_simulate.py` (E05-D07) to JS so the same
// deterministic, stdlib-only logic runs inside the Node/Style Dictionary
// build pipeline. Tritanopia is NOT ported from that file (its tritan row is
// defective, #4639); it uses the Machado, Oliveira & Fernandes (2009) matrix
// below instead. No network, no dependencies.

/** @param {string} hex */
function hexToRgb(hex) {
  const h = hex.replace(/^#/, "");
  if (!/^[0-9a-fA-F]{6}([0-9a-fA-F]{2})?$/.test(h)) {
    throw new Error(`A11Y-C000 not a hex colour: "${hex}"`);
  }
  return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16)];
}

function srgbToLinear(c) {
  const cs = c / 255;
  return cs <= 0.04045 ? cs / 12.92 : ((cs + 0.055) / 1.055) ** 2.4;
}

function linearToSrgb(c) {
  const s = c <= 0.0031308 ? c * 12.92 : 1.055 * c ** (1 / 2.4) - 0.055;
  return Math.max(0, Math.min(1, s)) * 255;
}

function rgbToHex([r, g, b]) {
  const clamp = (v) => Math.max(0, Math.min(255, Math.round(v)));
  return (
    "#" +
    [r, g, b]
      .map(clamp)
      .map((v) => v.toString(16).toUpperCase().padStart(2, "0"))
      .join("")
  );
}

/** WCAG relative luminance (0..1). */
export function relativeLuminance(hex) {
  const [r, g, b] = hexToRgb(hex).map(srgbToLinear);
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

/** WCAG contrast ratio (1..21) between two sRGB hex colours. */
export function contrastRatio(hexA, hexB) {
  const la = relativeLuminance(hexA);
  const lb = relativeLuminance(hexB);
  const [lighter, darker] = la >= lb ? [la, lb] : [lb, la];
  return (lighter + 0.05) / (darker + 0.05);
}

const RGB_TO_LMS = [
  [17.8824, 43.5161, 4.11935],
  [3.45565, 27.1554, 3.86714],
  [0.0299566, 0.184309, 1.46709],
];
const LMS_TO_RGB = [
  [0.0809444479, -0.130504409, 0.116721066],
  [-0.0102485335, 0.0540193266, -0.113614708],
  [-0.000365296938, -0.00412161469, 0.693511405],
];
// Brettel (1997)/Vienot dichromacy projection planes for D65 (protan, deutan).
const PROJECTIONS = {
  protanopia: [
    [0, 2.02344, -2.52581],
    [0, 1, 0],
    [0, 0, 1],
  ],
  deuteranopia: [
    [1, 0, 0],
    [0.494207, 0, 1.24827],
    [0, 0, 1],
  ],
};

// Tritanopia: Machado, Oliveira & Fernandes (2009), "A Physiologically-based
// Model for Simulation of Color Vision Deficiency", IEEE TVCG 15(6), the
// published tritanomaly matrix at severity 1.0, applied directly to linear RGB
// (each row sums to 1, so white and greys are preserved), then clamped and
// encoded back to sRGB. Mirrors TRITAN_MACHADO / `simulate` in
// `docs/design/_tools/e12_d06_series_audit.py`, with the same rounding.
// Replaces the defective LMS row `S = -0.395913 L + 0.801109 M` carried by
// `docs/research/_tools/cvd_simulate.py`, which mapped every colour onto
// R = G (red -> #BABA00, green -> #BDBDFF); see #4639.
const LINEAR_RGB_SIMS = {
  tritanopia: [
    [1.255528, -0.076749, -0.178779],
    [-0.078411, 0.930809, 0.147602],
    [0.004733, 0.691367, 0.3039],
  ],
};

function matvec(m, v) {
  return [
    m[0][0] * v[0] + m[0][1] * v[1] + m[0][2] * v[2],
    m[1][0] * v[0] + m[1][1] * v[1] + m[1][2] * v[2],
    m[2][0] * v[0] + m[2][1] * v[1] + m[2][2] * v[2],
  ];
}

/**
 * Simulates a dichromacy over a sRGB hex colour.
 * @param {string} hex
 * @param {"protanopia"|"deuteranopia"|"tritanopia"} deficiency
 */
export function simulateCvd(hex, deficiency) {
  const linearSim = Object.hasOwn(LINEAR_RGB_SIMS, deficiency) ? LINEAR_RGB_SIMS[deficiency] : null;
  const projection = Object.hasOwn(PROJECTIONS, deficiency) ? PROJECTIONS[deficiency] : null;
  if (!linearSim && !projection) {
    throw new Error(`A11Y-C000 unknown CVD deficiency: "${deficiency}"`);
  }
  const rgb = hexToRgb(hex);
  const lin = rgb.map(srgbToLinear);
  if (linearSim) {
    return rgbToHex(matvec(linearSim, lin).map(linearToSrgb));
  }
  const lms = matvec(RGB_TO_LMS, lin);
  const proj = matvec(projection, lms);
  const lin2 = matvec(LMS_TO_RGB, proj);
  return rgbToHex(lin2.map(linearToSrgb));
}

function srgbToXyz(hex) {
  const [r, g, b] = hexToRgb(hex).map(srgbToLinear);
  return [
    r * 0.4124 + g * 0.3576 + b * 0.1805,
    r * 0.2126 + g * 0.7152 + b * 0.0722,
    r * 0.0193 + g * 0.1192 + b * 0.9505,
  ];
}

function xyzToLab([x, y, z]) {
  const xn = x / 0.95047;
  const yn = y / 1.0;
  const zn = z / 1.08883;
  const f = (t) => (t > 0.008856 ? t ** (1 / 3) : 7.787 * t + 16 / 116);
  const [fx, fy, fz] = [f(xn), f(yn), f(zn)];
  return [116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)];
}

/**
 * CIE L*a*b* (D65) of an sRGB hex colour, as `[L, a, b]`; the same formula as
 * `rgb_to_lab` in `packages/ui/tokens/tests/verify_tokens.py`.
 */
export function cieLab(hex) {
  return xyzToLab(srgbToXyz(hex));
}

/** CIE76 deltaE perceptual distance between two sRGB hex colours. */
export function deltaE76(hexA, hexB) {
  const labA = cieLab(hexA);
  const labB = cieLab(hexB);
  return Math.sqrt(labA.reduce((acc, v, i) => acc + (v - labB[i]) ** 2, 0));
}

/**
 * Minimum perceptually-just-noticeable-difference floor, below which two
 * adjacent ramp stops (or a buy/sell pair) are flagged as indistinguishable
 * under a CVD simulation. Value fixed by E05-D07 (`docs/research/_tools/
 * cvd_simulate.py`; only the floor, not that file's tritan row): CIE76 dE < 2.3 is the classic JND; 5.0 is the
 * conservative "clearly distinguishable at a glance under stress/low-vision"
 * floor used for the automated re-tuning flag (A11Y-C003).
 */
export const CVD_JND_FLOOR = 5.0;

export const CVD_DEFICIENCIES = ["deuteranopia", "protanopia", "tritanopia"];
