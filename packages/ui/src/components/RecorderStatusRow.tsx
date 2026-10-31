import { useId, useRef, useState, type JSX, type KeyboardEvent, type ReactNode } from "react";
import { Icon } from "../icons/Icon.js";
import { Badge } from "./Badge.js";
import { useFocusRing } from "./FocusRing.js";
import { IconButton } from "./IconButton.js";
import { Popover } from "./Popover.js";
import { RbacGate, type RbacGateChild } from "./RbacGate.js";
import { Spinner } from "./Spinner.js";
import type { TableColumn } from "./Table.js";
import { Tag } from "./Tag.js";
import { cx } from "./internal/cx.js";
import { useGatedAnnounce } from "./internal/disabledReason.js";
import { ReasonEcho } from "./internal/ReasonEcho.js";
import { formatRbacReason } from "./rbacReasons.js";

export type RecorderReason =
  "manual" | "chart_open" | "position_open" | "rule_dependency" | "alert_dependency";

/** The row state (E16-D02 §4.1): the host derives it from `state`, `lingering`, `refusal` and the write gate. */
export type RecorderRowState =
  | "starting"
  | "recording"
  | "lingering"
  | "degraded"
  | "gated"
  | "refused"
  | "silent"
  | "error"
  | "stopping"
  | "stopped";

/** CMP-177's values and actions (E16-D02 §4.2), as the server sends them: the row decides nothing (C-12.4). */
export interface RecorderStatusRowData {
  readonly symbol: string;
  readonly reason: RecorderReason;
  readonly state: RecorderRowState;
  /** ISO time the linger ends: "stops in N min" against `now`. */
  readonly lingerUntil?: string | null;
  /** A refused start's cause (`state` refused). */
  readonly refusal?: "symbol_cap" | "disk_pressure" | null;
  /** The row's own stop refusal, never `reason`: Stop is T2 with the §8.5 key `reason` picks. */
  readonly stopBlockedReason?: "chart_open" | "position_open" | null;
  /** The active rows reach the limit: Record again is T2 (`state` stopped). */
  readonly recordAgainBlockedReason?: "symbol_cap" | null;
  readonly startedAt?: string | null;
  /** The last session's `ended_at`: with `retentionDays`, "gone by". */
  readonly stoppedAt?: string | null;
  readonly depth?: 1 | 50 | 200 | 500 | null;
  readonly dailyGrowthBytes?: number | null;
  /** "est." until an hour of data exists. */
  readonly growthEstimated?: boolean;
  readonly diskUsageBytes?: number | null;
  /** The share of the cap (0–1); from `diskLevel` 1 the Size adds "· N % of budget" (NearDiskBudget). */
  readonly budgetShare?: number | null;
  readonly diskLevel?: 0 | 1 | 2 | 3;
  readonly retentionDays?: number | null;
  readonly pinned?: boolean;
  /** No `recorder` frame for 2 s: the sunken row and a "stale" tag; the words are kept. */
  readonly stale?: boolean;
  /** As built: §4.1's words with no §4.2 prop. Silent's last write (`last_event_at`). */
  readonly lastEventAt?: string | null;
  /** As built: gaps in the last 24 h ("· 2 gaps in 24 h"). */
  readonly gapCount?: number;
  /** As built: `policy.max_symbols` ("20-symbol limit"); default 20. */
  readonly symbolLimit?: number;
  /** As built: `policy.autostop_grace_s`, `recorder.stop_blocked.chart_auto`'s `{grace}`; default 1800. */
  readonly graceSeconds?: number;
  /** The Why? popover's words (D02 §5.1), the host's from its deck; auto rows only. */
  readonly why?: string;
  /** The host's clock (ms), default `Date.now()`: the linger's minutes. */
  readonly now?: number;
  readonly onStop?: () => void;
  readonly onKeepRecording?: () => void;
  readonly onRecordAgain?: () => void;
  /** Asks for the other value; the host confirms and steps up (D02 §6.4). */
  readonly onTogglePin?: (pinned: boolean) => void;
  /** A press on the symbol: the row detail (D02 §6.7). */
  readonly onOpenDetail?: () => void;
  /** The Why? popover opened (`recorder.auto_review_opened`, D02 §12). */
  readonly onWhyOpen?: () => void;
}

