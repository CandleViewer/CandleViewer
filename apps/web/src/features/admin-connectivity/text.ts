import { COPY, type CopyKey } from "./copy";

/** The deck joins a string's lines with " · " (E08-D13 copy pack). */
const SEP = " · ";

/** A deck entry's lines, in order. */
export function parts(key: CopyKey): readonly string[] {
  return COPY[key].split(SEP);
}

const SLOT = /\{([^{}]+)\}/g;

/**
 * Fills a line's `{slot}`s from served values; a line with any slot left open is dropped (`null`), so no
 * example figure of the deck ever prints as if it were served (E08-D09 R-2).
 */
export function fill(
  line: string,
  slots: Readonly<Record<string, string | number>> = {},
): string | null {
  let open = false;
  const text = line.replace(SLOT, (_m, name: string) => {
    const value = slots[name];
    if (value === undefined) {
      open = true;
      return "";
    }
    return String(value);
  });
  return open ? null : text;
}

/** The lines of a deck entry that can be printed with the slots given. */
export function printable(
  key: CopyKey,
  slots?: Readonly<Record<string, string | number>>,
): readonly string[] {
  return parts(key).flatMap((line) => {
    const text = fill(line, slots);
    return text === null ? [] : [text];
  });
}
