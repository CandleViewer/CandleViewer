// The server's `dec_str` (services/api/candleviewer/rules/ir/canonical.py:61-65) for what a client
// sends; a value with no form to mirror gives undefined.

/** Plain notation of `digits` x 10^`exponent`: no exponent, no trailing fractional zero, "0" for 0. */
function plain(negative: boolean, digits: string, exponent: number): string | undefined {
  let [start, end] = [0, digits.length];
  while (start < end && digits[start] === "0") start++;
  while (end > start && digits[end - 1] === "0") end--;
  if (start === end) return "0";
  const coefficient = digits.slice(start, end);
  const exp = exponent + digits.length - end;
  // Python's default context: normalize() rounds past 28 significant digits, and past the
  // exponent range (+-999 999) it raises or rounds. Neither has a form to mirror.
  if (coefficient.length > 28 || Math.abs(exp + coefficient.length - 1) > 999_999) return undefined;
  const body =
    exp >= 0
      ? coefficient + "0".repeat(exp)
      : -exp < coefficient.length
        ? `${coefficient.slice(0, exp)}.${coefficient.slice(exp)}`
        : `0.${"0".repeat(-exp - coefficient.length)}${coefficient}`;
  return negative ? `-${body}` : body;
}

/**
 * Decimal text times 10^`exponent`: digits with an optional "-" and fraction, as the vectors pin
 * it. Pydantic hands the text to Python's `Decimal`, which also reads "+", ".5", "5.", exponents,
 * spaces, `_` and non-ASCII digits; no vector pins those, so they are not mirrored.
 */
export function decimalOfText(text: string, exponent = 0): string | undefined {
  const [, sign, whole, fraction = ""] = /^(-?)(\d+)(?:\.(\d+))?$/.exec(text) ?? [];
  if (whole === undefined) return undefined;
  return plain(sign === "-", whole + fraction, exponent - fraction.length);
}

/**
 * A number as the server reads `JSON.stringify(n)`: an int, or a float it turns into its shortest
 * decimal, the digits `String(n)` prints. NaN and +-Infinity go as null, and 1e21 or more with an
 * exponent the server reads as a float: an integer field refuses that, and no vector pins the rest.
 */
export function decimalOfNumber(n: number): string | undefined {
  if (!Number.isFinite(n) || Math.abs(n) >= 1e21) return undefined;
  const [mantissa, exponent] = String(n).split("e"); // an exponent only below 1e-6 here
  return decimalOfText(mantissa as string, Number(exponent ?? 0));
}
