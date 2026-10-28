import type { ComponentPropsWithoutRef, JSX } from "react";
import { cx } from "./internal/cx.js";

/** Pointer words of the keymap's chords ("Ctrl+click", "Shift+wheel", "Space+drag"): text, never a cap. */
const POINTER_WORDS: ReadonlySet<string> = new Set(["click", "drag", "wheel"]);
/** ECMAScript's line terminators: a digit range sits on one line. */
const LINE_TERMINATORS: readonly string[] = ["\n", "\r", "\u2028", "\u2029"];

/**
 * A digit range in the keymap's form ("1..9"): the text before the first ".." that starts after the
 * first character, and the text after that "..", both non-empty and on one line. A fixed number of
 * left-to-right scans, so a key of any length costs linear time; no RegExp backtracks over it.
 */
const splitRange = (key: string): { from: string; to: string } | undefined => {
  if (LINE_TERMINATORS.some((terminator) => key.includes(terminator))) return undefined;
  const at = key.indexOf("..", 1);
  return at === -1 || at + 2 >= key.length
    ? undefined
    : { from: key.slice(0, at), to: key.slice(at + 2) };
};

/**
 * The catalogue's spoken words ("Control plus Shift plus H"). Every other key word belongs to the
 * keymap's name table (E10 / E49), which its owner passes as `names`; a key absent from both is read
 * as written.
 */
const DEFAULT_NAMES: Readonly<Record<string, string>> = { Ctrl: "Control", Shift: "Shift" };

export interface KbdProps extends Omit<ComponentPropsWithoutRef<"kbd">, "children" | "style"> {
  /**
   * The active keymap profile's display form of the binding, one entry per key: `["Ctrl", "Shift",
   * "K"]`, a digit range `["Alt", "1..9"]`, a pointer chord `["Ctrl", "click"]`. Empty when the command
   * is unbound: nothing renders (conventions 40).
   */
  keys: readonly string[];
  /** The keymap's name table for the spoken form (key → word), merged over the catalogue's words. */
  names?: Readonly<Record<string, string>>;
}

type Part =
  | { kind: "cap"; key: string }
  | { kind: "range"; from: string; to: string }
  | { kind: "word"; word: string };

const parse = (key: string): Part => {
  const range = splitRange(key);
  if (range !== undefined) return { kind: "range", ...range };
  return POINTER_WORDS.has(key) ? { kind: "word", word: key } : { kind: "cap", key };
};

/** The visually hidden expansion: "Control plus Shift plus K", "Alt plus 1 to 9". */
export function kbdExpansion(
  keys: readonly string[],
  names: Readonly<Record<string, string>> = {},
): string {
  // Own keys only: "constructor" or "toString" must never resolve to an inherited member.
  const say = (key: string): string =>
    Object.hasOwn(names, key)
      ? (names[key] ?? key)
      : Object.hasOwn(DEFAULT_NAMES, key)
        ? (DEFAULT_NAMES[key] ?? key)
        : key;
  return keys
    .map(parse)
    .map((p) =>
      p.kind === "range"
        ? `${say(p.from)} to ${say(p.to)}`
        : say(p.kind === "cap" ? p.key : p.word),
    )
    .join(" plus ");
}

/**
 * CMP-022: a shortcut hint, never interactive. One `<kbd>` cap per key inside an outer `<kbd>`, no
 * visible "+"; the caps are `aria-hidden` and the outer element reads its expansion once. Inside a
 * menu item the host passes `aria-hidden` and carries the keys in `aria-keyshortcuts` instead.
 */
export function Kbd({ keys, names, className, ...rest }: KbdProps): JSX.Element | null {
  const bound = keys.map((k) => k.trim()).filter((k) => k !== "");
  if (bound.length === 0) return null;
  return (
    <kbd {...rest} className={cx("cv-kbd", className)} data-cmp="CMP-022">
      <span className="cv-kbd__caps" aria-hidden="true">
        {bound.map(parse).map((p, i) =>
          p.kind === "range" ? (
            <span key={i} className="cv-kbd__range">
              <kbd className="cv-kbd__cap">{p.from}</kbd>
              <span className="cv-kbd__word">–</span>
              <kbd className="cv-kbd__cap">{p.to}</kbd>
            </span>
          ) : p.kind === "word" ? (
            <span key={i} className="cv-kbd__word">
              {p.word}
            </span>
          ) : (
            <kbd key={i} className="cv-kbd__cap">
              {p.key}
            </kbd>
          ),
        )}
      </span>
      <span className="cv-visually-hidden">{kbdExpansion(bound, names)}</span>
    </kbd>
  );
}
