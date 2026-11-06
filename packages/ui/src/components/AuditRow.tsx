import type { generated } from "@candleviewer/protocol";
import { useMemo, type JSX, type KeyboardEvent, type MouseEvent, type ReactNode } from "react";
import { Icon } from "../icons/Icon.js";
import { AuditDiff } from "./AuditDiff.js";
import { auditDiffModel, groupDigits } from "./auditDiffModel.js";
import { useFocusRing } from "./FocusRing.js";
import { cx } from "./internal/cx.js";
import type { LinkRoute } from "./Link.js";
import type { TableColumn, TableRowContext } from "./Table.js";

type AuditEntry = generated.rest.components["schemas"]["AuditEntry"];

/**
 * The words a compact row reads, keyed as E42-D04 §14 keys them: `labels.word.*` for severity (D2) and
 * outcome (D3), `audit.result_started` and `audit.result_intent` for a write-ahead record, and the "—" of an
 * absent actor. Times read in UTC with "UTC" after them (E42-D03 §1, Clocks).
 */
export const AUDIT_ROW_COPY = {
  outcome: { success: "Success", failure: "Failure", denied: "Denied" },
  severity: {
    critical: "Critical",
    error: "Error",
    warning: "Warning",
    info: "Info",
    debug: "Debug",
  },
  started: "Started",
  intent: "Intent",
  none: "—",
  utc: "UTC",
} as const;

/**
 * E42-D04 §14 `labels.action.*`, paired with their codes as D02 and D04 pair them (D02:191-193, :244-245,
 * :445 "Order submitted" ↔ `orders.submit`; D04:399, :642-643; D03 §14). The registry holds codes, not labels
 * (CG-3), so any other code reads as itself.
 */
export const AUDIT_ACTION_LABELS: Readonly<Record<string, string>> = {
  "admin.area_entered": "Area entered",
  "admin.audit_export": "Audit log exported",
  "admin.audit_read": "Audit log viewed",
  "flags.change": "Flag changed",
  "maintenance.disabled": "Maintenance off",
  "maintenance.enabled": "Maintenance on",
  "orders.submit": "Order submitted",
};

/** The value under `key`, only when it is the table's own (never a prototype member). */
const lookup = (table: Readonly<Record<string, string>>, key: string): string | undefined =>
  Object.hasOwn(table, key) ? table[key] : undefined;

const pad = (n: number): string => String(n).padStart(2, "0");

/** An RFC 3339 date-time: a full date, a time to the second, any fraction, and an offset (`Z` or ±hh:mm). */
const DATE_TIME = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/;

/**
 * `ts` (UTC, to the microsecond) as an instant to the millisecond, or `undefined` when it is not a full
 * date-time with an offset: the row never guesses a zone.
 */
function parseAuditTime(ts: string): Date | undefined {
  const match = DATE_TIME.exec(ts);
  if (match === null) return undefined;
  // `Date` reads a fraction of exactly three digits: cut or pad it to milliseconds.
  const fraction = match[1] ?? "";
  const ms = Date.parse(fraction === "" ? ts : ts.replace(fraction, `${fraction}00`.slice(0, 4)));
  return Number.isNaN(ms) ? undefined : new Date(ms);
}

/** "yyyy-mm-dd hh:mm:ss UTC" (E42-D03 §1, Clocks). */
function utcText(at: Date): string {
  const year = String(at.getUTCFullYear()).padStart(4, "0");
  const date = `${year}-${pad(at.getUTCMonth() + 1)}-${pad(at.getUTCDate())}`;
  const time = `${pad(at.getUTCHours())}:${pad(at.getUTCMinutes())}:${pad(at.getUTCSeconds())}`;
  return `${date} ${time} ${AUDIT_ROW_COPY.utc}`;
}

/**
 * `ts` as "yyyy-mm-dd hh:mm:ss UTC", whatever offset it was written with. A value that is not a full
 * date-time with an offset is shown as served.
 */
