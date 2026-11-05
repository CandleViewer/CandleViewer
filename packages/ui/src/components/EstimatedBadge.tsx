import { createContext, useContext, useMemo, type JSX, type ReactNode } from "react";
import { cx } from "./internal/cx.js";
import { Tooltip } from "./Tooltip.js";

/**
 * The methodology sections CMP-227 can open (15 CMP-227 Props; PROPOSED union, E25-D05 G2): the six
 * `DetectorMethodology.detector` members plus the estimated-value kinds around them.
 */
export type DetectorId =
  | "iceberg"
  | "stop_run"
  | "absorption"
  | "exhaustion"
  | "big_trade"
  | "regime"
  | "queue_position"
  | "order_count"
  | "liquidity_cluster"
  | "trade_cluster"
  | "liquidation_cluster"
  | "funding";

export type EstimatedBadgeVariant = "inline" | "marker" | "section";
export type EstimatedBadgeSize = "sm" | "md";
export type EstimatedConfidence = "low" | "medium" | "high";

export interface EstimatedBadgeProps {
  detector: DetectorId;
  variant: EstimatedBadgeVariant;
  size: EstimatedBadgeSize;
  /** The confidence as a word in the accessible name ("Estimated, Funding rate, low confidence"). */
  confidence?: EstimatedConfidence;
  /**
   * PROPOSED: the display name in the accessible name, "Estimated, <name>" (15 CMP-227 A11y); the detector's
   * own name when absent.
   */
  name?: string;
  /** The tooltip's text; its first sentence is the provenance (CMP-016: hover and focus, `Esc`). */
  tooltip?: string;
  className?: string;
}

const DETECTOR_NAMES: Readonly<Record<DetectorId, string>> = {
  iceberg: "Iceberg",
  stop_run: "Stop run",
  absorption: "Absorption",
  exhaustion: "Exhaustion",
  big_trade: "Big trade",
  regime: "Regime",
  queue_position: "Queue position",
  order_count: "Order count",
  liquidity_cluster: "Liquidity cluster",
  trade_cluster: "Trade cluster",
  liquidation_cluster: "Liquidation cluster",
  funding: "Funding rate",
};

export interface EstimatedMethodology {
  /**
   * `opener` is the badge element that was activated: the host returns focus to it on close. It is passed
   * rather than read from `document.activeElement`, which a mouse click leaves on `body` in Safari and in
   * Firefox on macOS.
   */
  openMethodology: (detector: DetectorId, opener: HTMLElement) => void;
}

const MethodologyContext = createContext<EstimatedMethodology | null>(null);

export interface EstimatedMethodologyProviderProps {
  /**
   * Opens the methodology (CMP-069) at the detector's section; the host owns the drawer.
   * TODO(E25-D05 G9): the provider must also emit `methodology.opened{detector}` (15 CMP-227 Data contract);
   * its transport is undecided (E25-D05 G9), so nothing is emitted yet.
   */
  openMethodology: (detector: DetectorId, opener: HTMLElement) => void;
  children?: ReactNode;
}

/** The required binding of every badge to its drawer (name PROPOSED, 15 CMP-227 Props). */
export function EstimatedMethodologyProvider({
  openMethodology,
  children,
}: EstimatedMethodologyProviderProps): JSX.Element {
  const value = useMemo(() => ({ openMethodology }), [openMethodology]);
  return <MethodologyContext.Provider value={value}>{children}</MethodologyContext.Provider>;
}

/** Thrown by a badge rendered outside the provider: a development-time error, never a decorative chip. */
export class EstimatedBadgeOutsideProviderError extends Error {
  constructor() {
    super("EstimatedBadge needs an EstimatedMethodologyProvider (CMP-227).");
    this.name = "EstimatedBadgeOutsideProviderError";
  }
}

/** Throws `EstimatedBadgeOutsideProviderError` outside the provider. */
export function useEstimatedMethodology(): EstimatedMethodology {
  const value = useContext(MethodologyContext);
  if (value === null) throw new EstimatedBadgeOutsideProviderError();
  return value;
}

/** "Estimated, Funding rate[, low confidence]": the literal word is in the name, never colour alone. */
export const estimatedName = (
  detector: DetectorId,
  confidence: EstimatedConfidence | undefined,
  name?: string,
): string =>
  [
    "Estimated",
    name ?? DETECTOR_NAMES[detector],
    ...(confidence ? [`${confidence} confidence`] : []),
  ].join(", ");

/**
 * CMP-227: the one `(estimated)` badge. A native button whose `Enter` / `Space` opens the methodology through
 * the provider; the visible word is "(estimated)" (the `marker` is a glyph with the word visually hidden and
 * carried by its pane's legend row). Outline and glyph carry the hue, never the word.
 */
export function EstimatedBadge({
  detector,
  variant,
  size,
  confidence,
  name,
  tooltip = "",
  className,
}: EstimatedBadgeProps): JSX.Element {
  const { openMethodology } = useEstimatedMethodology();
  return (
    <Tooltip content={tooltip}>
      <button
        type="button"
        className={cx("cv-estimated", className)}
        data-cmp="CMP-227"
        data-variant={variant}
        data-size={size}
        data-detector={detector}
        aria-haspopup="dialog"
        aria-label={estimatedName(detector, confidence, name)}
        onClick={(event) => openMethodology(detector, event.currentTarget)}
      >
        <span className="cv-estimated__glyph" aria-hidden="true">
          ≈
        </span>
        <span className={variant === "marker" ? "cv-visually-hidden" : "cv-estimated__word"}>
          (estimated)
        </span>
      </button>
    </Tooltip>
  );
}
