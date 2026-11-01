// The drawings layer's input (E14-T03 slice 1, #358 BQ-3): primitives, no tool semantics; a tool
// maps to one or more inputs. Checked at the worker boundary (E14-X01 DR8, DR9, DR29; SR-E14-03,
// SR-E14-04): finite numbers, bounded counts, a closed kind set, numeric colours (no CSS string is
// built from a style) and labels clamped as data. DOM-free (C-2.16).

/** The closed primitive set and the anchors each takes. */
export const DRAWING_POINTS = {
  segment: [2, 2],
  ray: [2, 2],
  line: [2, 2],
  hline: [1, 1],
  vline: [1, 1],
  rect: [2, 2],
  ellipse: [2, 2],
  band: [3, 3],
  polyline: [2, 500],
  text: [1, 1],
} as const satisfies Record<string, readonly [number, number]>;

export type DrawingKind = keyof typeof DRAWING_POINTS;
export const DRAWING_KINDS = Object.keys(DRAWING_POINTS) as readonly DrawingKind[];

/** Bounds (E14-X01 §4, DR29): the server's per-symbol 500 plus in-progress and order lines. */
export const MAX_DRAWINGS = 1_000;
/** All anchors of one chart: 1 MiB of float64 pairs, inside the 8 MB layer bucket (§3.16). */
export const MAX_ANCHORS = 65_536;
export const LABEL_MAX = 120;
export const FONT_MIN = 8;
export const FONT_MAX = 48;
export const WIDTH_MAX = 8;
const ID = /^[\w:.#-]{1,64}$/;

export interface DrawingStyle {
  /** 0xRRGGBBAA numbers: no CSS colour string exists to inject (SR-E14-04); no fill if absent. */
  readonly colour: number;
  readonly fill?: number;
  /** CSS px, an integer 1..8 (the server's range). */
  readonly width: number;
  /** Into slice 2's LUT: 0 solid, 1 dashed, 2 dotted. */
  readonly dash: 0 | 1 | 2;
  /** Label size in CSS px; clamped to 8..48 (SR-E14-03). */
  readonly fontSize?: number;
}

export interface DrawingInput {
  readonly id: string;
  readonly kind: DrawingKind;
  /** Anchors `[t0, tick0, t1, tick1, ...]`: µs time (authoritative, §3.10) and ticks. */
  readonly points: readonly number[] | Float64Array;
  readonly style: DrawingStyle;
  readonly label?: string;
  readonly z?: number;
  readonly visible?: boolean;
}

/** `replace` swaps the whole set; `patch` removes `remove`, then upserts `drawings` by id. */
export interface SetDrawings {
  readonly op: "replace" | "patch";
  readonly drawings: readonly DrawingInput[];
  readonly remove?: readonly string[];
}

const isObj = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null;
const isInt = (v: unknown, lo: number, hi: number): boolean =>
  Number.isInteger(v) && (v as number) >= lo && (v as number) <= hi;
const rgba = (v: unknown): boolean => isInt(v, 0, 0xffffffff);
export const isDrawingId = (v: unknown): v is string => typeof v === "string" && ID.test(v);

function styleReason(s: unknown): string | null {
  if (!isObj(s)) return "style is not an object";
  for (const k of Object.keys(s)) {
    if (!["colour", "fill", "width", "dash", "fontSize"].includes(k)) return `style key ${k}`;
  }
  if (!rgba(s["colour"]) || (s["fill"] !== undefined && !rgba(s["fill"]))) return "style colour";
  if (!isInt(s["width"], 1, WIDTH_MAX) || !isInt(s["dash"], 0, 2)) return "style width or dash";
  const f = s["fontSize"];
  return f === undefined || (typeof f === "number" && Number.isFinite(f)) ? null : "fontSize";
}

/** Why one drawing is refused, or null: checked before anything is stored (never throws). */
export function drawingReason(d: unknown): string | null {
  if (!isObj(d) || !isDrawingId(d["id"])) return "drawing id";
  const kind = d["kind"];
  if (typeof kind !== "string" || !Object.hasOwn(DRAWING_POINTS, kind)) {
    return `unknown drawing kind ${String(kind)}`;
  }
  const span = DRAWING_POINTS[kind as DrawingKind];
  const pts = d["points"];
  if (!Array.isArray(pts) && !(pts instanceof Float64Array)) return "points";
  const n = pts.length / 2;
  if (!Number.isInteger(n) || n < span[0] || n > span[1]) return `${kind} takes ${span}`;
  for (let i = 0; i < pts.length; i += 1) {
    if (typeof pts[i] !== "number" || !Number.isFinite(pts[i])) return "non-finite point";
  }
  const style = styleReason(d["style"]);
  if (style !== null) return style;
  if (d["label"] !== undefined && typeof d["label"] !== "string") return "label";
  if (d["z"] !== undefined && !isInt(d["z"], -32768, 32767)) return "z";
  return d["visible"] === undefined || typeof d["visible"] === "boolean" ? null : "visible";
}

/** Why a `setDrawings` is refused structurally (caps against state are the set's own). */
export function setDrawingsReason(cmd: Record<string, unknown>): string | null {
  const { op, drawings, remove } = cmd;
  if (op !== "replace" && op !== "patch") return "op";
  if (!Array.isArray(drawings) || drawings.length > MAX_DRAWINGS) return "drawings";
  if (remove !== undefined && (op === "replace" || !Array.isArray(remove))) return "remove";
  if (Array.isArray(remove) && (remove.length > MAX_DRAWINGS || !remove.every(isDrawingId))) {
    return "remove";
  }
  const seen = new Set<unknown>();
  for (const d of drawings) {
    const why = drawingReason(d);
    if (why !== null) return why;
    const id = (d as DrawingInput).id;
    if (seen.has(id)) return `duplicate drawing ${id}`;
    seen.add(id);
  }
  return null;
}

/** C0, DEL and C1 controls, U+2028/9, the bidi marks, overrides and isolates (the server's set). */
const stripped = (c: number): boolean =>
  c < 0x20 ||
  (c >= 0x7f && c <= 0x9f) ||
  c === 0x061c ||
  c === 0x200e ||
  c === 0x200f ||
  (c >= 0x2028 && c <= 0x202e) ||
  (c >= 0x2066 && c <= 0x2069) ||
  (c >= 0xd800 && c <= 0xdfff); // a lone surrogate: a pair iterates as one code point

/** SR-E14-03: text as data, at most `LABEL_MAX` code points, never parsed. */
export function clampLabel(s: string): string {
  let out = "";
  let n = 0;
  for (const ch of s) {
    if (n === LABEL_MAX) break;
    if (stripped(ch.codePointAt(0) as number)) continue; // a non-empty code point
    out += ch;
    n += 1;
  }
  return out;
}

export const clampFont = (px: number): number => Math.min(FONT_MAX, Math.max(FONT_MIN, px));