export function formatAuditTime(ts: string): string {
  const at = parseAuditTime(ts);
  return at === undefined ? ts : utcText(at);
}

/**
 * The row's time: a `time` element whose `datetime` is the instant to the millisecond (HTML allows three
 * fraction digits at most, the server writes microseconds), or the served value as plain text when it is
 * not a date-time.
 */
function AuditTime({ ts }: { readonly ts: string }): JSX.Element {
  const at = parseAuditTime(ts);
  if (at === undefined) return <span className="cv-audit-row__time">{ts}</span>;
  return (
    <time className="cv-audit-row__time" dateTime={at.toISOString()}>
      {utcText(at)}
    </time>
  );
}

/** D3: a write-ahead record reads "Started" or "Intent", never its outcome; a terminal one its outcome word. */
function outcomeWord(entry: AuditEntry): string {
  if (entry.reason === "started") return AUDIT_ROW_COPY.started;
  if (entry.detail.after?.["phase"] === "intent") return AUDIT_ROW_COPY.intent;
  return lookup(AUDIT_ROW_COPY.outcome, entry.outcome) ?? entry.outcome;
}

/**
 * A field boundary, " · " as the copy deck writes it ("All times UTC · as of 14:02:11"): plain text, so the dot
 * is in the link's name too, and the spaces either side let a line break there.
 */
function Sep(): JSX.Element {
  return (
    <>
      {" "}
      <span className="cv-audit-row__sep">·</span>{" "}
    </>
  );
}

export interface AuditRowProps {
  /** One entry, the type generated from `22`; the row shows its fields and derives no value of its own. */
  readonly entry: generated.rest.components["schemas"]["AuditEntry"];
  /** `compact`: a list item that links to SCR-136. The grid's `row` variant takes `AuditRowGridProps`. */
  readonly variant: "compact";
  /** SCR-136 for this entry: the host builds the route. Developer-built, never user input (CMP-021's rule). */
  readonly href: string;
  /** The app's router link, as CMP-021's `as`: `packages/ui` never imports a router. */
  readonly linkAs?: LinkRoute | undefined;
  /** Action labels by code, default `AUDIT_ACTION_LABELS`; a code without one reads as itself. */
  readonly actionLabels?: Readonly<Record<string, string>> | undefined;
}

/**
 * CMP-173 AuditRow (E42-D03 D9, D17; E42-D04 D2, D3, D14, §4 Columns, §6; `15` CMP-173). `compact`: one entry as a
 * list item whose whole text is one link to SCR-136 (render the rows inside `AuditRowList`). `row`: one entry as a
 * row of SCR-135's CMP-049 grid, drawn through its row contract (`AuditRowGridProps`); its expanded diff is the next
 * grid row, `AuditRowDiff`. Neither variant has an edit, delete or archive control.
 */
export function AuditRow(props: AuditRowProps | AuditRowGridProps): JSX.Element {
  return props.variant === "row" ? <GridRow {...props} /> : <CompactRow {...props} />;
}

/**
 * The compact variant (E42-D03 D9, D17, Appendix A; E42-D04 D2, D3): one entry as a list item whose whole text is
 * one link to SCR-136. It reads, in words and " · " apart: the time (UTC), the actor, the action's label and code, the
 * subject's label, the outcome and the severity; never a hash, an IP, a user agent or the `detail` diff, so an elided
 * or projected entry renders the same way. Error and critical are "high": the octagon, the word in semibold and a
 * `border.thick` rule; warning takes the triangle. Glyphs are `aria-hidden`: the words carry the meaning.
 */
