import { useId, type CSSProperties, type JSX } from "react";
import { Icon } from "../icons/Icon.js";

/** The bar's name: a visible `label`, or the host's heading through `aria-labelledby`; one is required (D02 H12). */
export type ProgressBarName =
  { label: string; "aria-labelledby"?: never } | { label?: never; "aria-labelledby": string };

export type ProgressBarProps = ProgressBarName & {
  /** 0–100; clamped. Determinate only: an unknown total uses CMP-038, never a loop (D02 H12). */
  value: number;
  /** `progress` for a task (`role="progressbar"`), `meter` for a gauge such as a disk budget (`role="meter"`). */
  kind?: "progress" | "meter";
  /** Warning and danger add their glyph before the value text, so the tone is never colour alone. */
  tone?: "default" | "success" | "warning" | "danger";
  /** The visible value and `aria-valuetext` ("page 3 of ~9"); omitted, the percentage ("31 %"). */
  valueText?: string;
};

const MIN = 0;
const MAX = 100;

/**
 * CMP-023: a determinate progress bar or meter. The value text is always shown and read through the bar's
 * value (`aria-valuetext` is always the shown string, so a meter reads its unit), never as a live region: the host announces the start, the completion or a failure once.
 */
export function ProgressBar({
  value,
  kind = "progress",
  tone = "default",
  valueText,
  label,
  "aria-labelledby": labelledBy,
}: ProgressBarProps): JSX.Element {
  const labelId = useId();
  const now = Math.min(MAX, Math.max(MIN, Number.isFinite(value) ? value : MIN));
  const shown = valueText ?? `${Math.round(now)} %`;
  const glyph = tone === "warning" || tone === "danger" ? tone : undefined;
  return (
    <div className="cv-progress" data-cmp="CMP-023" data-tone={tone}>
      <div className="cv-progress__head">
        {label === undefined ? null : (
          <span id={labelId} className="cv-progress__label">
            {label}
          </span>
        )}
        <span className="cv-progress__value" aria-hidden="true">
          {glyph === undefined ? null : <Icon name={glyph} />}
          {shown}
        </span>
      </div>
      <div
        className="cv-progress__track"
        role={kind === "meter" ? "meter" : "progressbar"}
        aria-labelledby={labelledBy ?? labelId}
        aria-valuenow={now}
        aria-valuemin={MIN}
        aria-valuemax={MAX}
        aria-valuetext={shown}
      >
        <span
          className="cv-progress__fill"
          style={{ "--cv-progress": now / MAX } as CSSProperties}
        />
      </div>
    </div>
  );
}
