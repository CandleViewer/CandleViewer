/**
 * Purge data… (E16-D02 §6.5; E16-D04 §1.3, §7; E16-D06 KB-07, SD-01 to SD-03, T2-10, §16.4 rows 2, 3, 9 to 15; frozen
 * rows (ii), (iii) and (viii)): the one purge dialog, SCR-140's and SCR-142's (BQ-9 there: no second shape), a CMP-044
 * `typed` form, `role="dialog"` with its close button. Symbol (the row's preselected), "Delete data recorded before"
 * (the retention cut-off by default; its help), the consequence (about how much, from when to when, that it cannot be
 * undone: the dialog's description), Reason (3–280 characters), Include pinned (a pinned symbol only), then the typed
 * symbol, empty at every opening and never pre-filled, the step-up sentence and the audit line. Focus opens on Cancel;
 * Confirm keeps the validity look while the typed symbol differs, the date typed does not parse (CMP-047's own words:
 * the bound is never the last valid day's, A-5347-d02), the bound is later than now or the reason is short (in that
 * order, one reason under it); Enter in a field never confirms. The `recorder_purge` step-up runs on submit
 * (no grace: a fresh code each time), the request held and re-sent once with the same Idempotency-Key. A refusal shows
 * at the confirm, its code in parentheses, the inputs kept: the deck's sentence where §16.4 names one, "A purge is
 * running." for a 409 `job_running`, else the generic T4 (a 2xx with no job id too). The server's 202 closes it and
 * hands its job to the page. `confirm_symbol` is the typed field's text exactly as typed, never the Symbol select's
 * (the server checks the echo: S-5347-01). While the purge is on the wire every input is locked and Cancel, ✕, the
 * scrim and Esc keep the dialog (H22); each opening and close clears the step-up host (S-5353-01). A re-send with
 * no answer points at the Recording budget, whose figures are read again (S-5347-03). An expired challenge offers no
 * renewal of the purge as pressed: a fresh Confirm sends what the dialog shows (S-5347-d02).
 */
import { useEffect, useId, useRef, useState, type JSX, type RefObject } from "react";
import {
  Checkbox,
  ConfirmDialog,
  DatePicker,
  FormField,
  Select,
  Text,
  TextInput,
} from "@candleviewer/ui";
import { DECK, TEXT, fill } from "./copy";
import { DETAIL_REFUSED } from "./detailCopy";
import { estimateBefore } from "./estimate";
import { PAGE_TEXT } from "./pageCopy";
import {
  REASON_MAX,
  beforeInstant,
  beforeMs,
  defaultBefore,
  purgeBody,
  purgeValidity,
  type PurgeJob,
  type PurgeTarget,
} from "./purge";
import {
  recorderApi,
  type ApiResult,
  type DataCoverage,
  type JobAccepted,
  type RefusalRoute,
} from "./recorderApi";
import { refusalText } from "./refusal";
import { useStepUpHost, type StepUpRoute } from "./stepUpHost";

export interface PurgeDialogProps {
  readonly open: boolean;
  /** The symbol preselected (a row's Purge…); null: the first offered (the card's and the banner's Purge data…). */
  readonly symbol: string | null;
  /** What the Symbol select offers, with what the estimate reads. */
  readonly symbols: readonly PurgeTarget[];
  readonly onClose: () => void;
  /** The server accepted the purge (202): its job, for the page to follow. */
  readonly onStarted: (job: PurgeJob) => void;
  /** Reads the affected state back when a step-up's re-send got no answer ("Outcome pending"). */
  readonly readBack: () => unknown;
  /** The clock (ms): the default bound, "later than now" and the estimate; injectable for tests. */
  readonly now?: () => number;
  /** Where focus lands when the dialog closes and its opener is gone (A-5347-03, FM-04). */
  readonly fallbackFocusRef?: RefObject<HTMLElement | null> | undefined;
}

/** A refused purge (§16.4): the deck's sentence, §6.5's "A purge is running.", or the generic T4. */
export function purgeRefusal(route: RefusalRoute): string {
  if (route.kind === "deck") {
    return route.key === "storage.job.refused.running"
      ? `${TEXT.purge.running} (${route.code})`
      : refusalText(route, "compact");
  }
  if (route.kind === "t4" && route.status === 0) return PAGE_TEXT.unreachable;
  const code = route.kind === "t4" ? route.code : "step_up_required";
  return code === null ? DETAIL_REFUSED.purge : `${DETAIL_REFUSED.purge} (${code})`;
}