function CompactRow({
  entry,
  variant,
  href,
  linkAs: Slot,
  actionLabels = AUDIT_ACTION_LABELS,
}: AuditRowProps): JSX.Element {
  const ring = useFocusRing();
  const label = lookup(actionLabels, entry.action);
  const subject = entry.subject_label ?? entry.subject_id;
  const severity = entry.severity;
  const glyph =
    severity === "critical" || severity === "error"
      ? "danger"
      : severity === "warning"
        ? "warning"
        : undefined;
  const content: ReactNode = (
    <span className="cv-audit-row__text">
      <AuditTime ts={entry.ts} />
      <Sep />
      <span className="cv-audit-row__actor">{entry.actor_username ?? AUDIT_ROW_COPY.none}</span>
      <Sep />
      {/* The brackets sit inside the code's span: an element edge never splits "(code)" in the name. */}
      <span className="cv-audit-row__action">
        {label === undefined ? null : <>{label} </>}
        <span className="cv-audit-row__code">
          {label === undefined ? entry.action : `(${entry.action})`}
        </span>
      </span>
      {subject === null ? null : (
        <>
          <Sep />
          <span className="cv-audit-row__subject">{subject}</span>
        </>
      )}
      <Sep />
      <span className="cv-audit-row__outcome">{outcomeWord(entry)}</span>
      <Sep />
      <span className="cv-audit-row__severity">
        {glyph === undefined ? null : (
          <span className="cv-audit-row__glyph" data-glyph={glyph}>
            <Icon name={glyph} />
          </span>
        )}
        {lookup(AUDIT_ROW_COPY.severity, severity) ?? severity}
      </span>
    </span>
  );
  const className = cx(ring.className, "cv-audit-row__link");
  return (
    <li className="cv-audit-row" data-cmp="CMP-173" data-variant={variant} data-severity={severity}>
      {Slot === undefined ? (
        <a className={className} href={href}>
          {content}
        </a>
      ) : (
        <Slot className={className} to={href}>
          {content}
        </Slot>
      )}
    </li>
  );
}

export interface AuditRowListProps {
  /** `AuditRow`s, newest first as the host read them. */
  readonly children: ReactNode;
  /** Names the list where nothing around it does (a tile's or a fieldset's heading usually does). */
  readonly "aria-label"?: string | undefined;
  readonly "aria-labelledby"?: string | undefined;
}

/** The list compact rows form (CMP-173 A11y): a plain `ul`, unmarked and unpadded, one row under another. */
export function AuditRowList({
  children,
  "aria-label": ariaLabel,
  "aria-labelledby": ariaLabelledBy,
}: AuditRowListProps): JSX.Element {
  return (
    <ul className="cv-audit-rows" aria-label={ariaLabel} aria-labelledby={ariaLabelledBy}>
      {children}
    </ul>
  );
}

/**
 * The grid's words: E42-D04 §14 `labels.col.*`, D17's "not recorded", `rec.hidden` and the environment words. PROPOSED
 * (no source gives it): `columns.expander`, the expander column's visually hidden header.
 */
export const AUDIT_GRID_COPY = {
  columns: {
    expander: "Details",
    time: "Time",
    actor: "Actor",
    role: "Role",
    action: "Action",
    target: "Target",
    environment: "Environment",
    ip: "IP",
    severity: "Severity",
    result: "Result",
  },
  notRecorded: "not recorded",
  hidden: "not shown in your view",
  environments: { live: "LIVE", demo: "DEMO", testnet: "TESTNET" },
} as const;

/** `labels.h` "Record {id}" (E42-D04 §14): the expander's name, the row it expands. */
export const auditRecordName = (id: number): string => `Record ${groupDigits(id)}`;

/** `rec.after_break` "Not verified — at or after the break at entry {n}." (E42-D04 AD-5). */
export const auditAfterBreakText = (id: number): string =>
  `Not verified — at or after the break at entry ${groupDigits(id)}.`;

/** A row of SCR-135's grid: an entry, or its expanded diff right under it (CMP-049 takes both in `rows`, AL-3). */
export type AuditGridRow =
  | { readonly kind: "entry"; readonly entry: AuditEntry }
  | { readonly kind: "diff"; readonly entry: AuditEntry };