/** What a cell asks of the host's grid (#5146's CMP-049 `TableCellOptions` takes both). */
export interface RecorderCellOptions {
  /** The symbol: the row's header (`th scope="row"`). */
  readonly header?: boolean;
  /** Since, Depth and Size: end-aligned numbers (D02 §9.1). */
  readonly numeric?: boolean;
}

/** What the host spreads on a cell (a subset of #5146's `TableCellProps`): its role and roving `tabindex`. */
export interface RecorderCellProps {
  readonly className: string;
  readonly role?: string | undefined;
  readonly scope?: "row" | undefined;
  readonly tabIndex?: 0 | -1 | undefined;
  readonly "data-numeric"?: "" | undefined;
}

/**
 * The host grid's row contract (BQ-9: CMP-049's `renderRow`; #5146's `TableRowContext` satisfies it). The row draws
 * its nine cells in `recorderStatusColumns()`' order; the grid owns the header row, the arrows, the one Tab stop and
 * the roving `tabindex`. A cell with controls carries `data-cv-interactive`, CMP-049's interactive cell: Enter or F2
 * moves into its controls, Esc back out, and its controls leave the Tab order while the grid roves.
 */
export interface RecorderRowGrid {
  readonly rowProps: {
    readonly className: string;
    readonly role?: string | undefined;
    readonly "aria-rowindex": number;
  };
  readonly cellProps: (column: number, options?: RecorderCellOptions) => RecorderCellProps;
  /** Stacked, the visible header label a cell leads with. */
  readonly label: (column: number) => ReactNode;
}

/** SCR-140: a `row` of the host's grid. `ReadOnly` is the standalone variant's alone (D02 §4.2). */
interface TableVariant {
  readonly variant: "table";
  readonly grid: RecorderRowGrid;
  readonly writeReason?: never;
  readonly viewAsUser?: never;
}

/** SCR-103: a card; the session's write leg makes every write T2 under one notice (E09-D09 §2.3). */
interface StandaloneVariant {
  readonly variant?: "standalone";
  readonly grid?: never;
  readonly writeReason?: "rbac.owner_only" | "rbac.view_as" | null;
  /** `rbac.view_as`'s `{user}`. */
  readonly viewAsUser?: string;
}

export type RecorderStatusRowProps = RecorderStatusRowData & (TableVariant | StandaloneVariant);

/** E16-D02 §8.5's T2 reasons, PROPOSED state keys `recorder.*`, verbatim. */
export const RECORDER_REASONS = {
  "recorder.stop_blocked.chart_auto": "Recording stops {grace} after the last chart closes.",
  "recorder.stop_blocked.chart_manual": "Stop is available once the last chart closes.",
  "recorder.stop_blocked.position_auto": "Recording continues while a position is open.",
  "recorder.stop_blocked.position_manual": "Stop is unavailable while a position is open.",
  "recorder.symbol_cap": "The symbol limit is reached.",
} as const;

const TAGS: Readonly<Record<RecorderReason, string>> = {
  manual: "Manual",
  chart_open: "Auto: chart",
  position_open: "Auto: position",
  rule_dependency: "Auto: rule",
  alert_dependency: "Auto: alert",
};
type Tone = "success" | "warning" | "danger" | "info";
const TONES: Partial<Record<RecorderRowState, Tone>> = {
  starting: "info",
  recording: "success",
  lingering: "success",
  degraded: "warning",
  gated: "danger",
  silent: "danger",
  error: "danger",
};
const ACTIVE = new Set<RecorderRowState>([
  "recording",
  "lingering",
  "degraded",
  "gated",
  "silent",
  "error",
]);
const DASH = "—";
const MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split(" ");
const UNITS = [
  [1e9, "GB"],
  [1e6, "MB"],
  [1e3, "KB"],
] as const;

