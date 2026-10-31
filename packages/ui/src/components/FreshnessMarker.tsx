import type { JSX } from "react";

/**
 * The eight data-confidence states (E08-D04 §3), highest first: the E08-D01 §2 precedence, the single source of
 * the order. Exactly one is shown at a time, never stacked.
 */
export const DATA_CONFIDENCE_PRECEDENCE = [
  "delisted",
  "disconnected",
  "reconnecting",
  "resyncing",
  "gapped",
  "backfilling",
  "stale",
  "live",
] as const;

export type DataConfidenceState = (typeof DATA_CONFIDENCE_PRECEDENCE)[number];

/** The one state shown when several hold (E08-D01 §2): the highest; `live` when none is degraded. */
export function freshnessOf(states: Iterable<DataConfidenceState>): DataConfidenceState {
  let rank = DATA_CONFIDENCE_PRECEDENCE.length - 1;
  for (const state of states) rank = Math.min(rank, DATA_CONFIDENCE_PRECEDENCE.indexOf(state));
  return DATA_CONFIDENCE_PRECEDENCE[rank] ?? "live";
}

/**
 * The compact presentation's cell marker (E08-D07 §5): a class swap on the cell that holds the value, never a node
 * of its own (`15` CMP-239: no extra DOM per cell on hot surfaces). `live` adds nothing: the absence of a marker is
 * the live state. The words live once elsewhere, a row's chip or a panel's footer line, and reach assistive
 * technology through the cell's `aria-describedby`.
 */
export function freshnessClassName(state: DataConfidenceState): string | undefined {
  return state === "live" ? undefined : `cv-freshness cv-freshness--${state}`;
}

const SECOND = 1000;
const MINUTE = 60 * SECOND;
const HOUR = 60 * MINUTE;

/** The age in its largest whole unit (E08-D07 D34): seconds under a minute, then minutes, then hours. */
const ageParts = (
  ms: number,
): { readonly n: number; readonly short: string; readonly word: string } => {
  const age = Number.isFinite(ms) ? Math.max(0, ms) : 0;
  if (age < MINUTE) return { n: Math.floor(age / SECOND), short: "s", word: "second" };
  if (age < HOUR) return { n: Math.floor(age / MINUTE), short: "m", word: "minute" };
  return { n: Math.floor(age / HOUR), short: "h", word: "hour" };
};

/** The drawn age (E08-D07 D34): "Stale 7s", "Stale 2m", "Stale 1h". */
export function formatStaleAge(ms: number): string {
  const { n, short } = ageParts(ms);
  return `Stale ${n}${short}`;
}

/** The age as it is read (the `15` L2214 form): "Stale, 7 seconds", "Stale, 1 minute". */
export function staleAgeName(ms: number): string {
  const { n, word } = ageParts(ms);
  return `Stale, ${n} ${word}${n === 1 ? "" : "s"}`;
}

/**
 * CMP-239's compact presentation for dense grids (E08-D07 §5): the age text, drawn once per row (CMP-161's Status
 * chip) or once per panel, whose id the row's cells name in `aria-describedby`. Only `stale` has a compact chip:
 * the other states reach a dense grid as a panel status (disconnected), a merged cell (delisted) or a cell class
 * (`freshnessClassName`); the chip form with every state's word is CMP-239's base.
 */
export interface FreshnessMarkerProps {
  readonly presentation: "compact";
  readonly state: "stale";
  /** The age of the last value: drawn "Stale 7s", read "Stale, 7 seconds" (D34). */
  readonly lastUpdatedAgeMs?: number;
  /** Overrides the words for a compound row, drawn and read the same: "Stale (server)" (E17-D01 L149). */
  readonly label?: string;
  /** Past T2 (E08-D07 D1): the strong chip, `stale.indicator` with `text.inverse`; T1 is the subtle one. */
  readonly escalated?: boolean;
  /** The node's id: the cells it describes point at it. */
  readonly id?: string;
}

/**
 * CMP-239 FreshnessMarker, compact: one chip with the age. It owns no live region: an age change is never announced
 * (E08-D07 D17; the host says one summary per stale episode). Colour is never the signal: the word carries it.
 */
export function FreshnessMarker({
  state,
  lastUpdatedAgeMs = 0,
  label,
  escalated = false,
  id,
}: FreshnessMarkerProps): JSX.Element {
  const custom = label?.trim();
  return (
    <span
      id={id}
      className="cv-freshness-chip"
      data-cmp="CMP-239"
      data-state={state}
      data-level={escalated ? "strong" : "subtle"}
    >
      {custom === undefined || custom === "" ? (
        <>
          <span aria-hidden="true">{formatStaleAge(lastUpdatedAgeMs)}</span>
          <span className="cv-visually-hidden">{staleAgeName(lastUpdatedAgeMs)}</span>
        </>
      ) : (
        custom
      )}
    </span>
  );
}