/** The grid's rows, newest first as read: each expanded entry's diff row right after it. */
export const auditGridRows = (
  entries: readonly AuditEntry[],
  expanded: ReadonlySet<number>,
): AuditGridRow[] =>
  entries.flatMap((entry): AuditGridRow[] =>
    expanded.has(entry.id)
      ? [
          { kind: "entry", entry },
          { kind: "diff", entry },
        ]
      : [{ kind: "entry", entry }],
  );

/** A grid row's key: an entry's and its diff row's apart. */
export const auditGridRowKey = (row: AuditGridRow): string => `${row.kind}:${row.entry.id}`;

/**
 * The column ids and their 1280 widths in `em` (E42-D04 §4 Columns, 944 px in all), refitted to the pinned Inter and
 * CMP-049's 8 px cell padding (A-5520-09): D04's Result 64 and Environment 80 px wrapped "Success" mid-word and cut
 * the "Environment" header, so they take 72 and 92 px, and Target (144 to 128) and IP (104 to 100) give the room back;
 * no header or worked-example value is cut. A deviation from D04's widths, recorded for its owner.
 */
const GRID_COLUMNS = [
  ["expander", 1.5],
  ["time", 6.5],
  ["actor", 9],
  ["role", 3.5],
  ["action", 8],
  ["target", 8],
  ["environment", 5.75],
  ["ip", 6.25],
  ["severity", 6],
  ["result", 4.5],
] as const;

const AUDIT_COLUMNS: readonly TableColumn<AuditGridRow>[] = GRID_COLUMNS.map(([id, widthEm]) => ({
  id,
  header: AUDIT_GRID_COPY.columns[id],
  widthEm,
  minWidthEm: widthEm,
  cell: () => "",
  ...(id === "time" ? { order: "descending" as const } : {}),
  ...(id === "expander" ? { headerHidden: true } : {}),
}));

/**
 * SCR-135's columns for CMP-049 (E42-D04 §4 Columns): their 1280 widths (944 px in all) in `em` of the table's 16 px,
 * which are also their reflow minimums, so the grid stacks only when the content column is narrower (200 % zoom,
 * AL-28). Time states the fixed newest-first order (D6); the expander's header is visually hidden. The rows are the
 * host's `renderRow`: `AuditRow variant="row"` and `AuditRowDiff`. One list for every call, so a host may pass it on
 * every render.
 */
export function auditColumns(): readonly TableColumn<AuditGridRow>[] {
  return AUDIT_COLUMNS;
}

/** "yyyy-mm-dd hh:mm:ss.mmm" in UTC (the caption says UTC): D04 §4's Time, to the millisecond with the date. */
function gridTimeText(at: Date): string {
  const year = String(at.getUTCFullYear()).padStart(4, "0");
  const date = `${year}-${pad(at.getUTCMonth() + 1)}-${pad(at.getUTCDate())}`;
  const ms = String(at.getUTCMilliseconds()).padStart(3, "0");
  return `${date} ${pad(at.getUTCHours())}:${pad(at.getUTCMinutes())}:${pad(at.getUTCSeconds())}.${ms}`;
}

/** The read-time pseudonym of a purged user (CG-33): the grid cuts it to 4 hex and "…" (`rec.deleted_user`). */
const DELETED_USER = /^deleted-user-([0-9a-f]{12})$/;

/** The props of CMP-173's grid row (E42-D04 §4, D14; `15` CMP-173 Props). */
export interface AuditRowGridProps {
  readonly entry: AuditEntry;
  readonly variant: "row";
  /** CMP-049's row contract: `renderRow`'s second argument. */
  readonly grid: TableRowContext;
  /** The diff row shows under this one. */
  readonly expanded?: boolean;
  /** Space on the row, or a press on its expander, asks for the other state. */
  readonly onExpandedChange?: (expanded: boolean) => void;
  /** Enter on the row, or a press on a cell, opens SCR-136 (D14). */
  readonly onOpen: () => void;
  /** The id of this entry's diff row (`AuditRowDiff`'s `id`): the expander's `aria-controls` while expanded. */
  readonly diffId: string;
  /** The record SCR-136 shows (D14): `aria-selected` and the `check` glyph, never colour alone. */
  readonly selected?: boolean;
  /** `own`: a Manager's projection, whose nulled Environment and IP read "not shown in your view" (AL-25). */
  readonly view?: "raw" | "own";
  /** Focus entering the row, as ↑ / ↓ move it: the host keeps an open drawer on that record (D14). */
  readonly onRowFocus?: () => void;
  /** Action labels by code, default `AUDIT_ACTION_LABELS`; a code without one reads as itself. */
  readonly actionLabels?: Readonly<Record<string, string>> | undefined;
}

