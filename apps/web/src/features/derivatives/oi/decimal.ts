// E24-S01 (#776) slice 1: the one decimal check the REST points and the live ticker share. `22` `Decimal` is
// `^-?[0-9]+(\.[0-9]+)?$` with no bound; this adds a defensive ceiling far above any open-interest or price
// figure (a longer string is malformed, never truncated), so the two parsers can never disagree on a value.
export const MAX_DECIMAL_DIGITS = 40;

const DECIMAL = new RegExp(
  `^-?[0-9]{1,${String(MAX_DECIMAL_DIGITS)}}(\\.[0-9]{1,${String(MAX_DECIMAL_DIGITS)}})?$`,
);

export const isDecimal = (v: unknown): v is string => typeof v === "string" && DECIMAL.test(v);
