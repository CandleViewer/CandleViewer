import {
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type FocusEvent,
  type JSX,
  type KeyboardEvent,
  type ReactNode,
  type RefObject,
} from "react";
import { Icon } from "../icons/Icon.js";
import { Badge } from "./Badge.js";
import { Button } from "./Button.js";
import { useFocusRing } from "./FocusRing.js";
import { IconButton } from "./IconButton.js";
import { Popover } from "./Popover.js";
import { RbacGate, type RbacGateChild } from "./RbacGate.js";
import { Spinner } from "./Spinner.js";
import type { TableColumn } from "./Table.js";
import { Tag } from "./Tag.js";
import { cx } from "./internal/cx.js";
import { useGatedAnnounce } from "./internal/disabledReason.js";
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
  /**
   * As built: while `accelerate_retention` holds, the effective days of an unpinned row (the host's; the reaper
   * halves retention, `21-database-schema.md`): Retention reads "30 d → 15 d (accelerated)" (D02 §2, §3 `paused`).
   */
  readonly retentionAcceleratedDays?: number | null;
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
  /** The action's write is in flight (Keep recording, Record again): CMP-001 `loading`, a press sends nothing. */
  readonly actionBusy?: boolean;
  /** Asks for the other value; the host confirms and steps up (D02 §6.4). */
  readonly onTogglePin?: (pinned: boolean) => void;
  /** A press on the symbol: the row detail (D02 §6.7). */
  readonly onOpenDetail?: () => void;
  /** The Why? popover opened (`recorder.auto_review_opened`, D02 §12). */
  readonly onWhyOpen?: () => void;
}

/** What a cell asks of the host's grid (#5146's CMP-049 `TableCellOptions` takes these). */
export interface RecorderCellOptions {
  /** The symbol: the row's header (`th scope="row"`). */
  readonly header?: boolean;
  /** Since and Depth: end-aligned numbers that never wrap (D02 §9.1). */
  readonly numeric?: boolean;
  /** The Action cell's T2 reason, which the grid's one CMP-016 echo shows on the cell's focus and hover (2b). */
  readonly echo?: string | undefined;
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
  /**
   * The grid stacked into cards (CMP-049's reflow, a table of Tab stops): a T2 reason shows inline (2a, D02 §1's
   * 200 % paragraph), and a control a frame removes hands focus to the row's next stop.
   */
  readonly stacked?: boolean;
}