/**
 * A value the cell does not have: `rec.hidden` where the projection nulls it, else "—" for one not recorded, the dash
 * hidden from assistive technology and D17's "not recorded" read beside it, as the Role cell reads (A-5520-10).
 */
function Absent({ hidden }: { readonly hidden: boolean }): JSX.Element {
  if (hidden) return <span className="cv-audit-row__meta">{AUDIT_GRID_COPY.hidden}</span>;
  return (
    <span className="cv-audit-row__meta">
      <span aria-hidden="true">{AUDIT_ROW_COPY.none}</span>
      <span className="cv-visually-hidden">{AUDIT_GRID_COPY.notRecorded}</span>
    </span>
  );
}

/** Whether a press ended a text selection: the reader was selecting, not opening (D14). */
const selecting = (): boolean => {
  const selection = document.getSelection();
  return selection !== null && !selection.isCollapsed && selection.toString() !== "";
};

/**
 * CMP-173's grid row (E42-D04 §4 Columns, D2, D3, D14; `15` CMP-173 A11y), over CMP-049's row contract: the expander
 * (a button with `aria-expanded` and `aria-controls`, the 24 px column's one control), Time to the millisecond, Actor,
 * Role ("—", or "not recorded" where the column is wide), Action (its label, and its code under it where the column
 * is wide), Target, Environment, IP, Severity (the word; error and critical high: the octagon, semibold, the
 * `border.thick` rule; warning the triangle) and Result ("Started" or "Intent" for a write-ahead record). Space
 * expands from any cell and Enter opens SCR-136, once per press; a press on a cell opens it too, unless it ended a
 * text selection. The selected row is `aria-selected` with a `check` glyph before the chevron.
 */
