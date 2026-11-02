/**
 * The Positions tab's view (E29-S01 #911): the store's rows through the panel's filters, sort and
 * grouping, with the totals row and the empty states the panel tells apart (E29-D02 §9.2, §10.1;
 * S-03, S-04). Derived on read, never stored (`30-frontend-react.md`: no stored derived state).
 */
import { applyFilters, type FilterChip } from "./filters";
import {
  groupRows,
  totalsOf,
  type AccountRealisedToday,
  type GroupBy,
  type GroupModel,
  type TotalsModel,
} from "./grouping";
import type { Environment, PositionRowModel } from "./rowMapping";
import { applySort, type SortState } from "./sort";

export interface ViewInputs {
  readonly rows: readonly PositionRowModel[];
  readonly chips: readonly FilterChip[];
  readonly groupBy: GroupBy;
  readonly sort: SortState | null;
  readonly environment: Environment | null;
  readonly realisedToday: AccountRealisedToday;
}

export interface PositionsView {
  readonly groups: readonly GroupModel[];
  readonly totals: TotalsModel;
  /** No open position on any account (S-03, "No open positions"). */
  readonly empty: boolean;
  /** Positions exist, and the chips leave none (S-04, "No rows match 2 filters"). */
  readonly filterEmpty: boolean;
  /** The rows the chips leave, in display order: what CSV export writes (D-21). */
  readonly rows: readonly PositionRowModel[];
}

export function buildPositionsView(inputs: ViewInputs): PositionsView {
  const kept = applySort(applyFilters(inputs.rows, inputs.chips), inputs.sort);
  return {
    groups: groupRows(kept, inputs.groupBy, inputs.realisedToday),
    totals: totalsOf(kept, inputs.environment, inputs.realisedToday),
    empty: inputs.rows.length === 0,
    filterEmpty: inputs.rows.length > 0 && kept.length === 0,
    rows: kept,
  };
}
