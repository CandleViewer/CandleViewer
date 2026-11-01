/**
 * Keep forever and a retention change (E16-D02 §6.4, §12; E16-D06 KB-07, FM-04, SD-02, SD-03, §16.4 rows 5 and 6;
 * frozen rows (i) and (iii)): CMP-044 `typed`, one dialog per change, the compliant path D-8 keeps until the owner
 * decides: Keep forever on, Keep forever off (destructive: it states what becomes eligible, about how much and
 * from when) and a retention lengthened or shortened. Focus opens on Cancel; Confirm keeps the validity look until
 * the symbol is typed exactly; Enter in the field never confirms. The `recorder` step-up runs on submit: the
 * request is held and re-sent once with the same Idempotency-Key; Esc, expiry or the third failure leave "Not sent"
 * with the inputs kept. The dialog closes on the server's answer, focus back on the opener (the switch or the
 * select), else the host's fallback when its row left meanwhile (A-5347-03); a refusal is the generic T4 at the
 * confirm. While the write is on the wire, Cancel, ✕ and Esc keep the dialog (H22), and each opening and close
 * clears the step-up host, so no challenge outlives its dialog (S-5353-01). Pessimistic: the row changes when the
 * server says so.
 */
import { useEffect, useState, type JSX, type RefObject } from "react";
import { ConfirmDialog, Text } from "@candleviewer/ui";
import { reportRecorder } from "./analytics";
import { DECK, TEXT, fill } from "./copy";
import { changeRefusal, daysText } from "./detail";
import { RETENTION_TEXT } from "./detailCopy";
import { DAY_MS, dayOf, estimateBefore, sizeText } from "./estimate";
import { DEFAULT_RETENTION_DAYS } from "./grid";
import type { RecorderRow } from "./model";
import type { RecordedSymbol } from "./model/types";
import { PAGE_TEXT } from "./pageCopy";
import { recorderApi, type ApiResult, type DataCoverage } from "./recorderApi";
import { useStepUpHost } from "./stepUpHost";

/** The change asked for: Keep forever on, off (to `days`), or a retention of `days` on an unpinned row. */
export type RetentionChange =
  | { readonly kind: "pin"; readonly row: RecorderRow }
  | { readonly kind: "unpin"; readonly row: RecorderRow; readonly days: number }
  | { readonly kind: "retention"; readonly row: RecorderRow; readonly days: number };

export interface RetentionConfirmDialogProps {
  /** The change to confirm; null while closed. */
  readonly change: RetentionChange | null;
  /** Resolves the row's id (REST's, else the list read again). */
  readonly idOf: (row: RecorderRow) => Promise<string | null>;
  /** The server's row once it accepted the change. */
  readonly onChanged: (row: RecordedSymbol) => void;
  readonly onClose: () => void;
  /** Reads the list again when a step-up's re-send got no answer ("Outcome pending"). */
  readonly readBack: () => unknown;
  /** The page's clock (ms): the estimate's "before {date}". */
  readonly now?: () => number;
  /** Where focus lands when the dialog closes and its opener is gone (the row left, FM-02, FM-04). */
  readonly fallbackFocusRef?: RefObject<HTMLElement | null> | undefined;
}

const notListed: ApiResult<RecordedSymbol> = {
  ok: false,
  status: 404,
  code: "not_found",
  data: null,
  stepUp: null,
  route: { kind: "t4", code: "not_found", field: null, status: 404 },
};

/** The dialog's words for a change: §6.4's own for Keep forever, PROPOSED for a retention (board 18 not drawn). */
function wordsOf(change: RetentionChange, size: string, date: string) {
  const { symbol, retentionDays } = change.row;
  const values = { "{symbol}": symbol, "{size}": size, "{date}": date };
  const k = TEXT.keepForever;
  if (change.kind === "pin") {
    return {
      title: fill(k.onTitle, values),
      body: fill(k.onBody, values),
      confirm: fill(RETENTION_TEXT.onConfirm, values),
      destructive: false,
    };
  }
  const days = { ...values, "{n}": change.days };
  if (change.kind === "unpin") {
    return {
      title: fill(k.offTitle, values),
      body: fill(k.offBody, { ...days, "{retention}": daysText(change.days) }),
      confirm: fill(RETENTION_TEXT.offConfirm, values),
      destructive: true,
    };
  }
  const shorter = change.days < (retentionDays ?? DEFAULT_RETENTION_DAYS);
  return shorter
    ? {
        title: fill(RETENTION_TEXT.shortenTitle, days),
        body: fill(RETENTION_TEXT.shortenBody, days),
        confirm: fill(RETENTION_TEXT.shortenConfirm, days),
        destructive: true,
      }
    : {
        title: fill(RETENTION_TEXT.lengthenTitle, days),
        body: fill(RETENTION_TEXT.lengthenBody, days),
        confirm: fill(RETENTION_TEXT.lengthenConfirm, days),
        destructive: false,
      };
}

