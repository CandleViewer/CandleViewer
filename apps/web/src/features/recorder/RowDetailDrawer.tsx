/**
 * SCR-140's row detail (E16-D02 §6.7; E16-D06 KB-03, FM-07, RG-09, T2-01, T2-02): CMP-046 Drawer, modal, named
 * "{symbol} recording", opened from the row (its symbol, or Enter on it) or through `openRowDetail(symbol)`. Its
 * heading takes focus; Esc or Close returns focus to the row's opener (FM-07); nothing is announced, the drawer
 * is read by role. Status (state words, reason, started, streams; Depth, Retention and Keep forever, the Owner's
 * controls), Health and Cost read the newest frame; the gaps of the last 24 h are a static CMP-049 table. The
 * row's action carries its T2 reason inline (2a, D02 §6.3), busy while its add is on the wire, and Purge… is busy
 * while this client's purge runs. The drawer decides no write: the grid confirms and sends (C-12.4), and SCR-006 for
 * the drawer's own writes opens inside it, the page being inert under it (A-5347-d01). Focus never falls to `body`
 * (A-5347-03): a control that held it and goes with its row's controls hands it to the heading, and a close whose
 * opener is gone lands on the host's fallback.
 */
import { useLayoutEffect, useRef, type JSX, type ReactNode, type RefObject } from "react";
import {
  Button,
  Drawer,
  FormField,
  Heading,
  InlineError,
  KeyValueRow,
  ProgressBar,
  Select,
  Table,
  Tag,
  Text,
  Toggle,
} from "@candleviewer/ui";
import { DECK, TEXT, fill } from "./copy";
import {
  grouped,
  retentionOptions,
  retentionValue,
  rowAction,
  startedText,
  streamsText,
  type RowActionKind,
  type RowHealth,
} from "./detail";
import { DETAIL_TEXT } from "./detailCopy";
import { DEPTHS, type Depth, type RowContext } from "./grid";
import {
  formatBytes,
  formatClock,
  formatDuration,
  formatGrowth,
  stateWords,
  type RecorderRow,
} from "./model";
import type { RecordReason, RecordedSymbol } from "./model/types";
import { DETAIL_ID, detailHeading, gapColumns } from "./RecorderChrome";
import type { Gap } from "./useRecorderData";

const REASONS: readonly RecordReason[] = [
  "manual",
  "chart_open",
  "position_open",
  "rule_dependency",
  "alert_dependency",
];
const tagOf = (reason: RecordReason | null): string =>
  reason === null ? "—" : (DECK["d02.8.r08"][REASONS.indexOf(reason)] ?? "—");

const hidden = (text: string): JSX.Element => <span className="cv-visually-hidden">{text}</span>;

/** The action's visible label, its name completed by the symbol (D02H table 3, as CMP-177's). */
function actionLabel(kind: RowActionKind, symbol: string): ReactNode {
  if (kind === "keep") return <>Keep recording{hidden(` ${symbol}`)}</>;
  if (kind === "again") return <>Record{hidden(` ${symbol}`)} again</>;
  return <>Stop{hidden(` recording ${symbol}`)}</>;
}

export interface DetailPurge {
  /** A purge this client started is queued or running: Purge… is busy (D02 §6.5). */
  readonly busy: boolean;
  /** Opens the purge dialog with this symbol preselected. */
  readonly open: (symbol: string) => void;
  /** The symbols the purge dialog offers (`purgeTargets`): Purge… only for one of them (C-5347-08). */
  readonly symbols: readonly string[];
}

export interface RowDetailDrawerProps {
  /** The row as it reads now (the 1 Hz frame); null while closed. */
  readonly row: RecorderRow | null;
  readonly context: RowContext;
  /** REST's row: its streams. */
  readonly listed: RecordedSymbol | undefined;
  readonly health: RowHealth | null;
  /** This symbol's gaps of the last 24 h. */
  readonly gaps: readonly Gap[];
  readonly onClose: () => void;
  /** The row's action as the grid runs it: Stop opens its confirmation; Keep recording and Record again add. */
  readonly onAction: (kind: RowActionKind) => void;
  /** A refused action's words at the point of action (T4), the host's. */
  readonly actionRefusal?: string | null;
  /** Keep forever asked for its other value: the host confirms and steps up (D02 §6.4). */
  readonly onTogglePin?: ((pinned: boolean) => void) | undefined;
  /** A retention chosen in the select ("forever" never; "custom" opens SCR-141): the host confirms (D02 §6.4). */
  readonly onRetention?: ((value: string) => void) | undefined;
  /** SCR-141 is registered: the select offers "Custom…" (BQ-11). */
  readonly customRetention?: boolean;
  /** A depth chosen: the host sends it; its refusal comes back as `depthRefusal`. */
  readonly onDepth?: ((depth: Depth) => void) | undefined;
  /** The depth the host is sending, shown until the server answers. */
  readonly depthPending?: Depth | null;
  readonly depthRefusal?: string | null;
  readonly purge?: DetailPurge | undefined;
  /** Where focus lands when the drawer closes and its opener is gone (its row left, FM-02, FM-07). */
  readonly fallbackFocusRef?: RefObject<HTMLElement | null> | undefined;
  /**
   * SCR-006 for the drawer's own writes (its action, Depth), drawn inside the drawer's layer: a modal drawer makes
   * the page inert, so a gate there could not be reached (A-5347-d01).
   */
  readonly gate?: ReactNode;
  /** The action's add is on the wire: CMP-001 `loading`, focusable, a press sends nothing (A-5347-d04). */
  readonly actionBusy?: boolean;
}