const at = (iso: string | null | undefined): Date | undefined => {
  const ms = iso == null ? Number.NaN : Date.parse(iso);
  return Number.isNaN(ms) ? undefined : new Date(ms);
};
const dayMonth = (d: Date): string => `${d.getUTCDate()} ${MONTHS[d.getUTCMonth()] ?? ""}`;
const bytes = (n: number): string => {
  for (const [size, unit] of UNITS) if (n >= size) return `${(n / size).toFixed(1)} ${unit}`;
  return `${n} B`;
};
/** D02 §8: "60 s", "30 min", "1 h 30 min". */
const duration = (s: number): string => {
  const m = Math.round(s / 60);
  if (s < 60) return `${s} s`;
  return m < 60 ? `${m} min` : `${Math.floor(m / 60)} h${m % 60 === 0 ? "" : ` ${m % 60} min`}`;
};
const gaps = (n = 0): string => (n > 0 ? ` · ${n} ${n === 1 ? "gap" : "gaps"} in 24 h` : "");
const lower = (s: string): string => s.charAt(0).toLowerCase() + s.slice(1);
const hidden = (text: string): JSX.Element => <span className="cv-visually-hidden">{text}</span>;

/** The state cell's words (E16-D02 §4.1, §8.2); the tone is the icon's. */
function wordsOf(p: RecorderStatusRowData): string {
  switch (p.state) {
    case "starting":
      return "Starting · initial book snapshot";
    case "recording": {
      const position = p.reason === "position_open" ? " · position" : " · position open";
      return `Recording${p.stopBlockedReason === "position_open" ? position : ""}${gaps(p.gapCount)}`;
    }
    case "lingering": {
      const left = (at(p.lingerUntil)?.getTime() ?? 0) - (p.now ?? Date.now());
      return `Recording · stops in ${left < 60e3 ? "under a minute" : `${Math.ceil(left / 60e3)} min`}`;
    }
    case "degraded":
      return `Degraded · stream unhealthy${gaps(p.gapCount)}`;
    case "gated":
      return "Gated · data dropped";
    case "refused":
      return p.refusal === "disk_pressure"
        ? "Not recording: disk nearly full"
        : `Not recording: ${p.symbolLimit ?? 20}-symbol limit reached`;
    case "silent":
      return `No writes since ${at(p.lastEventAt)?.toISOString().slice(11, 19) ?? DASH}`;
    case "error":
      return "Error · retrying";
    case "stopping":
      return "Stopping · flushing to disk";
    case "stopped": {
      const end = at(p.stoppedAt);
      if (end === undefined) return "Stopped";
      if (p.pinned === true) return `Stopped ${dayMonth(end)} · kept forever`;
      if (p.retentionDays == null) return `Stopped ${dayMonth(end)}`;
      const gone = new Date(end.getTime() + p.retentionDays * 864e5);
      return `Stopped ${dayMonth(end)} · gone by ${dayMonth(gone)}`;
    }
  }
}

const sinceOf = (p: RecorderStatusRowData): string =>
  at(p.startedAt)?.toISOString().slice(0, 10) ?? DASH;
const depthOf = (p: RecorderStatusRowData): string =>
  p.state === "refused" || p.depth == null ? DASH : String(p.depth);
const retentionOf = (p: RecorderStatusRowData): string =>
  p.state === "refused"
    ? DASH
    : p.pinned === true
      ? "Forever"
      : p.retentionDays == null
        ? DASH
        : `${p.retentionDays} d`;

/** "34.8 GB · 0.71/d", "est." while estimated, "· 17 % of budget" from disk level 1; "—" with nothing written. */
function sizeOf(p: RecorderStatusRowData): string {
  if (p.state === "refused" || p.state === "starting") return DASH;
  const g = p.state === "stopped" ? null : p.dailyGrowthBytes;
  const rate =
    g == null ? "" : ` · ${(g / 1e9).toFixed(2)}/d${p.growthEstimated === true ? " est." : ""}`;
  const share = (p.diskLevel ?? 0) >= 1 && p.budgetShare != null;
  return `${bytes(p.diskUsageBytes ?? 0)}${rate}${share ? ` · ${Math.round((p.budgetShare ?? 0) * 100)} % of budget` : ""}`;
}

/** The row's name (D02H table 3): "BTCUSDT, manual, recording since 1 Sep 2026, 34.8 GB, keep forever on". */
function recorderStatusSummary(p: RecorderStatusRowData): string {
  const start = ACTIVE.has(p.state) ? at(p.startedAt) : undefined;
  const since = start === undefined ? "" : ` since ${dayMonth(start)} ${start.getUTCFullYear()}`;
  const parts = [p.symbol, lower(TAGS[p.reason]), `${lower(wordsOf(p))}${since}`];
  if (sizeOf(p) !== DASH) parts.push(bytes(p.diskUsageBytes ?? 0));
  if (p.state !== "refused") parts.push(`keep forever ${p.pinned === true ? "on" : "off"}`);
  if (p.stale === true) parts.push("stale");
  return parts.join(", ").replaceAll(" · ", ", ");
}

