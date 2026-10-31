/**
 * The FilterBar's chips (CMP-055; E29-D02 §9.1, US-POS-006): "Account: Sub-1", "Symbol: BTCUSDT",
 * "Side: Long" and a trade group, each removable, "Clear all" from two on. A view filter only:
 * the server scopes what the client may read, and the client never filters for security (the
 * ticket's security note). One environment per server (BQ-7), so no Env chip; no Manager (BQ-10).
 * Chips of one kind are alternatives (Account: Sub-1 or Sub-2); different kinds narrow together.
 */
import { isUuid, type PositionRowModel, type Side } from "./rowMapping";

export type FilterKind = "account" | "symbol" | "side" | "trade_group";

export interface FilterChip {
  readonly kind: FilterKind;
  /** An account or trade-group id (lower-case UUID), a symbol, or `long` / `short`. */
  readonly value: string;
}

export type FilterAction =
  | { readonly type: "add"; readonly chip: FilterChip }
  | { readonly type: "remove"; readonly chip: FilterChip }
  | { readonly type: "clear" }
  | { readonly type: "replace"; readonly chips: readonly FilterChip[] };

/** The FilterBar shows "Clear all" from this many chips (D02 §9.1). */
export const CLEAR_ALL_FROM = 2;
/** A bound on the chips one view holds, so a crafted deep link or a stored state stays small. */
export const MAX_CHIPS = 32;

const SYMBOL = /^[A-Z0-9]{2,20}USDT$/;
const KINDS: readonly FilterKind[] = ["account", "symbol", "side", "trade_group"];

/** The chip in its canonical form, or `null` for one that names nothing a row can hold. */
export function normaliseChip(raw: unknown): FilterChip | null {
  if (typeof raw !== "object" || raw === null) return null;
  const { kind, value } = raw as { kind?: unknown; value?: unknown };
  const k = KINDS.find((x) => x === kind);
  if (k === undefined || typeof value !== "string") return null;
  switch (k) {
    case "account":
    case "trade_group":
      return isUuid(value) ? { kind: k, value: value.toLowerCase() } : null;
    case "symbol":
      return SYMBOL.test(value) ? { kind: k, value } : null;
    case "side":
      return value === "long" || value === "short" ? { kind: k, value } : null;
  }
}

const same = (a: FilterChip, b: FilterChip): boolean => a.kind === b.kind && a.value === b.value;

/** Normalised, without duplicates, in order, at most `MAX_CHIPS`. */
function tidy(chips: readonly unknown[]): readonly FilterChip[] {
  const out: FilterChip[] = [];
  for (const raw of chips) {
    const chip = normaliseChip(raw);
    if (chip !== null && !out.some((c) => same(c, chip)) && out.length < MAX_CHIPS) out.push(chip);
  }
  return out;
}

/** The chip list after `action`; the list itself when nothing changes (a store compares by reference). */
export function reduceFilters(
  chips: readonly FilterChip[],
  action: FilterAction,
): readonly FilterChip[] {
  switch (action.type) {
    case "add": {
      const chip = normaliseChip(action.chip);
      if (chip === null || chips.some((c) => same(c, chip)) || chips.length >= MAX_CHIPS)
        return chips;
      return [...chips, chip];
    }
    case "remove": {
      const next = chips.filter((c) => !same(c, action.chip));
      return next.length === chips.length ? chips : next;
    }
    case "clear":
      return chips.length === 0 ? chips : [];
    case "replace":
      return tidy(action.chips);
  }
}

function matches(row: PositionRowModel, chip: FilterChip): boolean {
  switch (chip.kind) {
    case "account":
      return row.accountId === chip.value;
    case "symbol":
      return row.symbol === chip.value;
    case "side":
      return row.side === (chip.value as Side);
    case "trade_group":
      return row.tradeGroupId === chip.value;
  }
}

/** The rows the chips leave in view: any chip of a kind, and every kind present. */
export function applyFilters(
  rows: readonly PositionRowModel[],
  chips: readonly FilterChip[],
): readonly PositionRowModel[] {
  if (chips.length === 0) return rows;
  const kinds = KINDS.filter((k) => chips.some((c) => c.kind === k));
  return rows.filter((row) =>
    kinds.every((k) => chips.some((c) => c.kind === k && matches(row, c))),
  );
}

export const showsClearAll = (chips: readonly FilterChip[]): boolean =>
  chips.length >= CLEAR_ALL_FROM;
