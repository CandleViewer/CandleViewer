import type { JSX, ReactNode } from "react";
import { cx } from "./internal/cx.js";

export interface KeyValueRowProps {
  label: ReactNode;
  /**
   * A number is a CMP-020 NumericText (the host picks its format and size); any other value is text.
   * `null`, `undefined` or `""` is unavailable: a "—" read as `missingLabel`, never an empty cell or 0.
   */
  value: ReactNode;
  /** The value one step up: `type.num.md` for a base-size number, `type.ui.body-strong` for text. */
  emphasis?: boolean;
  /** `stacked` puts the value under its label (a narrow host or 150 % text, §6 J8 (a)). */
  layout?: "inline" | "stacked";
  /**
   * What a missing value is read as, so "—" is never read as a dash: the host's state word (CMP-239's
   * on a live row). Defaults to "no value", as NumericText reads its own "—".
   */
  missingLabel?: string;
  /**
   * The freshness slot beside the value, `space.inset.xs` before it: a CMP-239 FreshnessMarker. A
   * typed `freshness` state replaces this slot once CMP-239 exists (#265 ruling item 10).
   */
  freshness?: ReactNode;
  className?: string;
}

const isMissing = (value: ReactNode): boolean =>
  value === null || value === undefined || value === "" || typeof value === "boolean";

/**
 * CMP-036: one `dt` / `dd` pair in a `div`, always inside the host's `<dl>` (one per group; a single
 * row is a `dl` of one). Static and never focusable; a nested link or button owns its keys.
 */
export function KeyValueRow({
  label,
  value,
  emphasis = false,
  layout = "inline",
  missingLabel = "no value",
  freshness,
  className,
}: KeyValueRowProps): JSX.Element {
  const missing = isMissing(value);
  return (
    <div
      className={cx("cv-kv", className)}
      data-cmp="CMP-036"
      data-layout={layout}
      data-emphasis={emphasis ? "" : undefined}
    >
      <dt className="cv-kv__label">{label}</dt>
      <dd className="cv-kv__value" data-missing={missing ? "" : undefined}>
        {missing ? (
          <>
            <span aria-hidden="true">—</span>
            <span className="cv-visually-hidden">{missingLabel}</span>
          </>
        ) : (
          value
        )}
        {freshness === undefined ? null : <span className="cv-kv__freshness">{freshness}</span>}
      </dd>
    </div>
  );
}
