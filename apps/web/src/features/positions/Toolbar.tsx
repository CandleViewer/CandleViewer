/**
 * SCR-063's toolbar on the Positions tab (E29-S01 #911; E29-D02 §9.1): Group by (CMP-009), the
 * FilterBar (CMP-055) whose "+ Filter" opens the account picker (CMP-105, `mode="account"`, D04
 * board 05's `CMP-105/filter-picker`), then, on the right, Columns (CMP-056's `menu`) and Export CSV
 * (CMP-001 secondary, D-21). Every control is a read or a view choice: none is T2 for any role
 * (E29-D04 §4.2, D02:433) and none sends a request; the server scopes the accounts listed (a
 * Manager's assigned ones only), and no filter reveals another (US-POS-006).
 *
 * Not built here: the "+ Filter" menu's Symbol, Side and Trade group choosers (undrawn pickers; a
 * stored chip of those kinds still shows and removes), Manager and Env (BQ-10, BQ-7), the selection
 * bar and "Close all in view…" (E29-S03, BQ-3), the Updates-paused chip (D01 D13 b's hold), and
 * "Always shown" for the mandatory columns, which stay out of the picker meanwhile (BQ-6).
 *
 * The Working-orders tab (E29-S02) passes `end`: the FilterBar keeps its place, and the tab's own
 * controls (the selection bar, "Cancel all in view…") take the end's (D02 §4, §9.1). Group by, Columns
 * and Export CSV are the Positions tab's until their orders forms are built.
 */
import { useId, type JSX, type ReactNode } from "react";
import {
  AccountMultiSelect,
  Button,
  ColumnPicker,
  FilterBar,
  POSITIONS_GRID_COLUMNS,
  Select,
  type PositionsGridColumnId,
} from "@candleviewer/ui";
import { D02_TEXT } from "./copy";
import { positionCsvColumns } from "./csv";
import { chipLabel } from "./gridModel";
import type { FilterAction, FilterChip } from "./model/filters";
import type { GroupBy } from "./model/grouping";
import type { AccountInfo } from "./model/rowMapping";
import type { Density } from "./panelState";

/** The columns Account and Symbol always show (D02 §5.1): out of the picker until BQ-6's option. */
export const MANDATORY_COLUMNS: readonly PositionsGridColumnId[] = ["account", "symbol"];
/** The picker's columns, in D02 §5.1's order. */
export const OPTIONAL_COLUMNS: readonly PositionsGridColumnId[] = POSITIONS_GRID_COLUMNS.filter(
  (id) => !MANDATORY_COLUMNS.includes(id),
);

const HEADERS = positionCsvColumns(new Map());
/** A column's words in the picker: its D02 §5.1 header ("Entry (USDT)", "Liq dist. %"). */
export const columnLabel = (id: PositionsGridColumnId): string =>
  id === "status" ? "Status" : HEADERS[id].header;

const GROUP_OPTIONS: readonly { readonly value: GroupBy; readonly label: string }[] = [
  { value: "account", label: D02_TEXT.groupAccount.string },
  { value: "symbol", label: D02_TEXT.groupSymbol.string },
  { value: "trade_group", label: D02_TEXT.groupTradeGroup.string },
];

export interface ToolbarProps {
  /** The account directory, as the server scoped it. */
  readonly accounts: readonly AccountInfo[];
  readonly chips: readonly FilterChip[];
  readonly groupBy: GroupBy;
  /** The visible optional columns, in order. */
  readonly columns: readonly PositionsGridColumnId[];
  readonly onGroupBy: (by: GroupBy) => void;
  readonly onChips: (action: FilterAction) => void;
  readonly onColumns: (next: readonly PositionsGridColumnId[]) => void;
  readonly onExport: () => void;
  readonly density?: Density | undefined;
  /** The "+ Filter" trigger's id: where focus goes when a state's own Clear filters leaves. */
  readonly addFilterId?: string | undefined;
  /** The Working-orders tab's end controls, in place of Group by, Columns and Export CSV. */
  readonly end?: ReactNode;
}

export function Toolbar({
  accounts,
  chips,
  groupBy,
  columns,
  onGroupBy,
  onChips,
  onColumns,
  onExport,
  density,
  addFilterId,
  end,
}: ToolbarProps): JSX.Element {
  const groupById = useId();
  const directory = new Map(accounts.map((a) => [a.id, a]));
  const chosen = new Set(chips.filter((c) => c.kind === "account").map((c) => c.value));
  const accountChip = (id: string): FilterChip => ({ kind: "account", value: id });
  const shown = new Set(columns);
  return (
    <div className="cv-positions-toolbar" data-part="Toolbar">
      <div className="cv-positions-toolbar__start">
        {end === undefined ? (
          <>
            <span id={groupById} className="cv-positions-toolbar__label">
              {D02_TEXT.groupBy.string}
            </span>
            <Select
              aria-labelledby={groupById}
              options={GROUP_OPTIONS}
              value={groupBy}
              onChange={(value) => {
                const by = GROUP_OPTIONS.find((o) => o.value === value)?.value;
                if (by !== undefined && by !== groupBy) onGroupBy(by);
              }}
              {...(density === undefined ? {} : { density })}
            />
          </>
        ) : null}
        <FilterBar
          filters={chips.map((chip) => ({
            id: `${chip.kind}:${chip.value}`,
            label: chipLabel(chip, directory),
            onRemove: () => onChips({ type: "remove", chip }),
          }))}
          onClearAll={() => onChips({ type: "clear" })}
          addFilter={
            <AccountMultiSelect
              mode="account"
              trigger={
                <Button iconLeft="plus" {...(addFilterId === undefined ? {} : { id: addFilterId })}>
                  {D02_TEXT.addFilter.string}
                </Button>
              }
              accounts={accounts.map((a) => ({
                id: a.id,
                label: a.label,
                selected: chosen.has(a.id),
              }))}
              onToggle={(id) =>
                onChips({ type: chosen.has(id) ? "remove" : "add", chip: accountChip(id) })
              }
              onSelectAll={() =>
                onChips({
                  type: "replace",
                  chips: [
                    ...chips.filter((c) => c.kind !== "account"),
                    ...accounts.map((a) => accountChip(a.id)),
                  ],
                })
              }
              {...(density === undefined ? {} : { density })}
            />
          }
          {...(density === undefined ? {} : { density })}
        />
      </div>
      <div className="cv-positions-toolbar__end">
        {end ?? (
          <>
            <ColumnPicker
              variant="menu"
              label={D02_TEXT.columns.string}
              columns={OPTIONAL_COLUMNS.map((id) => ({
                id,
                label: columnLabel(id),
                visible: shown.has(id),
              }))}
              onChange={(id, visible) => {
                const next = OPTIONAL_COLUMNS.filter((c) => (c === id ? visible : shown.has(c)));
                onColumns(next);
              }}
            />
            <Button
              variant="secondary"
              onClick={onExport}
              {...(density === undefined ? {} : { density })}
            >
              {D02_TEXT.exportCsv.string}
            </Button>
          </>
        )}
      </div>
    </div>
  );
}
