/**
 * The Positions tab's view as CMP-114 draws it (E29-S01 #911): the model's groups, rows and totals
 * (`model/view.ts`) with the words the group header and the totals row read (D02 §5.5, D-15), and
 * the FilterBar's chip words (D02 §9.1). Pure: the panel passes what it holds and draws the result.
 *
 * - **Group headers:** an account group reads "Main · LIVE" with its position mode (CMP-129,
 *   `display`); a symbol group its symbol; a trade group its id's stub, "Trade group …0001", and the
 *   positions with none "No trade group" (both PROPOSED: no design names a trade group's header).
 * - **Totals:** "LIVE total" / "DEMO total" (D02:142, :209); a testnet session's label is PROPOSED.
 *   The row is the model's (count, exposure, uPnL, rPnL today; never a size across symbols, D-15).
 * - **Environment words:** LIVE and DEMO (D02:238, :209); TESTNET is the shell badge's PROPOSED word.
 */
import type { ReactNode } from "react";
import type {
  PositionMode,
  PositionsGridGroup,
  PositionsGridLiq,
  PositionsGridTotals,
} from "@candleviewer/ui";
import { D02_TEXT, PROPOSED_TEXT } from "./copy";
import type { FilterChip } from "./model/filters";
import type { GroupModel, TotalsModel } from "./model/grouping";
import type { LiqReading } from "./model/liqTier";
import type { AccountInfo, Environment, PositionRowModel } from "./model/rowMapping";

/** A model row with its liquidation reading beside it: what CMP-114 draws. */
export type GridRow = PositionRowModel & { readonly liq: PositionsGridLiq };

const ENV_WORDS: Readonly<Record<Environment, string>> = {
  live: D02_TEXT.envLive.string,
  demo: D02_TEXT.envDemo.string,
  testnet: PROPOSED_TEXT.envTestnet,
};

/** The environment's word in a label ("Main · LIVE"); "—" while the session's is not known. */
export const envWord = (environment: Environment | null): string =>
  environment === null ? "—" : ENV_WORDS[environment];

/** The totals row's label (D-15), `null` while the environment is unknown (no row is labelled). */
export function totalsLabel(environment: Environment | null): string | null {
  switch (environment) {
    case "live":
      return D02_TEXT.liveTotal.string;
    case "demo":
      return D02_TEXT.demoTotal.string;
    case "testnet":
      return PROPOSED_TEXT.testnetTotal;
    case null:
      return null;
  }
}

/** An id's stub, its last four characters after an ellipsis ("…0001"), as D03 shows an order's. */
export const idStub = (id: string): string => `…${id.slice(-4)}`;

/** A trade group's header words (PROPOSED). */
export const tradeGroupLabel = (id: string | null): string =>
  id === null
    ? PROPOSED_TEXT.noTradeGroup
    : PROPOSED_TEXT.tradeGroupLabel.replace("…{stub}", idStub(id));

/** An account's words: its label, else its id's stub (an account the directory does not name). */
export const accountWords = (id: string, accounts: ReadonlyMap<string, AccountInfo>): string =>
  accounts.get(id)?.label ?? idStub(id);

const NO_READING: PositionsGridLiq = Object.freeze({ tier: "none", distancePct: null });

/** A row as the grid draws it: the model's row and its tier reading. */
export const gridRow = (row: PositionRowModel, reading: LiqReading | undefined): GridRow => ({
  ...row,
  liq: reading ?? NO_READING,
});

const MODE_WORDS: Readonly<Record<NonNullable<AccountInfo["positionMode"]>, PositionMode>> = {
  one_way: "one-way",
  hedge: "hedge",
};

export interface GridGroupInputs {
  readonly groups: readonly GroupModel[];
  readonly accounts: ReadonlyMap<string, AccountInfo>;
  readonly liq: ReadonlyMap<string, LiqReading>;
  /** The session's environment: an account the directory does not name reads it. */
  readonly environment: Environment | null;
  /** An account group's state marker and read-only notice (BQ-14, D02 §10.4), else none. */
  readonly markerOf?: ((accountId: string) => ReactNode) | undefined;
}

/** The model's groups as CMP-114's: the header's words, the position mode, the marker, the rows. */
export function gridGroups(inputs: GridGroupInputs): readonly PositionsGridGroup<GridRow>[] {
  const { accounts, liq, environment } = inputs;
  return inputs.groups.map((group) => {
    const rows = group.rows.map((row) => gridRow(row, liq.get(row.key)));
    const base = {
      key: group.key,
      rows,
      count: group.count,
      unrealisedPnl: group.unrealisedPnl,
      realisedToday: group.realisedToday,
      netSize: group.netSize,
    };
    if (group.by === "symbol") return { ...base, label: group.key ?? "" };
    if (group.by === "trade_group") return { ...base, label: tradeGroupLabel(group.key) };
    const id = group.key ?? "";
    const account = accounts.get(id);
    const mode = account?.positionMode;
    const marker = inputs.markerOf?.(id);
    return {
      ...base,
      label: `${accountWords(id, accounts)} · ${envWord(account?.environment ?? environment)}`,
      ...(mode === null || mode === undefined ? {} : { positionMode: MODE_WORDS[mode] }),
      ...(marker === undefined || marker === null ? {} : { marker }),
    };
  });
}

/** The model's totals as CMP-114's row; none while nothing is in view or the label is unknown. */
export function gridTotals(
  totals: TotalsModel,
  environment: Environment | null,
): PositionsGridTotals | undefined {
  const label = totalsLabel(environment);
  if (label === null || totals.count === 0) return undefined;
  return {
    label,
    count: totals.count,
    exposure: totals.exposure,
    unrealisedPnl: totals.unrealisedPnl,
    realisedToday: totals.realisedToday,
  };
}

const SIDE_WORDS = { long: "Long", short: "Short" } as const;

/** A chip's words, "Account: Sub-1", "Symbol: BTCUSDT", "Side: Long" (D02:375); a trade group's PROPOSED. */
export function chipLabel(chip: FilterChip, accounts: ReadonlyMap<string, AccountInfo>): string {
  switch (chip.kind) {
    case "account":
      return `${D02_TEXT.chipAccount.string}: ${accountWords(chip.value, accounts)}`;
    case "symbol":
      return `${D02_TEXT.chipSymbol.string}: ${chip.value}`;
    case "side":
      return `${D02_TEXT.chipSide.string}: ${chip.value === "short" ? SIDE_WORDS.short : SIDE_WORDS.long}`;
    case "trade_group":
      return `${D02_TEXT.groupTradeGroup.string}: ${idStub(chip.value)}`;
  }
}

/** Filter-empty's restated chips, "Account: Sub-1 · Symbol: SOLUSDT" (D02:380). */
export const chipsRestated = (
  chips: readonly FilterChip[],
  accounts: ReadonlyMap<string, AccountInfo>,
): string => chips.map((chip) => chipLabel(chip, accounts)).join(" · ");