function GridRow({
  entry,
  grid,
  expanded = false,
  onExpandedChange,
  onOpen,
  diffId,
  selected = false,
  view = "raw",
  onRowFocus,
  actionLabels = AUDIT_ACTION_LABELS,
}: AuditRowGridProps): JSX.Element {
  const ring = useFocusRing({ inset: true });
  const own = view === "own";
  const severity = entry.severity;
  const glyph =
    severity === "critical" || severity === "error"
      ? "danger"
      : severity === "warning"
        ? "warning"
        : undefined;
  const at = parseAuditTime(entry.ts);
  const label = lookup(actionLabels, entry.action);
  const subject = entry.subject_label ?? entry.subject_id;
  const target = [entry.subject_type, subject].filter(
    (part) => part !== null && part !== undefined,
  );
  const actor = entry.actor_username ?? null;
  const deleted = actor === null ? null : DELETED_USER.exec(actor);
  const environment = entry.environment ?? null;
  const ip = entry.ip ?? null;
  const toggleId = `${diffId}-toggle`;

  const onKeyDown = (event: KeyboardEvent<HTMLTableRowElement>): void => {
    if (event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey || event.shiftKey)
      return;
    if (event.key === "Enter") {
      // Enter opens the record: on the expander too, whose own click it cancels. A held key opens one.
      event.preventDefault();
      if (!event.repeat) onOpen();
    } else if (event.key === " ") {
      // The expander's own Space clicks it once, on keyup; a held key's repeats do nothing anywhere.
      const onToggle =
        event.target instanceof Element && event.target.closest(".cv-audit-row__toggle") !== null;
      if (onToggle && !event.repeat) return;
      event.preventDefault();
      if (!event.repeat) onExpandedChange?.(!expanded);
    }
  };
  const onClick = (event: MouseEvent<HTMLTableRowElement>): void => {
    if (event.defaultPrevented || selecting()) return;
    if (event.target instanceof Element && event.target.closest(".cv-audit-row__toggle") !== null)
      return;
    onOpen();
  };
  const cell = (index: number, options: Parameters<TableRowContext["cellProps"]>[1] = {}) =>
    grid.cellProps(index, { ...options, className: cx("cv-audit-row__cell", options.className) });

  return (
    <tr
      {...grid.rowProps}
      className={cx(grid.rowProps.className, "cv-audit-row")}
      data-cmp="CMP-173"
      data-variant="row"
      data-entry={entry.id}
      data-severity={severity}
      aria-selected={selected ? true : undefined}
      onKeyDown={onKeyDown}
      onClick={onClick}
      onFocus={onRowFocus === undefined ? undefined : () => onRowFocus()}
    >
      <td {...cell(0, { widget: true, className: "cv-audit-row__expander" })}>
        <button
          type="button"
          id={toggleId}
          className={cx(ring.className, "cv-audit-row__toggle")}
          tabIndex={grid.tabIndexOf(0)}
          aria-label={auditRecordName(entry.id)}
          aria-expanded={expanded}
          aria-controls={expanded ? diffId : undefined}
          onClick={() => onExpandedChange?.(!expanded)}
        >
          {selected ? (
            <span className="cv-audit-row__toggle-glyph" data-glyph="check">
              <Icon name="check" size="sm" />
            </span>
          ) : null}
          <span
            className="cv-audit-row__toggle-glyph"
            data-glyph={expanded ? "chevron-down" : "chevron-right"}
          >
            <Icon name={expanded ? "chevron-down" : "chevron-right"} size="sm" />
          </span>
        </button>
      </td>
      <td {...cell(1)}>
        {grid.label(1)}
        {at === undefined ? (
          <span className="cv-audit-row__mono">{entry.ts}</span>
        ) : (
          <time className="cv-audit-row__mono" dateTime={at.toISOString()}>
            {gridTimeText(at)}
          </time>
        )}
      </td>
      <td {...cell(2, deleted === null ? {} : { echo: actor ?? undefined })}>
        {grid.label(2)}
        {actor === null ? (
          <Absent hidden={false} />
        ) : deleted === null ? (
          actor
        ) : (
          <>
            <span aria-hidden="true">{`deleted-user-${(deleted[1] ?? "").slice(0, 4)}…`}</span>
            <span className="cv-visually-hidden">{actor}</span>
          </>
        )}
      </td>
      <td {...cell(3)}>
        {grid.label(3)}
        <div className="cv-audit-row__fit" data-fit="role">
          <span className="cv-audit-row__short cv-audit-row__meta" aria-hidden="true">
            {AUDIT_ROW_COPY.none}
          </span>
          <span className="cv-audit-row__long cv-audit-row__meta cv-visually-hidden">
            {AUDIT_GRID_COPY.notRecorded}
          </span>
        </div>
      </td>
      <td {...cell(4)}>
        {grid.label(4)}
        <div className="cv-audit-row__fit" data-fit="action">
          {label === undefined ? (
            <span className="cv-audit-row__code cv-audit-row__mono">{entry.action}</span>
          ) : (
            <>
              <span className="cv-audit-row__label">{label}</span>{" "}
              <span className="cv-audit-row__code cv-audit-row__mono cv-audit-row__long cv-visually-hidden">
                {entry.action}
              </span>
            </>
          )}
        </div>
      </td>
      <td {...cell(5)}>
        {grid.label(5)}
        {target.length === 0 ? <Absent hidden={false} /> : target.join(" · ")}
      </td>
      <td {...cell(6)}>
        {grid.label(6)}
        {environment === null ? (
          <Absent hidden={own} />
        ) : (
          // Its own attribute: the shell's env-badge guard reads `data-env` as a hide path (CI-5520-01).
          <span className="cv-audit-row__env" data-audit-env={environment}>
            {AUDIT_GRID_COPY.environments[environment]}
          </span>
        )}
      </td>
      <td {...cell(7)}>
        {grid.label(7)}
        {ip === null ? <Absent hidden={own} /> : <span className="cv-audit-row__mono">{ip}</span>}
      </td>
      <td {...cell(8)}>
        {grid.label(8)}
        <span className="cv-audit-row__severity">
          {glyph === undefined ? null : (
            <span className="cv-audit-row__glyph" data-glyph={glyph}>
              <Icon name={glyph} />
            </span>
          )}
          {lookup(AUDIT_ROW_COPY.severity, severity) ?? severity}
        </span>
      </td>
      <td {...cell(9)}>
        {grid.label(9)}
        {outcomeWord(entry)}
      </td>
    </tr>
  );
}

