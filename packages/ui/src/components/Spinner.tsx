import { useEffect, useState, type JSX } from "react";

export interface SpinnerProps {
  /** sm = `size.icon` (nested and inline), md = `size.control.height` (standalone). */
  size?: "sm" | "md";
  /**
   * Selects the mode. Set: standalone, a `role="status"` region that speaks the label. Unset: nested and
   * `aria-hidden`, only inside a host that is `aria-busy` or is its own status region (no double announcement).
   */
  label?: string;
}

const Arc = (): JSX.Element => (
  // No viewBox: user units are CSS px, so the 2px stroke and the dash need no scaling at either size.
  // r = 37.5% is the arc's 9/24 radius; pathLength 4 with a 3 1 dash draws 270 degrees.
  <svg className="cv-spinner__arc" aria-hidden="true" focusable="false">
    <circle cx="50%" cy="50%" r="37.5%" pathLength={4} />
  </svg>
);

/** The live region mounts empty and receives its text after mount, so the label is announced (CMP-014 A11y). */
function StatusSpinner({ size, label }: { size: "sm" | "md"; label: string }): JSX.Element {
  const [mounted, setMounted] = useState(false);
  useEffect(() => {
    setMounted(true);
  }, []);
  return (
    <span
      className="cv-spinner"
      role="status"
      aria-live="polite"
      aria-atomic="true"
      data-cmp="CMP-014"
      data-size={size}
      data-standalone=""
    >
      <Arc />
      <span className="cv-visually-hidden">{mounted ? label : null}</span>
    </span>
  );
}

/** CMP-014: an indeterminate busy indicator; one turn per 800 ms, a static arc under reduced motion. */
export function Spinner({ size = "md", label }: SpinnerProps): JSX.Element {
  if (label) return <StatusSpinner size={size} label={label} />;
  return (
    <span className="cv-spinner" aria-hidden="true" data-cmp="CMP-014" data-size={size}>
      <Arc />
    </span>
  );
}