/** The row's one action (D02 §4.1): its label (the name completes it), its T2 reason, its handler. */
function actionOf(
  p: RecorderStatusRowData,
): { label: ReactNode; reason: string | undefined; onPress: (() => void) | undefined } | undefined {
  if (p.state === "refused" || p.state === "stopping") return undefined;
  if (p.state === "lingering")
    return {
      label: <>Keep recording{hidden(` ${p.symbol}`)}</>,
      reason: undefined,
      onPress: p.onKeepRecording,
    };
  if (p.state === "stopped") {
    const cap = p.recordAgainBlockedReason === "symbol_cap";
    return {
      label: <>Record{hidden(` ${p.symbol}`)} again</>,
      reason: cap ? RECORDER_REASONS["recorder.symbol_cap"] : undefined,
      onPress: p.onRecordAgain,
    };
  }
  const block = p.stopBlockedReason;
  const key =
    block == null
      ? undefined
      : (`recorder.stop_blocked.${block === "chart_open" ? "chart" : "position"}_${p.reason === "manual" ? "manual" : "auto"}` as const);
  return {
    label: <>Stop{hidden(` recording ${p.symbol}`)}</>,
    reason:
      key === undefined
        ? undefined
        : RECORDER_REASONS[key].replace("{grace}", duration(p.graceSeconds ?? 1800)),
    onPress: p.onStop,
  };
}

/**
 * A held key re-shows a reason once (E09-D09 §9.3). Enter presses a button on every keydown, so after a gated
 * control's first one, those that follow before a keyup or a blur (a key's auto-repeat) press nothing; Space
 * presses once, on its keyup.
 */
function useHoldOnce(gated: boolean): {
  onKeyDown: (event: KeyboardEvent<HTMLElement>) => void;
  onKeyUp: () => void;
  onBlur: () => void;
} {
  const held = useRef(false);
  const release = (): void => {
    held.current = false;
  };
  return {
    onKeyDown: (event) => {
      if (!gated || event.key !== "Enter") return;
      if (held.current || event.repeat) event.preventDefault();
      held.current = true;
    },
    onKeyUp: release,
    onBlur: release,
  };
}

/** CMP-019 `lock`, named "Not available", leading a T2 control's label (E09-D09 §2.2, G-T2.1d). */
const Lock = ({ id }: { readonly id?: string }): JSX.Element => (
  <span id={id} className="cv-rsr__lock">
    <Icon name="lock" decorative={false} label="Not available" />
  </span>
);

interface RowButtonProps {
  readonly children: ReactNode;
  /** T2: the state's reason, or CMP-079's role leg, which replaces it. */
  readonly disabledReason?: string;
  /** The node that shows the reason: the row's 2a line, the read-only notice, or the grid's hidden node (2b). */
  readonly reasonId: string;
  /** 2b: CMP-016 echoes the reason on hover and focus (the grid's Action cell, D02 D-15). */
  readonly echo: boolean;
  readonly onPress: (() => void) | undefined;
}

/**
 * CMP-001 (ghost) as the row draws it: main's atom can neither point at a host's reason node nor lead with the named
 * lock (#5146's `disabledReasonId`), so CMP-177 owns this button's T2 on CMP-001's classes. A gate that engages or
 * lifts, or Stop turning into Keep recording, updates this element in place: it keeps focus (D02 §9.1).
 */
function RowButton({
  children,
  disabledReason,
  reasonId,
  echo,
  onPress,
}: RowButtonProps): JSX.Element {
  const ring = useFocusRing();
  const announce = useGatedAnnounce();
  const reason = disabledReason?.trim() || undefined;
  const hold = useHoldOnce(reason !== undefined);
  const control = (
    <button
      type="button"
      className={cx("cv-control", ring.className, "cv-button", "cv-rsr__action")}
      data-variant="ghost"
      aria-disabled={reason === undefined ? undefined : true}
      aria-describedby={reason === undefined ? undefined : reasonId}
      {...hold}
      onClick={() => (reason === undefined ? onPress?.() : announce(reason))}
    >
      {reason === undefined ? null : <Lock />} <span className="cv-button__label">{children}</span>
    </button>
  );
  return echo ? <ReasonEcho text={reason}>{control}</ReasonEcho> : control;
}

