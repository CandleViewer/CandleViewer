/**
 * D-13 "Rules changed while open": the shown fields that differ between the painted detail and the re-read one,
 * compared by value ("0.10" to "0.1" is no change), with the old value for "Changed · was 0.01". A revision that
 * changes no shown field changes the provenance line only: no change, no tag, no announcement, no analytics.
 */
import * as copy from "./copy";
import { formatRule } from "./format";
import { statusOf, type InstrumentDetail, type RuleField, type RuleKey } from "./rules";

export interface RuleChange {
  readonly field: RuleField;
  readonly key: RuleKey;
  /** The row's label, in lower case for the sentence ("tick size"). */
  readonly label: string;
  /** The old value as the row showed it ("0.01", "—"). */
  readonly was: string;
  /** The new value as the row shows it. */
  readonly now: string;
  readonly unit: string | null;
}

export interface RulesDiff {
  readonly changes: readonly RuleChange[];
  readonly revisionFrom: number | null;
  readonly revisionTo: number | null;
}

interface Shape {
  readonly field: RuleField;
  readonly key: RuleKey;
  readonly read: (d: InstrumentDetail) => string;
  readonly unit: (d: InstrumentDetail) => string | null;
}

const rule =
  (pick: (d: InstrumentDetail) => string | undefined) =>
  (d: InstrumentDetail): string =>
    formatRule(pick(d)).text ?? copy.DASH;

const quote = (d: InstrumentDetail): string | null => d.quote_coin ?? null;
const base = (d: InstrumentDetail): string | null => d.base_coin ?? null;
const none = (): null => null;

/** Row order is the band's; `leverage_step` rides on the leverage row's own line, so it has its own entry. */
const SHAPES: readonly Shape[] = [
  {
    field: "status",
    key: "status",
    read: (d) => statusOf(d.status).word ?? copy.DASH,
    unit: none,
  },
  { field: "tick_size", key: "tick_size", read: rule((d) => d.tick_size), unit: quote },
  { field: "qty_step", key: "qty_step", read: rule((d) => d.qty_step), unit: base },
  { field: "min_order_qty", key: "min_order_qty", read: rule((d) => d.min_order_qty), unit: base },
  { field: "max_order_qty", key: "max_order_qty", read: rule((d) => d.max_order_qty), unit: base },
  {
    field: "min_notional_value",
    key: "min_notional_value",
    read: rule((d) => (d.min_notional_value === "0" ? undefined : d.min_notional_value)),
    unit: quote,
  },
  {
    field: "max_leverage",
    key: "max_leverage",
    read: rule((d) => d.max_leverage),
    unit: () => "×",
  },
  { field: "leverage_step", key: "max_leverage", read: rule((d) => d.leverage_step), unit: none },
  {
    field: "funding_interval_minutes",
    key: "funding_interval",
    read: (d) =>
      d.funding_interval_minutes === undefined
        ? copy.DASH
        : copy.fundingInterval(d.funding_interval_minutes),
    unit: none,
  },
];

const LABEL_FOR: Partial<Record<RuleField, string>> = { leverage_step: "leverage step" };

export function diffRules(prev: InstrumentDetail, next: InstrumentDetail): RulesDiff {
  const changes: RuleChange[] = [];
  for (const shape of SHAPES) {
    const was = shape.read(prev);
    const now = shape.read(next);
    if (was === now) continue;
    changes.push({
      field: shape.field,
      key: shape.key,
      label: LABEL_FOR[shape.field] ?? copy.LABELS[shape.key].toLowerCase(),
      was,
      now,
      unit: shape.unit(next),
    });
  }
  return {
    changes,
    revisionFrom: typeof prev.revision === "number" ? prev.revision : null,
    revisionTo: typeof next.revision === "number" ? next.revision : null,
  };
}

/** "Changed · was 0.01" for a row's field(s), or `null` when the row did not change. */
export function wasFor(diff: RulesDiff, key: RuleKey): string | null {
  const found = diff.changes.find((c) => c.key === key);
  return found === undefined ? null : copy.wasText(found.was);
}

/** The one polite announcement: the first changed row in the band's order (PROPOSED for several; owner: E08-D06). */
export function announcementFor(diff: RulesDiff): string | null {
  const first = diff.changes[0];
  return first === undefined
    ? null
    : copy.rulesChangedSentence(first.label, first.now, first.unit, first.was);
}

/** "Rules changed at 06:40 UTC (revision 7 → 8)." needs both revisions and a changed row. */
export function changedNote(diff: RulesDiff, atMs: number): string | null {
  if (diff.changes.length === 0 || diff.revisionFrom === null || diff.revisionTo === null) {
    return null;
  }
  return copy.rulesChangedAt(
    new Date(atMs).toISOString().slice(11, 16),
    diff.revisionFrom,
    diff.revisionTo,
  );
}
