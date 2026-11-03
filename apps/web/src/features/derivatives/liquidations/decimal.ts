// E24-S05 (#780) PR 4: exact decimal arithmetic on served strings for the bucket rows' display aggregates (BQ 5,
// ruled 6612481277: display aggregates of served prints, never a trading value). Scaled BigInts; never a float.

export interface Dec {
  readonly v: bigint;
  readonly scale: number;
}

const TEN = BigInt(10);
const pow = (n: number): bigint => TEN ** BigInt(n);

export function parseDec(text: string): Dec {
  const [int = "0", frac = ""] = text.split(".");
  return { v: BigInt(`${int}${frac}`), scale: frac.length };
}

export function addDec(a: Dec, b: Dec): Dec {
  const scale = Math.max(a.scale, b.scale);
  return { v: a.v * pow(scale - a.scale) + b.v * pow(scale - b.scale), scale };
}

/** `a ÷ b` at `scale` decimals, half up; `null` when `b` is zero. */
export function divDec(a: Dec, b: Dec, scale: number): Dec | null {
  if (b.v === BigInt(0)) return null;
  // a.v / 10^a.s ÷ (b.v / 10^b.s) = a.v · 10^(b.s + scale + 1 - a.s) / b.v, at scale + 1, then rounded
  const shift = b.scale + scale + 1 - a.scale;
  const num = shift >= 0 ? a.v * pow(shift) : a.v / pow(-shift);
  const q = num / b.v;
  return { v: (q + BigInt(5)) / TEN, scale };
}

export function formatDec(d: Dec): string {
  const digits = d.v.toString().padStart(d.scale + 1, "0");
  return d.scale === 0 ? digits : `${digits.slice(0, -d.scale)}.${digits.slice(-d.scale)}`;
}