interface KeepSwitchProps {
  readonly row: RecorderStatusRowData;
  readonly disabledReason?: string;
  readonly reasonId: string;
  /** Standalone: "Keep forever" beside the switch; in the grid the column header shows it. */
  readonly visible: boolean;
}

/** CMP-004 as the row draws it, for the same reason as RowButton: named "Keep {symbol} data forever". */
function KeepSwitch({ row, disabledReason, reasonId, visible }: KeepSwitchProps): JSX.Element {
  const id = useId();
  const announce = useGatedAnnounce();
  const reason = disabledReason?.trim() || undefined;
  const hold = useHoldOnce(reason !== undefined);
  const on = row.pinned === true;
  return (
    <div className="cv-choice cv-rsr__keep" data-gated={reason === undefined ? undefined : ""}>
      <label className="cv-choice__target" htmlFor={id}>
        {reason === undefined ? null : <Lock id={`${id}-lock`} />}
        <span className="cv-choice__control">
          <button
            id={id}
            type="button"
            role="switch"
            className="cv-switch"
            data-checked={on ? "" : undefined}
            aria-checked={on}
            aria-labelledby={cx(reason !== undefined && `${id}-lock`, `${id}-name`)}
            aria-disabled={reason === undefined ? undefined : true}
            aria-describedby={reason === undefined ? undefined : reasonId}
            {...hold}
            onClick={() => (reason === undefined ? row.onTogglePin?.(!on) : announce(reason))}
          >
            <span className="cv-switch__knob" />
          </button>
        </span>
        <span id={`${id}-name`} className={visible ? "cv-choice__label" : "cv-visually-hidden"}>
          Keep{hidden(` ${row.symbol} data`)} forever
        </span>
      </label>
    </div>
  );
}

/** The card's write leg (E09-D09 §2.1 step 3): CMP-079 around each write, and its sentence. */
interface WriteLeg {
  readonly gate: (child: RbacGateChild) => JSX.Element;
  readonly reason: string;
}

/** The Why? popover (D02 §5.1): opens on Keep recording, which closes it with focus back on Why? (F-03). */
function Why({
  row,
  leg,
}: {
  readonly row: RecorderStatusRowData;
  readonly leg?: WriteLeg;
}): JSX.Element {
  const id = useId();
  const [open, setOpen] = useState(false);
  const keep = (
    <RowButton
      reasonId={`${id}-why`}
      echo={false}
      onPress={() => {
        row.onKeepRecording?.();
        setOpen(false);
      }}
    >
      Keep recording{hidden(` ${row.symbol}`)}
    </RowButton>
  );
  return (
    <Popover
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (next) row.onWhyOpen?.();
      }}
      heading="Recorded automatically"
      anchor={<IconButton icon="info" variant="ghost" label={`Why is ${row.symbol} recorded?`} />}
      footer={
        ACTIVE.has(row.state) ? (
          <span className="cv-rsr__gated">
            {leg === undefined ? keep : leg.gate(keep)}
            {/* Outside the row, the popover repeats a role leg as its own 2a line (D02 §4.2). */}
            <span id={`${id}-why`} className="cv-rsr__reason">
              {leg?.reason}
            </span>
          </span>
        ) : undefined
      }
    >
      <p className="cv-rsr__why">{row.why}</p>
    </Popover>
  );
}

function SymbolView({ row }: { readonly row: RecorderStatusRowData }): JSX.Element {
  const ring = useFocusRing();
  return row.onOpenDetail === undefined ? (
    <span className="cv-rsr__symbol">{row.symbol}</span>
  ) : (
    <button
      type="button"
      className={cx(ring.className, "cv-rsr__symbol")}
      onClick={row.onOpenDetail}
    >
      {row.symbol}
    </button>
  );
}