export function RowDetailDrawer({
  row,
  context,
  listed,
  health,
  gaps,
  onClose,
  onAction,
  actionRefusal = null,
  onTogglePin,
  onRetention,
  customRetention = false,
  onDepth,
  depthPending = null,
  depthRefusal = null,
  purge,
  fallbackFocusRef,
  gate = null,
  actionBusy = false,
}: RowDetailDrawerProps): JSX.Element | null {
  // The control that held focus: gone with its row's controls (no id now) or the action's change, focus moves to
  // the heading, never `body` inside the open modal (A-5347-03).
  const held = useRef<HTMLElement | null>(null);
  useLayoutEffect(() => {
    const element = held.current;
    if (row === null) held.current = null;
    if (row === null || element === null || element.isConnected) return;
    held.current = null;
    const now = document.activeElement;
    if (now === null || now === document.body) detailHeading()?.focus({ preventScroll: true });
  });
  if (row === null) return null;
  const { symbol } = row;
  const sections = TEXT.detail.sections;
  const f = DETAIL_TEXT.fields;
  const grace = context.policy === null ? "" : formatDuration(context.policy.autostop_grace_s);
  const action = rowAction(row, grace);
  // An `idle` entry has no recorded-symbol id: no control exists for it (D02 §4.1).
  const tracked = row.state !== "refused" && row.id !== null;
  const stoppedAtMs = context.stoppedAtMs.get(symbol) ?? null;
  const words = stateWords(row, {
    nowMs: context.nowMs,
    maxSymbols: context.policy?.max_symbols ?? null,
    stoppedAtMs,
    gaps: context.gaps.get(symbol) ?? 0,
  });
  const erodes =
    row.state === "stopped" && !row.pinned && row.retentionDays !== null
      ? ` · ${fill(DETAIL_TEXT.erodes, { "{days}": row.retentionDays })}`
      : "";
  const growth = row.state === "stopped" ? null : (context.growth.get(symbol) ?? null);
  const cap = context.capBytes;
  const share =
    cap === null || cap <= 0 || row.diskBytes === null ? null : (row.diskBytes / cap) * 100;
  const dropped = health?.droppedMessages ?? null;
  const reasonId = `${DETAIL_ID}-reason`;

  return (
    <Drawer
      open
      id={DETAIL_ID}
      title={fill(TEXT.detail.label, { "{symbol}": symbol })}
      onOpenChange={(next) => {
        if (!next) onClose();
      }}
      {...(fallbackFocusRef === undefined ? {} : { fallbackFocusRef })}
    >
      {/* Sections without names: headings, never four `region` landmarks inside the dialog (A-5347-06). */}
      <div
        style={{ display: "grid", gap: "var(--space-stack-md)" }}
        onFocus={(event) => {
          held.current = event.target instanceof HTMLElement ? event.target : null;
        }}
      >
        <section>
          <Heading level={3} variant="heading-sm">
            {sections[0]}
          </Heading>
          <dl style={{ margin: 0 }}>
            <KeyValueRow
              label={f.state}
              value={
                <>
                  {words}
                  {erodes}
                  {context.stale ? <Tag label={TEXT.staleTag} icon="pending" /> : null}
                </>
              }
            />
            <KeyValueRow label={f.reason} value={tagOf(row.reason)} />
            <KeyValueRow label={f.started} value={startedText(row.startedAt)} />
            <KeyValueRow label={f.streams} value={streamsText(listed?.streams)} />
            {tracked ? null : (
              <>
                <KeyValueRow label={f.depth} value="—" />
                <KeyValueRow label={f.retention} value="—" />
              </>
            )}
          </dl>
          {tracked ? (
            <div style={{ display: "grid", gap: "var(--space-stack-sm)" }}>
              <FormField label={f.depth} error={depthRefusal ?? undefined}>
                <Select
                  options={DEPTHS.map((d) => ({ value: String(d), label: String(d) }))}
                  value={String(depthPending ?? row.depth ?? "")}
                  onChange={(value) => {
                    const depth = Number(value) as Depth;
                    if (depth !== (depthPending ?? row.depth)) onDepth?.(depth);
                  }}
                />
              </FormField>
              <FormField label={f.retention}>
                <Select
                  options={retentionOptions(row, customRetention)}
                  value={retentionValue(row)}
                  onChange={(value) => {
                    if (value !== retentionValue(row)) onRetention?.(value);
                  }}
                />
              </FormField>
              <Toggle
                label={fill(TEXT.keepForever.toggle, { "{symbol}": symbol })}
                checked={row.pinned}
                onChange={(next) => onTogglePin?.(next)}
              />
            </div>
          ) : null}
        </section>

        <section>
          <Heading level={3} variant="heading-sm">
            {sections[1]}
          </Heading>
          <dl style={{ margin: 0 }}>
            <KeyValueRow
              label={f.lag}
              value={
                health?.lagMs == null
                  ? null
                  : fill(DETAIL_TEXT.lag, { "{ms}": grouped(health.lagMs) })
              }
            />
            <KeyValueRow
              label={f.rows}
              value={health?.rowsLastHour == null ? null : grouped(health.rowsLastHour)}
            />
            <KeyValueRow
              label={f.resyncs}
              value={health?.resyncsLastHour == null ? null : grouped(health.resyncsLastHour)}
            />
            <KeyValueRow
              label={f.lastWrite}
              value={
                health?.lastEventAtMs == null ? null : `${formatClock(health.lastEventAtMs)} UTC`
              }
            />
            <KeyValueRow
              label={f.dropped}
              value={
                dropped === null
                  ? null
                  : dropped > 0
                    ? fill(TEXT.detail.dropped, { "{count}": grouped(dropped) })
                    : "0"
              }
            />
          </dl>
        </section>

        <section>
          <Heading level={3} variant="heading-sm">
            {sections[2]}
          </Heading>
          <dl style={{ margin: 0 }}>
            <KeyValueRow
              label={f.size}
              value={row.diskBytes === null ? null : formatBytes(row.diskBytes)}
            />
            <KeyValueRow
              label={f.rate}
              value={
                growth === null
                  ? null
                  : `${fill(DETAIL_TEXT.rate, { "{growth}": formatGrowth(growth) })}${
                      context.estimated.has(symbol) ? ` ${DETAIL_TEXT.estimated}` : ""
                    }`
              }
            />
          </dl>
          {share === null ? null : (
            <ProgressBar
              kind="meter"
              label={f.share}
              value={share}
              valueText={fill(DETAIL_TEXT.share, { "{pct}": Math.round(share) })}
            />
          )}
        </section>

        <section>
          <Heading level={3} variant="heading-sm">
            {sections[3]}
          </Heading>
          {/* None: one plain line, never CMP-049's empty-state heading (C-5347-06); else the page's columns. */}
          {gaps.length === 0 ? (
            <Text tone="secondary">{DETAIL_TEXT.noGaps}</Text>
          ) : (
            <Table
              columns={gapColumns(context.nowMs)}
              rows={gaps}
              rowKey={(g) => `${g.fromMs}|${g.toMs}|${g.reason ?? ""}`}
              caption={sections[3]}
              captionHidden
            />
          )}
        </section>

        <div
          style={{
            display: "flex",
            flexWrap: "wrap",
            alignItems: "start",
            gap: "var(--space-inset-sm)",
          }}
        >
          {action === null ? null : (
            <span style={{ display: "inline-grid", gap: "var(--space-stack-xs)" }}>
              <Button
                variant="secondary"
                loading={actionBusy}
                {...(action.reason === undefined
                  ? {}
                  : { disabledReason: action.reason, disabledReasonId: reasonId })}
                onClick={() => onAction(action.kind)}
              >
                {actionLabel(action.kind, symbol)}
              </Button>
              {/* 2a: the reason under the action, its node in the DOM from the first paint (D02 §6.3). */}
              <Text id={reasonId} variant="caption" tone="secondary">
                {action.reason}
              </Text>
              {actionRefusal === null ? null : (
                <InlineError message={actionRefusal} live="polite" />
              )}
            </span>
          )}
          {purge === undefined || !purge.symbols.includes(symbol) ? null : (
            <Button variant="secondary" loading={purge.busy} onClick={() => purge.open(symbol)}>
              {DECK["storage.purge.button"][1]}
            </Button>
          )}
        </div>
      </div>
      {/* Outside the tracked controls: focus in SCR-006 is never the control `held` hands back (A-5347-03). */}
      {gate}
    </Drawer>
  );
}