export function PurgeDialog({
  open,
  symbol: preselected,
  symbols,
  onClose,
  onStarted,
  readBack,
  now = Date.now,
  fallbackFocusRef,
}: PurgeDialogProps): JSX.Element | null {
  const id = useId();
  const [symbol, setSymbol] = useState<string | null>(null);
  const [day, setDay] = useState<string | null>(null);
  /** The date field's typed error (CMP-047 commits nothing invalid, so `day` is still the last valid one). */
  const [dateError, setDateError] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const [includePinned, setIncludePinned] = useState(false);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const [coverage, setCoverage] = useState<DataCoverage | null>(null);
  // No renewal of the purge as pressed: once a challenge expires the inputs are the Owner's again, so a fresh Confirm
  // (a fresh code, E16-D04 §7) sends what the dialog then shows (S-5347-d02).
  const stepUp = useStepUpHost(readBack, PAGE_TEXT.budget, { renewal: false });
  const { clear } = stepUp;

  // Each opening starts from the row's symbol (or the first offered) and its retention cut-off (§6.5). Read at the
  // opening only: a frame's new figures never reset what the Owner has typed.
  const opening = useRef({ first: preselected ?? symbols[0]?.symbol ?? null, symbols, now });
  opening.current = { first: preselected ?? symbols[0]?.symbol ?? null, symbols, now };
  useEffect(() => {
    if (!open) return;
    const { first, symbols: offered, now: clock } = opening.current;
    setSymbol(first);
    setDay(
      defaultBefore(
        offered.find((s) => s.symbol === first),
        clock(),
      ),
    );
    setReason("");
    setIncludePinned(false);
    setBusy(false);
    setFailure(null);
    setDateError(null);
    clear();
  }, [open, clear]);

  // The estimate's coverage, read for the chosen symbol (C-5: an estimate; the audit record is exact).
  useEffect(() => {
    setCoverage(null);
    if (!open || symbol === null) return undefined;
    let live = true;
    void recorderApi.coverage({ symbol }).then((res) => {
      if (live && res.ok) setCoverage(res.data);
    });
    return () => {
      live = false;
    };
  }, [open, symbol]);

  if (!open || symbol === null) return null;
  const target = symbols.find((s) => s.symbol === symbol);
  const nowMs = now();
  const bound = beforeMs(day) ?? nowMs;
  const estimate = estimateBefore(
    coverage,
    target?.diskBytes ?? null,
    target?.startedAt ?? null,
    bound,
    nowMs,
  );
  const pinned = target?.pinned === true;
  const fills = { "{symbol}": symbol };

  function answer(res: ApiResult<JobAccepted>): void {
    setBusy(false);
    const jobId = res.ok ? res.data?.job_id : undefined;
    if (typeof jobId === "string" && jobId !== "" && day !== null && symbol !== null) {
      onStarted({ jobId, symbol, beforeMs: beforeMs(day) ?? nowMs });
      return;
    }
    // A 2xx with no job id starts nothing the page can follow: the generic T4, never a silent no-op (S-5347-04).
    setFailure(
      purgeRefusal(res.route ?? { kind: "t4", code: null, field: null, status: res.status }),
    );
  }

  async function submit(route: StepUpRoute, typedValue: string): Promise<void> {
    if (day === null || symbol === null) return;
    setBusy(true);
    setFailure(null);
    const res = await recorderApi.purge({
      symbol,
      // What the Owner typed, exactly (CMP-044's `typedValue`): the server's echo check is theirs (S-5347-01).
      confirm_symbol: typedValue,
      reason: reason.trim(),
      before: beforeInstant(day),
      include_pinned: pinned && includePinned,
    });
    // A challenge holds the request: Confirm is a control again while SCR-006 is open (§6.4).
    if (res.stepUp !== null) setBusy(false);
    route("purgeRecordedData", res, answer);
  }

  const noEnter = (event: { key: string; preventDefault: () => void }): void => {
    if (event.key === "Enter") event.preventDefault();
  };

  return (
    <ConfirmDialog
      open
      role="dialog"
      title={fill(DECK["storage.purge.title"][0], fills)}
      aria-describedby={`${id}-body`}
      confirmLabel={fill(DECK["storage.purge.confirm"][0], fills)}
      cancelLabel={TEXT.purge.cancel}
      confirmVariant="danger"
      variant="typed"
      typedConfirmValue={symbol}
      typedInstruction={DECK["storage.purge.typed"][0]}
      typedReason={fill(DECK["storage.purge.typed.reason"][0], fills)}
      validityReason={purgeValidity(day, reason, nowMs, dateError)}
      busy={busy}
      {...(failure === null ? {} : { failure: { message: failure } })}
      // `recorder_purge` is no-grace: always the code sentence (E16-D04 §7), before the audit line.
      notes={
        <>
          <Text tone="secondary">{DECK["storage.purge.stepup"][0]}</Text>
          <Text tone="secondary">{DECK["storage.purge.audited"][0]}</Text>
          {stepUp.gate}
        </>
      }
      {...(fallbackFocusRef === undefined ? {} : { fallbackFocusRef })}
      onConfirm={(meta) => void stepUp.start((route) => submit(route, meta.typedValue ?? ""))}
      onCancel={() => stepUp.cancel(onClose)}
    >
      <div style={{ display: "flex", flexWrap: "wrap", gap: "var(--space-inset-md)" }}>
        <FormField label={TEXT.purge.symbol}>
          <Select
            options={symbols.map((s) => ({ value: s.symbol, label: s.symbol }))}
            value={symbol}
            disabled={busy}
            onChange={(next) => {
              setSymbol(next);
              setIncludePinned(false);
            }}
          />
        </FormField>
        <FormField
          label={DECK["storage.purge.before"][0]}
          help={DECK["storage.purge.before.help"][0]}
        >
          <DatePicker
            value={day}
            onChange={setDay}
            onInvalidChange={setDateError}
            now={now}
            readOnly={busy}
          />
        </FormField>
      </div>
      <Text id={`${id}-body`}>{purgeBody(estimate, day ?? "—")}</Text>
      <FormField label={TEXT.purge.reason}>
        <TextInput
          value={reason}
          maxLength={REASON_MAX}
          readOnly={busy}
          autoComplete="off"
          onChange={(event) => setReason(event.currentTarget.value)}
          onKeyDown={noEnter}
        />
      </FormField>
      {pinned ? (
        <div style={{ display: "grid", gap: "var(--space-stack-xs)" }}>
          <Checkbox
            label={TEXT.purge.includePinned}
            checked={includePinned}
            onChange={setIncludePinned}
            disabled={busy}
          />
          {includePinned ? <Text tone="secondary">{TEXT.purge.pinnedToo}</Text> : null}
        </div>
      ) : null}
    </ConfirmDialog>
  );
}