function ReasonView({
  row,
  leg,
}: {
  readonly row: RecorderStatusRowData;
  readonly leg?: WriteLeg;
}): JSX.Element {
  return (
    <span className="cv-rsr__tag">
      <Tag label={TAGS[row.reason]} />
      {row.reason === "manual" ? null : <Why row={row} {...(leg === undefined ? {} : { leg })} />}
    </span>
  );
}

/** The state words in `color.text.primary`, the tone on an `aria-hidden` icon of its own shape (D02 §10.3). */
function StateView({ row }: { readonly row: RecorderStatusRowData }): JSX.Element {
  const tone =
    row.state === "refused"
      ? row.refusal === "disk_pressure"
        ? "warning"
        : "info"
      : TONES[row.state];
  const stale = row.stale === true;
  return (
    <span className="cv-rsr__state" data-stale={stale ? "" : undefined}>
      {tone === undefined ? null : (
        <span className="cv-rsr__icon" data-tone={tone}>
          {row.state === "starting" ? (
            <Spinner size="sm" />
          ) : tone === "success" ? (
            <Badge variant="dot" tone="success" />
          ) : (
            <Icon name={tone} size="sm" />
          )}
        </span>
      )}
      <span className="cv-rsr__words">{wordsOf(row)}</span>
      {stale ? <Tag label="stale" icon="pending" /> : null}
    </span>
  );
}

const COLUMNS = [
  ["symbol", "Symbol", 7.5],
  ["reason", "Reason", 9.5],
  ["state", "State", 15.5],
  ["since", "Since", 6.5],
  ["depth", "Depth", 4],
  ["size", "Size", 9.5],
  ["retention", "Retention", 7.5],
  ["keep", "Keep forever", 5.5],
  ["action", "Action", 6.5],
] as const;
type ColumnId = (typeof COLUMNS)[number][0];
/** A column's words (the host's default row name reads the first); the table variant draws the cells. */
const TEXT: Readonly<Record<ColumnId, (r: RecorderStatusRowData) => string>> = {
  symbol: (r) => r.symbol,
  reason: (r) => TAGS[r.reason],
  state: wordsOf,
  since: sinceOf,
  depth: depthOf,
  size: sizeOf,
  retention: retentionOf,
  keep: (r) => (r.pinned === true ? "on" : "off"),
  action: () => "",
};

/**
 * The host grid's columns for CMP-177 (E16-D02 §1): the table variant's cell order, D02 §1's widths at 16 px as
 * `minWidthEm`, Symbol, Since and Size sortable, and the cells with controls `interactive`.
 */
export function recorderStatusColumns(): TableColumn<RecorderStatusRowData>[] {
  return COLUMNS.map(([id, header, minWidthEm]) => ({
    id,
    header,
    minWidthEm,
    sortable: id === "symbol" || id === "since" || id === "size",
    interactive: id === "symbol" || id === "reason" || id === "keep" || id === "action",
    cell: TEXT[id],
  }));
}

/** The table variant: the row's nine cells for the host's grid, named by the row's summary (D02H table 3). */
function GridRow({ grid, ...row }: RecorderStatusRowData & TableVariant): JSX.Element {
  const id = useId();
  const action = actionOf(row);
  const cell = (column: number, content: ReactNode, controls = false, numeric = false) => (
    <td
      {...grid.cellProps(column, numeric ? { numeric } : undefined)}
      data-cv-interactive={controls ? "" : undefined}
    >
      {grid.label(column)}
      {numeric ? <span className="cv-rsr__num">{content}</span> : content}
    </td>
  );
  return (
    <tr
      {...grid.rowProps}
      className={cx(grid.rowProps.className, "cv-rsr-row")}
      aria-label={recorderStatusSummary(row)}
      data-cmp="CMP-177"
      data-stale={row.stale === true ? "" : undefined}
    >
      <th
        {...grid.cellProps(0, { header: true })}
        data-cv-interactive={row.onOpenDetail === undefined ? undefined : ""}
      >
        {grid.label(0)}
        <SymbolView row={row} />
      </th>
      {cell(1, <ReasonView row={row} />, row.reason !== "manual")}
      {cell(2, <StateView row={row} />)}
      {cell(3, sinceOf(row), false, true)}
      {cell(4, depthOf(row), false, true)}
      {cell(5, sizeOf(row), false, true)}
      {cell(6, retentionOf(row))}
      {row.state === "refused"
        ? cell(7, DASH)
        : cell(7, <KeepSwitch row={row} reasonId="" visible={false} />, true)}
      {action === undefined
        ? cell(8, null)
        : cell(
            8,
            <>
              {/* 2b (D02 D-15): the reason's node, hidden and in the DOM at mount; CMP-016 echoes it. */}
              <RowButton
                {...(action.reason === undefined ? {} : { disabledReason: action.reason })}
                reasonId={`${id}-reason`}
                echo
                onPress={action.onPress}
              >
                {action.label}
              </RowButton>
              <span id={`${id}-reason`} className="cv-visually-hidden">
                {action.reason}
              </span>
            </>,
            true,
          )}
    </tr>
  );
}

