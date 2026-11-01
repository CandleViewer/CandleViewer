/**
 * SCR-142's region (e) (E16-D04 §4 `TIER/per-symbol`; D04-CG3, D04-D3; E16-D06 F-14): the hot tier's per-symbol
 * table, CMP-049's table variant (no APG grid: Tab reaches its one scroll region, and each Symbol the page lists once
 * SCR-140 has registered its row detail, where Purge… and the pin live, D04-D3), then the attribution line. Figures
 * carry their units in tabular numerals (F-14); "—" is read as its word. No table when the report lists no symbol.
 */
import type { JSX } from "react";
import { Table, Text, useFocusRing, type TableColumn } from "@candleviewer/ui";
import { fill } from "../copy";
import { PANEL_TEXT } from "./panelCopy";
import { STORAGE_DECK } from "./storageCopy";
import type { SymbolRow } from "./storageModel";

const [SIZE, SHARE, , GROWTH] = STORAGE_DECK["storage.tier.rows"];

export interface SymbolTableProps {
  readonly rows: readonly SymbolRow[];
  readonly attribution: string | null;
  /** SCR-140's row detail (`openRowDetail`, BQ-6), once registered. */
  readonly onOpen?: ((symbol: string) => void) | undefined;
  /** The symbols the page lists (its frame's and its status's): only their rows have a detail to open (C-486P3-12). */
  readonly listed: ReadonlySet<string>;
  /** The section's one polite region: the table renders none of its own (RG-13). */
  readonly announce: (text: string) => void;
}

/** A figure in tabular numerals, or "—" read as "no value". */
const figure = (text: string | null): JSX.Element =>
  text === null ? (
    <>
      <span aria-hidden="true">—</span>
      <span className="cv-visually-hidden">no value</span>
    </>
  ) : (
    <span className="cv-num" data-size="sm">
      {text}
    </span>
  );

export function SymbolTable({
  rows,
  attribution,
  onOpen,
  listed,
  announce,
}: SymbolTableProps): JSX.Element | null {
  // The cell clips at its edge (`overflow: hidden`): the DS's inset ring (H8) is drawn inside (A-486P3-01).
  const ring = useFocusRing({ inset: true });
  if (rows.length === 0) return null;
  const columns: readonly TableColumn<SymbolRow>[] = [
    {
      id: "symbol",
      header: PANEL_TEXT.importSymbol,
      cell: (row) =>
        onOpen === undefined || !listed.has(row.symbol) ? (
          row.symbol
        ) : (
          // Its name leads with the visible symbol and says what it opens, a dialog (A-486P3-06; SC 2.5.3); the
          // padding keeps the inset ring off the glyphs (A-486P3-01).
          <button
            type="button"
            className={`cv-link ${ring.className}`}
            style={{ padding: "0 var(--space-inset-xs)", border: 0, background: "none" }}
            aria-label={fill(PANEL_TEXT.openDetail, { "{symbol}": row.symbol })}
            aria-haspopup="dialog"
            onClick={() => onOpen(row.symbol)}
          >
            {row.symbol}
          </button>
        ),
    },
    { id: "size", header: SIZE, cell: (row) => figure(row.size), align: "end" },
    { id: "growth", header: GROWTH, cell: (row) => figure(row.growth), align: "end" },
    { id: "share", header: SHARE, cell: (row) => figure(row.share), align: "end" },
    {
      id: "pinned",
      header: PANEL_TEXT.pinnedColumn,
      cell: (row) =>
        row.pinned ? (
          PANEL_TEXT.pinned
        ) : (
          <>
            <span aria-hidden="true">—</span>
            <span className="cv-visually-hidden">{PANEL_TEXT.notPinned}</span>
          </>
        ),
    },
  ];
  return (
    <div style={{ display: "grid", gap: "var(--space-stack-xs)" }}>
      <Table
        columns={columns}
        rows={rows}
        rowKey={(row) => row.symbol}
        caption={PANEL_TEXT.symbolsCaption}
        announce={announce}
      />
      {attribution === null ? null : (
        <Text as="p" tone="secondary">
          {attribution}
        </Text>
      )}
    </div>
  );
}