/** SCR-140: a `row` of the host's grid. `ReadOnly` is the standalone variant's alone (D02 §4.2). */
interface TableVariant {
  readonly variant: "table";
  readonly grid: RecorderRowGrid;
  /** D02 §1's 1280 × 800 plan: no Since and Depth cells, as `recorderStatusColumns({ narrow })` gives the host. */
  readonly narrow?: boolean;
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
/** en-US grouping, one decimal: the page's own figures' form ("1,188.0 GB", E16-D04 §14). */
const ONE_DECIMAL = new Intl.NumberFormat("en-US", {
  minimumFractionDigits: 1,
  maximumFractionDigits: 1,
});

const at = (iso: string | null | undefined): Date | undefined => {
  const ms = iso == null ? Number.NaN : Date.parse(iso);
  return Number.isNaN(ms) ? undefined : new Date(ms);
};
const dayMonth = (d: Date): string => `${d.getUTCDate()} ${MONTHS[d.getUTCMonth()] ?? ""}`;
/** "34.8 GB", "1.3 MB": GB from 999.95 MB, where one decimal of MB would print "1,000.0" (as the page's). */
const bytes = (n: number): string =>
  n >= 1e9 - 5e4 ? `${ONE_DECIMAL.format(n / 1e9)} GB` : `${ONE_DECIMAL.format(n / 1e6)} MB`;
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
const retentionOf = (p: RecorderStatusRowData): string => {
  if (p.state === "refused") return DASH;
  if (p.pinned === true) return "Forever";
  if (p.retentionDays == null) return DASH;
  const fast = p.retentionAcceleratedDays;
  return fast == null ? `${p.retentionDays} d` : `${p.retentionDays} d → ${fast} d (accelerated)`;
};

/** "34.8 GB · 0.71/d", "est." while estimated, "· 17 % of budget" from disk level 1; "—" with nothing written. */
function sizeOf(p: RecorderStatusRowData): string {
  const [size, share] = sizeParts(p);
  return share === null ? size : `${size} ${share}`;
}

/**
 * The Size cell's two parts (D02 §1, board 05): the figures, then from disk level 1 the share of the budget, which the
 * grid draws on its own line; "—" with no size yet (refused, starting) or nothing written.
 */
function sizeParts(p: RecorderStatusRowData): readonly [string, string | null] {
  if (p.state === "refused" || p.state === "starting" || p.diskUsageBytes == null) {
    return [DASH, null];
  }
  const g = p.state === "stopped" ? null : p.dailyGrowthBytes;
  const rate =
    g == null ? "" : ` · ${(g / 1e9).toFixed(2)}/d${p.growthEstimated === true ? " est." : ""}`;
  const share =
    (p.diskLevel ?? 0) >= 1 && p.budgetShare != null
      ? `· ${Math.round(p.budgetShare * 100)} % of budget`
      : null;
  return [`${bytes(p.diskUsageBytes)}${rate}`, share];
}

/** The states whose leading word is "Recording": the start date reads as how long it has recorded. */
const RECORDING = new Set<RecorderRowState>(["recording", "lingering"]);

/**
 * The row's name (D02H table 3): "BTCUSDT, manual, recording since 1 Sep 2026, 34.8 GB, keep forever on". The start
 * date joins the state's leading word only while it is "recording" ("recording since 20 Oct 2026, position"), so it
 * never dates a degraded, gated or silent state (B-5309-04, D-5309-12).
 */
function recorderStatusSummary(p: RecorderStatusRowData): string {
  const [head = "", ...detail] = wordsOf(p).split(" · ");
  const start = RECORDING.has(p.state) ? at(p.startedAt) : undefined;
  const since = start === undefined ? "" : ` since ${dayMonth(start)} ${start.getUTCFullYear()}`;
  const parts = [p.symbol, lower(TAGS[p.reason]), `${lower(head)}${since}`, ...detail];
  if (p.diskUsageBytes != null && sizeParts(p)[0] !== DASH) parts.push(bytes(p.diskUsageBytes));
  if (p.state !== "refused") parts.push(`keep forever ${p.pinned === true ? "on" : "off"}`);
  if (p.stale === true) parts.push("stale");
  return parts.join(", ");
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

/**
 * CMP-019 `lock`, named "Not available", for a T2 switch (E09-D09 §2.2, G-T2.1d): CMP-004's centred lock (ChoiceRow's
 * `cv-choice__lock`), leading the visible label, or trailing the switch where the label is hidden (B-5309-09).
 */
const Lock = ({ id }: { readonly id?: string }): JSX.Element => (
  <span id={id} className="cv-choice__lock">
    <Icon name="lock" decorative={false} label="Not available" />
  </span>
);

interface RowButtonProps {
  readonly children: ReactNode;
  /** T2: the state's reason, or CMP-079's role leg, which replaces it. */
  readonly disabledReason?: string;
  /** The node that shows the reason: the row's 2a line, the read-only notice, or the grid's hidden node (2b). */
  readonly reasonId: string;
  /** The action's write is in flight: CMP-001 `loading`. */
  readonly busy?: boolean;
  readonly onPress: (() => void) | undefined;
}

/**
 * CMP-001 (ghost) composed as CMP-055's controls are (rendering 2a: `disabledReasonId`, so the lock leads the full
 * label, named "Not available", and the row's reason node describes it; the T2 look is the atom's, #262's C-row). In
 * the grid the node is hidden and the grid's one CMP-016 echo shows it on the cell (2b, D02 D-15). The atom says a
 * refused press once through the gated announcement; a held key's repeats press nothing; while `busy` a press sends
 * nothing. A gate that engages or lifts, or Stop turning into Keep recording, updates this element in place: it keeps
 * focus (D02 §9.1).
 */
function RowButton({
  children,
  disabledReason,
  reasonId,
  busy = false,
  onPress,
}: RowButtonProps): JSX.Element {
  const reason = disabledReason?.trim() || undefined;
  const hold = useHoldOnce(reason !== undefined);
  return (
    <Button
      variant="ghost"
      loading={busy}
      {...(reason === undefined ? {} : { disabledReason: reason, disabledReasonId: reasonId })}
      {...hold}
      onClick={() => onPress?.()}
    >
      {children}
    </Button>
  );
}

interface KeepSwitchProps {
  readonly row: RecorderStatusRowData;
  readonly disabledReason?: string;
  readonly reasonId: string;
  /** Standalone: "Keep forever" beside the switch; in the grid the column header shows it. */
  readonly visible: boolean;
}

/**
 * CMP-004 as the row draws it, for the same reason as RowButton: named "Keep {symbol} data forever". T2, the named
 * lock leads the visible label as CMP-004's own does (ChoiceRow); with the label hidden (the grid) it trails the
 * switch, and the switch's name still starts with it.
 */
function KeepSwitch({ row, disabledReason, reasonId, visible }: KeepSwitchProps): JSX.Element {
  const id = useId();
  const announce = useGatedAnnounce();
  const reason = disabledReason?.trim() || undefined;
  const hold = useHoldOnce(reason !== undefined);
  const on = row.pinned === true;
  const lock = reason === undefined ? null : <Lock id={`${id}-lock`} />;
  return (
    <div className="cv-choice cv-rsr__keep" data-gated={reason === undefined ? undefined : ""}>
      <label className="cv-choice__target" htmlFor={id}>
        <span className="cv-choice__control">
          <button
            id={id}
            type="button"
            role="switch"
            className="cv-switch"
            data-checked={on ? "" : undefined}
            aria-checked={on}
            aria-labelledby={cx(!visible && lock !== null && `${id}-lock`, `${id}-name`)}
            aria-disabled={reason === undefined ? undefined : true}
            aria-describedby={reason === undefined ? undefined : reasonId}
            {...hold}
            onClick={() => (reason === undefined ? row.onTogglePin?.(!on) : announce(reason))}
          >
            <span className="cv-switch__knob" />
          </button>
        </span>
        {visible ? (
          <span id={`${id}-name`} className="cv-choice__label">
            {lock}
            Keep{hidden(` ${row.symbol} data`)} forever
          </span>
        ) : (
          <span id={`${id}-name`} className="cv-visually-hidden">
            Keep {row.symbol} data forever
          </span>
        )}
      </label>
      {visible ? null : lock}
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

/**
 * The symbol; with `onOpenDetail`, a button that opens the row's detail. In the roving grid it is no Tab stop of its
 * own (`stop` false): Enter on its cell opens the detail (the row's key), and a press still does.
 */
function SymbolView({
  row,
  stop = true,
}: {
  readonly row: RecorderStatusRowData;
  readonly stop?: boolean;
}): JSX.Element {
  const ring = useFocusRing();
  const open = row.onOpenDetail;
  return open === undefined ? (
    <span className="cv-rsr__symbol">{row.symbol}</span>
  ) : (
    <button
      type="button"
      className={cx(ring.className, "cv-rsr__symbol")}
      tabIndex={stop ? undefined : -1}
      onClick={() => open()}
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
      {/* One line in the grid, cut with an ellipsis; CMP-049's echo shows the whole words while cut (D02 §9.1). */}
      <span className="cv-rsr__words" data-cv-cut={wordsOf(row)}>
        {wordsOf(row)}
      </span>
      {stale ? <Tag label="stale" icon="pending" /> : null}
    </span>
  );
}

/**
 * E16-D02 §1's column plan, in px at its 1440 × 900 frame (content 1152 px), and `narrowPx` at 1280 × 800 (content
 * 992 px), where Since and Depth go to the row detail. In `em` of the table's own font: the app sets none, so a
 * `<col>`'s em is the root's 16 px, and 72 em is 1152 px, scaling with zoom and the in-app text scale.
 * Deviation, measured in the pinned faces (B-5309-01): CMP-001's "Record again" with its T2 lock is 121 px and
 * "Keep recording" 113, so Action takes 138 px where D02 has 104 and 112; State, which cuts its words with an
 * ellipsis and the echo, gives the 34 and 26 px (216 and 224).
 */
const COLUMNS = [
  { id: "symbol", header: "Symbol", px: 120, narrowPx: 120 },
  { id: "reason", header: "Reason", px: 150, narrowPx: 150 },
  { id: "state", header: "State", px: 216, narrowPx: 224 },
  { id: "since", header: "Since", px: 104, narrowPx: null },
  { id: "depth", header: "Depth", px: 64, narrowPx: null },
  { id: "size", header: "Size", px: 150, narrowPx: 150 },
  { id: "retention", header: "Retention", px: 120, narrowPx: 120 },
  { id: "keep", header: "Keep forever", px: 90, narrowPx: 90 },
  { id: "action", header: "Action", px: 138, narrowPx: 138 },
] as const;
type ColumnId = (typeof COLUMNS)[number]["id"];
const EM_PX = 16;
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

export interface RecorderColumnsOptions {
  /** D02 §1's 1280 × 800 plan: no Since and Depth (they are the row detail's), 62 em in all. */
  readonly narrow?: boolean;
}

/**
 * The host grid's columns for CMP-177 (E16-D02 §1): the table variant's cell order; D02 §1's widths as `widthEm` and
 * as `minWidthEm` alike, so the grid stacks into cards rather than squeeze a column (B-5309-01); Since, Depth and
 * Size end-aligned (B-5309-02); Symbol, Since and Size sortable; the cells with controls `interactive` (the symbol's
 * cell is not: Enter on it opens the row's detail, B-5309-03).
 */
export function recorderStatusColumns(
  options: RecorderColumnsOptions = {},
): TableColumn<RecorderStatusRowData>[] {
  const narrow = options.narrow === true;
  return COLUMNS.flatMap(({ id, header, px, narrowPx }) => {
    const width = narrow ? narrowPx : px;
    if (width === null) return [];
    const em = width / EM_PX;
    return [
      {
        id,
        header,
        widthEm: em,
        minWidthEm: em,
        ...(id === "since" || id === "depth" || id === "size" ? { align: "end" as const } : {}),
        sortable: id === "symbol" || id === "since" || id === "size",
        interactive: id === "reason" || id === "keep" || id === "action",
        cell: TEXT[id],
      },
    ];
  });
}

/** The cell index of the row's element `node` holds focus in, by DOM order. */
const cellIndexOf = (row: HTMLTableRowElement, node: Element): number => {
  const cell = node.closest("td, th");
  return cell === null ? -1 : [...row.cells].indexOf(cell as HTMLTableCellElement);
};
/** The row's own Tab stops while stacked (CMP-049 gives each control back its own `tabindex`). */
const STOPS = "button:not([tabindex='-1']), a[href], input, select, textarea";

/**
 * D-5309-07: stacked, a control a frame removes (Why? once the row turns manual, the action once it stops) took focus
 * with it, so the row hands focus to its next stop, else its previous one; never while focus went elsewhere. In the
 * roving grid CMP-049 keeps the Tab stop on the cell.
 */
function useFocusHandoff(stacked: boolean): {
  readonly ref: RefObject<HTMLTableRowElement>;
  readonly onFocus: (event: FocusEvent<HTMLTableRowElement>) => void;
} {
  const ref = useRef<HTMLTableRowElement>(null);
  const held = useRef<{ readonly node: Element; readonly cell: number } | null>(null);
  useLayoutEffect(() => {
    const was = held.current;
    const row = ref.current;
    if (was === null || row === null || was.node.isConnected) return;
    held.current = null;
    const active = document.activeElement;
    if (!stacked || (active !== null && active !== document.body)) return;
    const stops = [...row.querySelectorAll<HTMLElement>(STOPS)];
    const next = stops.find((stop) => cellIndexOf(row, stop) >= was.cell) ?? stops.at(-1);
    next?.focus();
  });
  return {
    ref,
    onFocus: (event) => {
      const row = event.currentTarget;
      held.current = { node: event.target, cell: cellIndexOf(row, event.target) };
    },
  };
}

/** The cells each plan draws, in order. */
const WIDE_IDS: readonly ColumnId[] = COLUMNS.map((column) => column.id);
const NARROW_IDS: readonly ColumnId[] = COLUMNS.filter((c) => c.narrowPx !== null).map((c) => c.id);

/** How the row draws one cell: its controls (CMP-049's interactive cell), a number, the echo's words. */
interface CellPlan {
  readonly controls?: boolean;
  readonly numeric?: boolean;
  readonly echo?: string;
}

/** A figure and its unit stay on one line ("34.8 GB", "0.71/d est."): the figures wrap at their " · " alone. */
const unbroken = (figures: string): string =>
  figures.replace(/(\d) (GB|MB)\b/g, "$1\u00a0$2").replace(" est.", "\u00a0est.");

/**
 * The Size cell: the figures, then the share of the budget on its own line (a break, so the cell's words read as one
 * text), end-aligned under its end-aligned header (board 05).
 */
function SizeView({ row }: { readonly row: RecorderStatusRowData }): JSX.Element {
  const [size, share] = sizeParts(row);
  return (
    <span className="cv-rsr__num">
      {unbroken(size)}
      {share === null ? null : (
        <>
          <br /> {share}
        </>
      )}
    </span>
  );
}

/**
 * The table variant: the row's cells for the host's grid (nine, or seven `narrow`), named by the row's summary (D02H
 * table 3). Enter on a cell with no control opens the row's detail (D02 §10.1, B-5309-03).
 */
function GridRow({
  grid,
  narrow = false,
  ...row
}: RecorderStatusRowData & TableVariant): JSX.Element {
  const id = useId();
  const action = actionOf(row);
  const stacked = grid.stacked === true;
  const handoff = useFocusHandoff(stacked);
  const shown: readonly ColumnId[] = narrow ? NARROW_IDS : WIDE_IDS;
  const cell = (
    column: ColumnId,
    content: ReactNode,
    options: CellPlan = {},
  ): JSX.Element | null => {
    const place = shown.indexOf(column);
    if (place < 0) return null;
    const { controls = false, numeric = false, echo } = options;
    return (
      <td
        {...grid.cellProps(place, {
          ...(numeric ? { numeric } : {}),
          ...(echo === undefined ? {} : { echo }),
        })}
        data-cv-interactive={controls ? "" : undefined}
      >
        {grid.label(place)}
        {numeric ? <span className="cv-rsr__num">{content}</span> : content}
      </td>
    );
  };
  // A held Enter opens the detail once: its repeats before a keyup or a blur open nothing (as useHoldOnce).
  const held = useRef(false);
  const onKeyDown = (event: KeyboardEvent<HTMLTableRowElement>): void => {
    const open = row.onOpenDetail;
    const bare = !event.altKey && !event.ctrlKey && !event.metaKey && !event.shiftKey;
    if (open === undefined || event.defaultPrevented || event.key !== "Enter" || !bare) return;
    // From a cell itself, never a control in it; Enter on a cell with controls is CMP-049's way into them.
    const target = event.target as HTMLElement;
    if (!target.matches("td, th") || target.hasAttribute("data-cv-interactive")) return;
    event.preventDefault();
    if (held.current || event.repeat) return;
    held.current = true;
    open();
  };
  const release = (): void => {
    held.current = false;
  };
  return (
    <tr
      {...grid.rowProps}
      ref={handoff.ref}
      className={cx(grid.rowProps.className, "cv-rsr-row")}
      aria-label={recorderStatusSummary(row)}
      data-cmp="CMP-177"
      data-stale={row.stale === true ? "" : undefined}
      data-stacked={stacked ? "" : undefined}
      onKeyDown={onKeyDown}
      onKeyUp={release}
      onBlur={release}
      onFocus={handoff.onFocus}
    >
      <th {...grid.cellProps(0, { header: true })}>
        {grid.label(0)}
        <SymbolView row={row} stop={stacked} />
      </th>
      {cell("reason", <ReasonView row={row} />, { controls: row.reason !== "manual" })}
      {cell("state", <StateView row={row} />)}
      {cell("since", sinceOf(row), { numeric: true })}
      {cell("depth", depthOf(row), { numeric: true })}
      {cell("size", <SizeView row={row} />)}
      {cell("retention", retentionOf(row))}
      {row.state === "refused"
        ? cell("keep", DASH)
        : cell("keep", <KeepSwitch row={row} reasonId="" visible={false} />, { controls: true })}
      {action === undefined
        ? cell("action", null)
        : cell(
            "action",
            <>
              <RowButton
                {...(action.reason === undefined ? {} : { disabledReason: action.reason })}
                reasonId={`${id}-reason`}
                busy={row.actionBusy === true}
                onPress={action.onPress}
              >
                {action.label}
              </RowButton>
              {/*
                The reason's node, in the DOM at mount: hidden in the grid, whose one CMP-016 echo shows it on the cell
                (2b, D02 D-15); inline under the action once the grid stacks into cards (2a, D02 §1's 200 % paragraph).
              */}
              <span
                id={`${id}-reason`}
                className={stacked ? "cv-rsr__reason" : "cv-visually-hidden"}
              >
                {action.reason}
              </span>
            </>,
            {
              controls: true,
              ...(stacked || action.reason === undefined ? {} : { echo: action.reason }),
            },
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
              busy={row.actionBusy === true}
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
