/**
 * The export's rung-1 dialog (E42-S04; E42-D04 §8, §11, §12, D12, D29, AL-18, AL-19, AL-24): CMP-044
 * `alertdialog`, size Large, naming the window the file covers: From and To (CMP-047 with times,
 * UTC), prefilled from the filter's dates or the last 24 hours, at most 31 days with From before To
 * (a client check: the field carries its error and takes focus, nothing is sent); Compress
 * (CMP-005), on; the body (every entry in the window's chain span, filters don't apply), the
 * personal-data line, the static step-up line (`Me` serves no per-class grace, D03 CG-2) and the
 * marker. [Cancel] takes first focus and [Export] confirms. The body and the marker are the
 * dialog's description (D04 §12, AL-18): CMP-044's restatement, as plain text, which it renders
 * before the window's fields (A-1135P2-07).
 * - While its `POST` is in flight the window is read-only and `export.dlg.starting` shows.
 * - `403 step_up_required` (`audit`): SCR-006 through the shipped gate, over this dialog, which keeps
 *   the window; Cancel, Esc, expiry or a third wrong code drop the held request unsent and leave the
 *   gate's "Not sent" above the footer, focus back on Export (D29).
 * - A refusal is said in the dialog, assertively, once, the window kept (X3); after a `429`,
 *   Export is T2 `admin.rate_limited` until `Retry-After`. No answer is `export.unknown` with
 *   [Check again], which re-sends under the same key (X11).
 */
import { useId, useLayoutEffect, useState, type CSSProperties, type JSX } from "react";
import {
  AUDIT_FILTER_COPY,
  Checkbox,
  ConfirmDialog,
  DatePicker,
  FormField,
  auditMarkerText,
  type ConfirmFailure,
} from "@candleviewer/ui";
import { StepUpChallengeGate } from "../../stepUp/StepUpChallengeGate";
import type { AuditFilters } from "./auditFilters";
import { AUDIT_COPY as COPY, utc } from "./copy";
import type { ExportPhase, ExportWindow, StartRefusal } from "./exportJob";

/** `22` exportAuditLog: `audit_export_max_range_days`, 31 by default (the dialog's check). */
export const MAX_EXPORT_DAYS = 31;
const DAY_MS = 86_400_000;
/** The export's marker (D02 §4.3): a step-up action, "Recorded · needs your confirmation — …". */
export const EXPORT_MARKER = { codes: ["admin.audit_export"], confirm: true } as const;

const BODY: CSSProperties = { display: "grid", gap: "var(--space-stack-sm)" };
const LINE: CSSProperties = { margin: 0 };

interface Moment {
  readonly date: string | null;
  readonly time: string | null;
}
export interface WindowDraft {
  readonly from: Moment;
  readonly to: Moment;
  readonly compress: boolean;
}

const DATE_TIME = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(?:Z|[+-]\d{2}:\d{2})$/;

/** An instant as the picker's UTC day and time; none when it is no date-time. */
function momentOf(iso: string | undefined): Moment {
  if (iso === undefined || !DATE_TIME.test(iso)) return { date: null, time: null };
  const ms = Date.parse(iso);
  if (!Number.isFinite(ms)) return { date: null, time: null };
  const text = new Date(ms).toISOString();
  return { date: text.slice(0, 10), time: text.slice(11, 16) };
}

/** The picker's day and time as the RFC 3339 UTC instant the contract takes. */
const instantOf = (moment: Moment): string | null =>
  moment.date === null ? null : `${moment.date}T${moment.time ?? "00:00"}:00Z`;

/** D04 §8: the filter's dates, else the last 24 hours to the minute. */
export function draftOf(filters: AuditFilters, now: number): WindowDraft {
  const end = Math.floor(now / 60_000) * 60_000;
  const from = momentOf(filters.from);
  const to = momentOf(filters.to);
  return {
    from: from.date === null ? momentOf(new Date(end - DAY_MS).toISOString()) : from,
    to: to.date === null ? momentOf(new Date(end).toISOString()) : to,
    compress: true,
  };
}

/** The window to send, or the To field's error: From before To, at most 31 days (D04 §8). */
export function checkWindow(
  draft: WindowDraft,
): { readonly window: ExportWindow } | { readonly error: string } {
  const from = instantOf(draft.from);
  const to = instantOf(draft.to);
  if (from === null || to === null || Date.parse(from) >= Date.parse(to)) {
    return { error: COPY.audit.errRange };
  }
  if (Date.parse(to) - Date.parse(from) > MAX_EXPORT_DAYS * DAY_MS) {
    return { error: COPY.export.dlgRange };
  }
  return { window: { from, to, compress: draft.compress } };
}

/** "yyyy-mm-dd hh:mm", the body's `{from}` and `{to}`. */
const windowText = (moment: Moment): string =>
  moment.date === null ? COPY.labels.word.none : `${moment.date} ${moment.time ?? "00:00"}`;

/** A refusal's words in the dialog (X3, AL-24). */
export function refusalText(refusal: StartRefusal, viewAsReason: string | undefined): string {
  switch (refusal.kind) {
    case "range":
      return COPY.export.refused.range(refusal.days);
    case "busy":
      return COPY.export.refused.busy;
    case "rate":
      return COPY.export.refused.rate(utc.hm(refusal.until));
    case "signing":
      return COPY.export.refused.signing;
    case "store":
      return COPY.export.refused.store;
    case "read_only":
      return COPY.inflight.readOnly;
    case "view_as":
      return COPY.inflight.notSent(viewAsReason ?? "");
    case "other":
      return COPY.export.refused.other;
  }
}