export interface AuditRowDiffProps {
  /** CMP-049's row contract: `renderRow`'s second argument. */
  readonly grid: TableRowContext;
  readonly entry: AuditEntry;
  /** The row's id: the expander's `aria-controls` (its `diffId`). */
  readonly id: string;
  /** The latest break's first bad entry (D11): an entry at or after it says it is not verified (AD-5). */
  readonly afterBreakId?: number;
  /** Space on the row asks to collapse it; focus moves to the entry's expander first. */
  readonly onExpandedChange?: (expanded: boolean) => void;
  /** Enter on the row opens the entry's record, as on the entry's row. */
  readonly onOpen?: () => void;
}

/**
 * CMP-173's expanded diff (E42-D04 AL-3, §6): the grid row under its entry, one CMP-049 composite cell over every
 * column holding the full diff (`AuditDiff`), whose Copy and disclosures the arrows reach as cells (→, ←; Enter or
 * Space acts). An entry at or after the latest break leads with `rec.after_break` in the danger treatment (AD-5),
 * never shown in the collapsed row. Space on the row collapses it, focus to the entry's expander; Enter opens SCR-136.
 * It is a part of its entry's CMP-173, whose row carries the one `data-cmp`.
 */
export function AuditRowDiff({
  grid,
  entry,
  id,
  afterBreakId,
  onExpandedChange,
  onOpen,
}: AuditRowDiffProps): JSX.Element {
  const model = useMemo(() => auditDiffModel(entry), [entry]);
  const afterBreak = afterBreakId !== undefined && entry.id >= afterBreakId;
  const onKeyDown = (event: KeyboardEvent<HTMLTableRowElement>): void => {
    if (event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey || event.shiftKey)
      return;
    if (event.target !== event.currentTarget.firstElementChild) return;
    if (event.key === " ") {
      event.preventDefault();
      if (event.repeat) return;
      document.getElementById(`${id}-toggle`)?.focus();
      onExpandedChange?.(false);
    } else if (event.key === "Enter") {
      event.preventDefault();
      if (!event.repeat) onOpen?.();
    }
  };
  return (
    <tr
      {...grid.rowProps}
      id={id}
      className={cx(grid.rowProps.className, "cv-audit-diff-row")}
      data-variant="diff"
      onKeyDown={onKeyDown}
    >
      <td
        {...grid.cellProps(0, {
          span: Number.MAX_SAFE_INTEGER,
          composite: true,
          className: "cv-audit-row__cell cv-audit-diff-row__cell",
        })}
      >
        {afterBreak ? (
          <p className="cv-audit-diff__break">
            <span className="cv-audit-diff__break-glyph">
              <Icon name="danger" />
            </span>
            {auditAfterBreakText(afterBreakId)}
          </p>
        ) : null}
        <AuditDiff model={model} form="full" />
      </td>
    </tr>
  );
}