/** The bound before which data becomes eligible: now less the retention the change leaves; null when none. */
function eligibleBefore(change: RetentionChange, nowMs: number): number | null {
  if (change.kind === "pin") return null;
  if (
    change.kind === "retention" &&
    change.days >= (change.row.retentionDays ?? DEFAULT_RETENTION_DAYS)
  ) {
    return null;
  }
  return nowMs - change.days * DAY_MS;
}

export function RetentionConfirmDialog({
  change,
  idOf,
  onChanged,
  onClose,
  readBack,
  now = Date.now,
  fallbackFocusRef,
}: RetentionConfirmDialogProps): JSX.Element | null {
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const [coverage, setCoverage] = useState<DataCoverage | null>(null);
  const stepUp = useStepUpHost(readBack, PAGE_TEXT.grid);
  const { clear } = stepUp;
  const symbol = change?.row.symbol ?? null;
  const needsEstimate = change !== null && eligibleBefore(change, now()) !== null;

  // Each opening starts clean; one that states what becomes eligible reads the symbol's coverage (C-5).
  useEffect(() => {
    setBusy(false);
    setFailure(null);
    setCoverage(null);
    clear();
    if (symbol === null || !needsEstimate) return undefined;
    let live = true;
    void recorderApi.coverage({ symbol }).then((res) => {
      if (live && res.ok) setCoverage(res.data);
    });
    return () => {
      live = false;
    };
  }, [symbol, needsEstimate, clear]);

  if (change === null) return null;
  const nowMs = now();
  const bound = eligibleBefore(change, nowMs);
  const estimate =
    bound === null
      ? null
      : estimateBefore(coverage, change.row.diskBytes, change.row.startedAt, bound, nowMs);
  const words = wordsOf(
    change,
    sizeText(estimate?.bytes ?? null),
    bound === null ? "" : dayOf(bound),
  );

  function answer(res: ApiResult<RecordedSymbol>): void {
    setBusy(false);
    if (res.ok && res.data !== null) {
      if (change !== null && change.kind !== "retention") {
        reportRecorder({
          name: "recorder.pin_toggled",
          symbol: res.data.symbol,
          pinned: change.kind === "pin",
        });
      }
      onChanged(res.data);
      onClose();
      return;
    }
    if (res.route !== null) setFailure(changeRefusal(res.route));
  }

  async function submit(): Promise<void> {
    if (change === null) return;
    setBusy(true);
    setFailure(null);
    const id = await idOf(change.row);
    let res: ApiResult<RecordedSymbol>;
    if (id === null) res = notListed;
    else if (change.kind === "retention") {
      res = await recorderApi.update(id, { retention_days: change.days });
    } else {
      res = await recorderApi.pin(
        id,
        change.kind === "pin" ? { pinned: true } : { pinned: false, retention_days: change.days },
      );
    }
    // A challenge holds the request: Confirm is a control again while SCR-006 is open (§6.4).
    if (res.stepUp !== null) setBusy(false);
    stepUp.route(
      change.kind === "retention" ? "updateRecordedSymbol" : "pinRecordedSymbol",
      res,
      answer,
    );
  }

  return (
    <ConfirmDialog
      open
      title={words.title}
      message={words.body}
      confirmLabel={words.confirm}
      confirmVariant={words.destructive ? "danger" : "primary"}
      variant="typed"
      typedConfirmValue={change.row.symbol}
      typedReason={fill(DECK["storage.purge.typed.reason"][0], { "{symbol}": change.row.symbol })}
      busy={busy}
      {...(failure === null ? {} : { failure: { message: failure } })}
      notes={
        <>
          {/* §6.4: whether a code will be asked, before the audit line; no grace source exists (#485 BQ-9). */}
          <Text tone="secondary">{DECK["storage.purge.stepup"][0]}</Text>
          <Text tone="secondary">{TEXT.keepForever.audited}</Text>
          {stepUp.gate}
        </>
      }
      {...(fallbackFocusRef === undefined ? {} : { fallbackFocusRef })}
      onConfirm={() => void stepUp.start(submit)}
      onCancel={() => stepUp.cancel(onClose)}
    />
  );
}
