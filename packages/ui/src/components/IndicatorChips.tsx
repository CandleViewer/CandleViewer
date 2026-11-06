import type { JSX } from "react";
import { Icon } from "../icons/Icon.js";
import type { IconName } from "../icons/registry.js";
import { useFocusRing } from "./FocusRing.js";
import { cx } from "./internal/cx.js";

export type IndicatorSuffixKind = "error" | "stale" | "computing" | "hidden";

export interface IndicatorSuffix {
  readonly kind: IndicatorSuffixKind;
  readonly n: number;
}

export interface IndicatorChipsProps {
  /** The count of indicator instances on this chart. */
  readonly count: number;
  /** The one state suffix; pick it with `pickIndicatorSuffix` (error first). */
  readonly suffix?: IndicatorSuffix;
  /** SCR-036 is open for this chart: the chip reads as pressed (`aria-pressed`), the name is unchanged. */
  readonly open?: boolean;
  /** Opens SCR-036 for this chart. */
  readonly onOpen: () => void;
}

/** The suffix order (E13-D02 §7.3): error, then stale, computing, hidden. */
export const INDICATOR_SUFFIX_ORDER: readonly IndicatorSuffixKind[] = [
  "error",
  "stale",
  "computing",
  "hidden",
];

/** The one suffix the chip shows: the first kind in `INDICATOR_SUFFIX_ORDER` with a non-zero count. */
export function pickIndicatorSuffix(
  counts: Readonly<Partial<Record<IndicatorSuffixKind, number>>>,
): IndicatorSuffix | undefined {
  for (const kind of INDICATOR_SUFFIX_ORDER) {
    const n = counts[kind] ?? 0;
    if (n > 0) return { kind, n };
  }
  return undefined;
}

/** The glyph rides the hue; the word carries the meaning (colour is never alone). */
const GLYPH: Readonly<Record<IndicatorSuffixKind, IconName>> = {
  error: "warning",
  stale: "warning",
  computing: "pending",
  hidden: "hide",
};

const suffixWords = ({ kind, n }: IndicatorSuffix): string =>
  kind === "error" ? `${n} ${n === 1 ? "error" : "errors"}` : `${n} ${kind}`;

/**
 * CMP-224 IndicatorChips: the toolbar's indicator entry, one count chip (`Ind 4 · 1 hidden`) that opens SCR-036
 * (E11-D02 A-14; E13-D02 D29). Per-indicator toggle, settings and remove live on CMP-199's rows. No live region of
 * its own; a change of the count or the suffix is an instant state flip (E13-D04 M9).
 */
export function IndicatorChips({ count, suffix, open, onOpen }: IndicatorChipsProps): JSX.Element {
  const ring = useFocusRing();
  const words = suffix === undefined || suffix.n <= 0 ? undefined : suffixWords(suffix);
  const name = `Indicators: ${count} on this chart${words === undefined ? "" : `, ${words}`} — open the object manager`;
  return (
    <button
      type="button"
      className={cx("cv-indicator-chips", ring.className)}
      data-cmp="CMP-224"
      aria-label={name}
      aria-pressed={open === undefined ? undefined : open}
      onClick={onOpen}
    >
      <span className="cv-indicator-chips__pill">
        <span>Ind {count}</span>
        {words === undefined || suffix === undefined ? null : (
          <>
            <span aria-hidden="true">·</span>
            <span className="cv-indicator-chips__glyph" data-kind={suffix.kind}>
              <Icon name={GLYPH[suffix.kind]} size="sm" />
            </span>
            <span>{words}</span>
          </>
        )}
      </span>
    </button>
  );
}
