/**
 * The fills' CSV (E29-S04 #979; E29-D03 §3.8, D-11; E29-D02 D-21): every fill in scope (the caller
 * pages them all, never the rendered window) in D03:200's column order, decimals raw as the
 * contract carries them (no `+`, no grouping; `fee` positive when paid), text guarded against
 * formula injection and quoted per RFC 4180 by `../csv.ts`. Line 1 is `fills.export.watermark`,
 * naming the exporting identity, the accounts and the time, "not the audit trail" (SR-098, BQ-4):
 * the file is built here, and its audit record waits for G7's server path (D03 OQ-10).
 */
import { toCsv, type CsvColumn } from "../csv";
import { bindEntry, D03_TEXT, DECK, PROPOSED_TEXT } from "./copy";
import { liquidityOf, type FillRowModel } from "./model/fillRow";

/** Where a row's account label and environment come from (the caller's directory). */
export type AccountOf = (
  accountId: string,
) => { readonly label: string; readonly environment: string } | null;

/** D03:200's columns, in order, with what each writes. */
export function fillColumns(accountOf: AccountOf): readonly CsvColumn<FillRowModel>[] {
  const text = (header: string, value: (r: FillRowModel) => string | null) =>
    ({ header, kind: "text", value }) as const;
  const number = (header: string, value: (r: FillRowModel) => string | null) =>
    ({ header, kind: "number", value }) as const;
  const liquidity = (r: FillRowModel): string | null => {
    const l = liquidityOf(r);
    return l === "maker" || l === "taker" ? l : null;
  };
  return [
    text("time_utc", (r) => new Date(r.tsMs).toISOString()),
    text("account", (r) => accountOf(r.accountId)?.label ?? null), // never an id the screen hides
    text("environment", (r) => r.environment ?? accountOf(r.accountId)?.environment ?? null),
    text("symbol", (r) => r.symbol),
    text("side", (r) => r.side),
    text("type", (r) => r.execType),
    number("price", (r) => r.price),
    number("qty", (r) => r.qty),
    number("value", (r) => r.value),
    number("fee", (r) => r.fee),
    text("fee_currency", (r) => r.feeCoin),
    number("fee_rate", (r) => r.feeRate),
    text("liquidity", liquidity),
    number("closed_pnl", (r) => r.closedPnl),
    text("exec_id", (r) => r.execId),
    text("order_id", (r) => r.orderId),
    text("trade_group_id", (r) => r.tradeGroupId ?? null),
  ];
}

export interface WatermarkInput {
  readonly displayName: string;
  readonly role: "owner" | "manager" | "viewer";
  /** The user a view-as session shows (D03:301's "viewing as alex"). */
  readonly viewingAs?: string | null;
  /** The labels of the accounts in scope: a Manager's are theirs alone (D-8). */
  readonly accounts: readonly string[];
  /** The ENV pill's word ("LIVE", "DEMO"): one environment per server (#911 BQ-7). */
  readonly environment: string;
  readonly atMs: number;
}

/**
 * The role in the watermark: the deck's "(Owner)", D03:301's "(Manager)" (`D03_TEXT
 * .exportedByManager`) and a PROPOSED "(Viewer)" (`PROPOSED_TEXT.exportedByViewer`); a test holds
 * each to its source.
 */
export const ROLE_PART = { owner: "(Owner)", manager: "(Manager)", viewer: "(Viewer)" } as const;

/**
 * Line 1 of the file. The deck string's four " · " parts are bound one at a time, so a user's
 * name or a label can never be read as a later span; the accounts follow D03:301's list form
 * ("Sub-1 (LIVE), Sub-2 (LIVE)").
 */
export function watermark(input: WatermarkInput): string {
  const entry = DECK["fills.export.watermark"];
  const at = new Date(input.atMs).toISOString().replace("T", " ").slice(0, 19);
  const values: Readonly<Record<string, string>> = {
    "{display name}": input.displayName,
    Main: input.accounts.join(` (${input.environment}), `),
    LIVE: input.environment,
    "2026-10-22 14:05:09": at,
  };
  const parts = entry.string.split(" · ").map((part, i) => {
    const params = Object.fromEntries(
      Object.entries(entry.params ?? {}).filter(([span]) => part.includes(span)),
    );
    const shaped = i === 1 ? part.replace("(Owner)", ROLE_PART[input.role]) : part;
    const bound = bindEntry({ string: shaped, params }, values);
    const viewing = input.viewingAs ?? null;
    return i === 1 && viewing !== null
      ? bound + bindEntry(D03_TEXT.viewingAs, { alex: viewing })
      : bound;
  });
  return parts.join(" · ");
}

/** The file's text: the watermark line, the header, then one line per fill (CRLF, D02 D-21). */
export function fillsCsv(
  rows: readonly FillRowModel[],
  accountOf: AccountOf,
  mark: WatermarkInput,
): string {
  const first = toCsv([], [{ header: watermark(mark), kind: "text", value: () => null }]);
  return first + toCsv(rows, fillColumns(accountOf));
}

/** `20261022T140509Z`: the file name's stamp. */
const stamp = (atMs: number): string =>
  `${new Date(atMs).toISOString().slice(0, 19).replace(/[-:]/g, "")}Z`;

/** D03:200's name for an order's export; the tab's is PROPOSED (`PROPOSED_TEXT.tabFileName`). */
export function fillsCsvName(atMs: number, orderId?: string): string {
  if (orderId === undefined)
    return bindEntry(PROPOSED_TEXT.tabFileName, { "20261022T140509Z": stamp(atMs) });
  return bindEntry(D03_TEXT.fileName, { a3f2: orderId.slice(-4), "20261022T140509Z": stamp(atMs) });
}
