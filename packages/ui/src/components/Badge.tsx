import type { JSX } from "react";

export type BadgeTone = "neutral" | "info" | "success" | "warning" | "danger";

/** The displayed count caps here (E11); the accessible name always keeps the full number. */
const COUNT_CAP = 99;

interface BadgeCount {
  variant?: "count";
  value: number;
  /**
   * What is counted and any condition the tone implies ("unread alerts"): the badge is then a standalone
   * `role="img"` named "{value} {label}". Omit it only inside a named host (a labelled control such as
   * "Notifications, 3 unread"): the count is then `aria-hidden`, so the host's name must carry it.
   */
  label?: string;
  tone?: BadgeTone;
}

interface BadgeDot {
  variant: "dot";
  value?: never;
  label?: never;
  tone?: BadgeTone;
}

export type BadgeProps = BadgeCount | BadgeDot;

/** The whole, non-negative count; a negative value is 0. Callers handle non-finite values first. */
const wholeCount = (value: number): number => Math.max(0, Math.trunc(value));

/** The displayed numeral: the whole count up to 99, then "99+". */
export function badgeCountText(value: number): string {
  const whole = wholeCount(value);
  return whole > COUNT_CAP ? `${COUNT_CAP}+` : String(whole);
}

/**
 * CMP-012: a static status indicator, never focusable. A dot is always `aria-hidden` and sits beside a
 * visible word (plus the tone's glyph), so the tone never carries the condition alone. Counts are tinted
 * (subtle fill, `.strong` outline, `text.primary` numeral): no text token reaches 4.5:1 on every solid fill.
 * A count with a non-finite value (NaN, Infinity) renders nothing rather than show or announce a fake one.
 */
export function Badge(props: BadgeProps): JSX.Element | null {
  const tone = props.tone ?? "neutral";
  if (props.variant === "dot") {
    return (
      <span
        className="cv-badge"
        data-cmp="CMP-012"
        data-variant="dot"
        data-tone={tone}
        aria-hidden="true"
      >
        <span className="cv-badge__dot" />
      </span>
    );
  }
  const { value, label } = props;
  if (!Number.isFinite(value)) return null;
  const named = label !== undefined && label.trim() !== "";
  return (
    <span
      className="cv-badge"
      data-cmp="CMP-012"
      data-variant="count"
      data-tone={tone}
      role={named ? "img" : undefined}
      aria-label={named ? `${wholeCount(value)} ${label}` : undefined}
      aria-hidden={named ? undefined : "true"}
    >
      {badgeCountText(value)}
    </span>
  );
}
