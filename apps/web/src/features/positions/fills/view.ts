/**
 * The Fills tab's view (E29-S04 #979; E29-D02 §6.4, D02:299; BQ-13): the store's rows through the
 * Type chips and the panel's group-by, by order or every fill, with the two empty states told
 * apart: no fill at all (D02:299's "No recent fills on Sub-1 · LIVE") and chips that leave none
 * (S-04's `blotter.ui.filter_empty`, the Type chips restated in PROPOSED words). Derived on read,
 * never stored (`30-frontend-react.md`).
 */
import type { GroupBy } from "../model/grouping";
import { bindEntry, D03_TEXT, DECK, PROPOSED_TEXT } from "./copy";
import type { FillKind, FillRowModel, FillType } from "./model/fillRow";
import { applyTypeFilter, groupFills, TYPE_CHIPS, type FillsGroup } from "./model/grouping";

/** D03 §3.3's type words (`fills.type.*`, D03:281). */
export const TYPE_WORDS: Readonly<Record<FillKind, string>> = {
  trade: DECK["fills.type.*"].string,
  adl: D03_TEXT.typeAdl.string,
  liquidation: D03_TEXT.typeLiquidation.string,
  funding: D03_TEXT.typeFunding.string,
  settlement: D03_TEXT.typeSettlement.string,
};

/** A Type cell's word: the kind's, a value the wire's enum lacks as its raw name, else "—". */
export function typeWord(type: FillType): string {
  if (type.kind === "other") return type.name;
  if (type.kind === "missing") return DECK["fills.cell.null"].string;
  return TYPE_WORDS[type.kind];
}

export interface FillsViewInputs {
  readonly rows: readonly FillRowModel[];
  /** Every fill held, the held-back new ones too (the store's `all`); `rows` when omitted. */
  readonly all?: readonly FillRowModel[];
  /** The pressed Type chips (all of them by default, D02:299). */
  readonly types: ReadonlySet<FillKind>;
  readonly groupBy: GroupBy;
  /** D02:299's "Show every fill". */
  readonly everyFill: boolean;
  readonly labelOf?: (accountId: string) => string | null;
}

export interface FillsView {
  readonly groups: readonly FillsGroup[];
  /** No fill on any account (D02:299's empty line). */
  readonly empty: boolean;
  /** Fills exist, and the chips leave none. */
  readonly filterEmpty: boolean;
  /** The pressed chips restated for the filter-empty state (PROPOSED), else `null`. */
  readonly typeFilter: string | null;
  /** The rows shown that the chips leave, newest first. */
  readonly rows: readonly FillRowModel[];
  /** Every held fill the chips leave, the held-back new ones too: the tab's export (D-21). */
  readonly exportRows: readonly FillRowModel[];
}

export function buildFillsView(inputs: FillsViewInputs): FillsView {
  const kept = applyTypeFilter(inputs.rows, inputs.types);
  const filterEmpty = inputs.rows.length > 0 && kept.length === 0;
  const words = TYPE_CHIPS.filter((kind) => inputs.types.has(kind)).map((k) => TYPE_WORDS[k]);
  return {
    groups: groupFills(kept, inputs.groupBy, inputs.everyFill, inputs.labelOf),
    empty: inputs.rows.length === 0,
    filterEmpty,
    typeFilter: !filterEmpty
      ? null
      : words.length === 0
        ? PROPOSED_TEXT.typeFilterNone.string
        : bindEntry(PROPOSED_TEXT.typeFilter, { "Trade, ADL": words.join(", ") }),
    rows: kept,
    exportRows: inputs.all === undefined ? kept : applyTypeFilter(inputs.all, inputs.types),
  };
}