export interface ExportDialogProps {
  readonly open: boolean;
  /** The window the dialog opens with. */
  readonly initial: WindowDraft;
  /** The export's start: `starting`, `step_up`, `refused` or `unknown` show here. */
  readonly phase: ExportPhase;
  /** A `429` blocks Export until then (AL-24). */
  readonly limited: boolean;
  /** The view-as sentence, for a `view_as_*` refusal's `inflight.not_sent`. */
  readonly viewAsReason?: string | undefined;
  readonly onExport: (window: ExportWindow) => void;
  readonly onCheckAgain: () => void;
  readonly onCancel: () => void;
  /** The gate re-sent the held start once. */
  readonly onResent: (response: Response) => void;
  /** The gate's re-send got no answer: the export may have started (X11). */
  readonly onLost: () => void;
}

export function ExportDialog({
  open,
  initial,
  phase,
  limited,
  viewAsReason,
  onExport,
  onCheckAgain,
  onCancel,
  onResent,
  onLost,
}: ExportDialogProps): JSX.Element {
  const fromId = useId();
  const toId = useId();
  const [draft, setDraft] = useState(initial);
  const [seen, setSeen] = useState(open);
  const [error, setError] = useState<string | undefined>(undefined);
  // Each opening starts from the window it is given (the last one, or the filter's dates).
  if (open !== seen) {
    setSeen(open);
    if (open) {
      setDraft(initial);
      setError(undefined);
    }
  }
  // An invalid window sends nothing and re-allows Export: CMP-044 re-arms when `busy` ends, so a
  // busy that ends before the frame is painted re-arms it without showing.
  const [rearm, setRearm] = useState(false);
  useLayoutEffect(() => {
    if (rearm) setRearm(false);
  }, [rearm]);
  const starting = phase.kind === "starting";
  const failure: ConfirmFailure | undefined =
    phase.kind === "refused"
      ? { message: refusalText(phase.refusal, viewAsReason) }
      : phase.kind === "unknown"
        ? {
            message: COPY.export.unknown,
            retry: { label: COPY.labels.act.checkAgain, onClick: onCheckAgain },
          }
        : undefined;
  const confirm = (): void => {
    const checked = checkWindow(draft);
    if ("error" in checked) {
      setError(checked.error);
      setRearm(true);
      document.getElementById(toId)?.focus();
      return;
    }
    setError(undefined);
    onExport(checked.window);
  };
  const setMoment = (end: "from" | "to", moment: Moment): void => {
    setDraft((now) => ({ ...now, [end]: moment }));
  };
  return (
    <ConfirmDialog
      open={open}
      title={COPY.export.dlgTitle}
      size="lg"
      confirmLabel={COPY.labels.act.export}
      cancelLabel={COPY.labels.act.cancel}
      confirmVariant="primary"
      busy={starting || rearm}
      onConfirm={confirm}
      onCancel={() => onCancel()}
      {...(failure === undefined ? {} : { failure })}
      {...(limited ? { confirmDisabledReason: COPY.admin.rateLimited } : {})}
      restatement={
        <>
          <p style={LINE}>{COPY.export.dlgBody(windowText(draft.from), windowText(draft.to))}</p>
          <p style={LINE}>{COPY.export.dlgPii}</p>
          <p style={LINE}>{COPY.export.stepUpLine}</p>
          <p style={LINE}>{auditMarkerText(EXPORT_MARKER)}</p>
        </>
      }
      restatementLabel=""
    >
      <div style={BODY}>
        <FormField label={COPY.labels.filter.from} htmlFor={fromId}>
          <DatePicker
            withTime
            timeLabel={AUDIT_FILTER_COPY.fromTime}
            value={draft.from.date}
            time={draft.from.time}
            readOnly={starting}
            onChange={(date) => setMoment("from", { ...draft.from, date })}
            onTimeChange={(time) => setMoment("from", { ...draft.from, time })}
          />
        </FormField>
        <FormField label={COPY.labels.filter.to} htmlFor={toId} error={error} errorLive={false}>
          <DatePicker
            withTime
            timeLabel={AUDIT_FILTER_COPY.toTime}
            value={draft.to.date}
            time={draft.to.time}
            readOnly={starting}
            onChange={(date) => setMoment("to", { ...draft.to, date })}
            onTimeChange={(time) => setMoment("to", { ...draft.to, time })}
          />
        </FormField>
        <Checkbox
          label={COPY.labels.field.compress}
          checked={draft.compress}
          {...(starting
            ? { disabledReason: COPY.export.dlgStarting }
            : { onChange: (compress: boolean) => setDraft((now) => ({ ...now, compress })) })}
        />
        {starting ? <p style={LINE}>{COPY.export.dlgStarting}</p> : null}
        {phase.kind === "step_up" ? (
          <StepUpChallengeGate
            key={phase.hold.challenge.challengeId}
            challenge={phase.hold.challenge}
            held={phase.hold.held}
            onResent={onResent}
            readBack={onLost}
            outcomeWhere={COPY.labels.h.auditLog}
          />
        ) : null}
      </div>
    </ConfirmDialog>
  );
}