/** The standalone variant (SCR-103): a group named "{symbol} recording", its summary the description. */
function Card({
  writeReason,
  viewAsUser = "",
  ...row
}: RecorderStatusRowData & StandaloneVariant): JSX.Element {
  const id = useId();
  const view = writeReason === "rbac.view_as";
  const write =
    writeReason == null
      ? undefined
      : view
        ? formatRbacReason("rbac.view_as", { user: viewAsUser })
        : formatRbacReason("rbac.owner_only", { verb: "change recording" });
  const reasonId = `${id}-${write === undefined ? "reason" : "notice"}`;
  // One element type whatever the leg, so a leg that comes or goes never re-mounts the control.
  const gate = (child: RbacGateChild): JSX.Element =>
    writeReason == null ? (
      <RbacGate allowed>{child}</RbacGate>
    ) : view ? (
      <RbacGate allowed={false} reason="rbac.view_as" fills={{ user: viewAsUser }}>
        {child}
      </RbacGate>
    ) : (
      <RbacGate allowed={false} reason="rbac.owner_only" fills={{ verb: "change recording" }}>
        {child}
      </RbacGate>
    );
  const action = actionOf(row);
  return (
    <div
      role="group"
      aria-label={`${row.symbol} recording`}
      aria-describedby={`${id}-about`}
      className="cv-rsr"
      data-cmp="CMP-177"
      data-stale={row.stale === true ? "" : undefined}
    >
      <div className="cv-rsr__title">
        <SymbolView row={row} />
        <ReasonView row={row} {...(write === undefined ? {} : { leg: { gate, reason: write } })} />
      </div>
      {write === undefined ? null : (
        <p id={`${id}-notice`} className="cv-rsr__reason">
          {view ? write : `Read-only — ${lower(write)}`}
        </p>
      )}
      <StateView row={row} />
      <p className="cv-rsr__meta">
        Since {sinceOf(row)} · Depth {depthOf(row)} · Size {sizeOf(row)} · Retention{" "}
        {retentionOf(row)}
      </p>
      {row.state === "refused" ? null : gate(<KeepSwitch row={row} reasonId={reasonId} visible />)}
      {action === undefined ? null : (
        <span className="cv-rsr__gated">
          {gate(
            <RowButton
              {...(action.reason === undefined ? {} : { disabledReason: action.reason })}
              reasonId={reasonId}
              echo={false}
              onPress={action.onPress}
            >
              {action.label}
            </RowButton>,
          )}
          <span id={`${id}-reason`} className="cv-rsr__reason">
            {write === undefined ? action.reason : undefined}
          </span>
        </span>
      )}
      <span id={`${id}-about`} hidden>
        {recorderStatusSummary(row)}
      </span>
    </div>
  );
}

/**
 * CMP-177 RecorderStatusRow (E16-D02 §4.2). `variant="table"` draws a row of the host's grid (SCR-140) through its row
 * contract; the default, `standalone`, a card (SCR-103) whose Tab order is Why?, Keep forever, then the action (D02H
 * table 2). A blocked action is T2 (D02 §10.5): the lock leads its full label, its reason echoed in the grid (2b) or
 * under it in the card (2a); `writeReason` makes every write T2 through CMP-079, each described by one
 * `notice.panel_read_only` under the title (E09-D09 §2.2), the reason alone with `rbac.view_as` (D02 D-16).
 */
export function RecorderStatusRow(props: RecorderStatusRowProps): JSX.Element {
  return props.variant === "table" ? <GridRow {...props} /> : <Card {...props} />;
}
