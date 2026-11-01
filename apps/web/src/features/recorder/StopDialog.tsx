/**
 * The stop confirmation (E16-D02 §6.2, §6.3; E16-D06 KB-06, FM-04): CMP-044, no typed field, since a
 * stop deletes nothing; "Keep recording" is the default button, so it is Cancel and takes first
 * focus. A confirmed stop is pessimistic: the confirm is `loading` until the server answers. A
 * `409 conflict` (the frame lagged) shows E09-D09's T4 at the confirm, re-sends nothing, and keeps
 * the confirm `loading` until the next `recorder` frame: with a stop refusal by then, the row's §8.5
 * reason turns the confirm T2; without one, or once the page is stale, it returns to T1.
 */
import { useEffect, useState, type JSX } from "react";
import { ConfirmDialog } from "@candleviewer/ui";
import { TEXT, fill } from "./copy";
import { DEFAULT_RETENTION_DAYS } from "./grid";
import { formatDuration, stopBlockedKey, t2Reason, type RecorderRow } from "./model";
import type { RecorderPolicy } from "./model/types";
import type { ApiResult } from "./recorderApi";
import { refusalText } from "./refusal";

export interface StopDialogProps {
  /** The row as it reads now (the 1 Hz frame); null while closed. */
  readonly row: RecorderRow | null;
  readonly policy: RecorderPolicy | null;
  /** When the newest `recorder` frame was read: a 409's `loading` lasts until it changes. */
  readonly frameAtMs: number | null;
  readonly stale: boolean;
  /** Sends the stop (`removeRecordedSymbol`); the host resolves the row's id. */
  readonly stop: (row: RecorderRow) => Promise<ApiResult<null>>;
  /** The server accepted the stop. */
  readonly onStopped: (row: RecorderRow) => void;
  readonly onClose: () => void;
  /** The confirm's clock (CMP-044's guard), injectable for tests. */
  readonly now?: () => number;
}

export function StopDialog({
  row,
  policy,
  frameAtMs,
  stale,
  stop,
  onStopped,
  onClose,
  now,
}: StopDialogProps): JSX.Element | null {
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  /** A 409's frame: `loading` holds until a newer one is read. */
  const [waitingFrom, setWaitingFrom] = useState<number | null | undefined>(undefined);
  const [blocked, setBlocked] = useState<string | undefined>(undefined);
  const grace = policy === null ? "" : formatDuration(policy.autostop_grace_s);
  const symbol = row?.symbol ?? null;

  // A new opening starts clean.
  useEffect(() => {
    setBusy(false);
    setFailure(null);
    setWaitingFrom(undefined);
    setBlocked(undefined);
  }, [symbol]);

  // The next frame after a 409 (or the page turning stale) ends the wait: T2 with the row's reason, else T1.
  useEffect(() => {
    if (waitingFrom === undefined || row === null) return;
    if (!stale && frameAtMs === waitingFrom) return;
    setWaitingFrom(undefined);
    setBusy(false);
    const key = stale ? null : stopBlockedKey(row);
    setBlocked(key === null ? undefined : t2Reason(key, grace));
  }, [waitingFrom, frameAtMs, stale, row, grace]);

  if (row === null) return null;
  const retention = `${row.retentionDays ?? DEFAULT_RETENTION_DAYS} days`;
  const confirm = async (): Promise<void> => {
    setBusy(true);
    setFailure(null);
    const res = await stop(row);
    if (res.ok) {
      onStopped(row);
      return;
    }
    setFailure(res.route === null ? null : refusalText(res.route, "stop"));
    if (res.status === 409) setWaitingFrom(frameAtMs);
    else setBusy(false);
  };
  return (
    <ConfirmDialog
      open
      title={fill(TEXT.stop.title, { "{symbol}": row.symbol })}
      message={fill(TEXT.stop.body, {
        "{symbol}": row.symbol,
        "{grace}": grace,
        "{retention}": retention,
      })}
      cancelLabel={TEXT.stop.keep}
      confirmLabel={TEXT.stop.confirm}
      confirmVariant="primary"
      busy={busy}
      {...(failure === null ? {} : { failure: { message: failure } })}
      {...(blocked === undefined ? {} : { confirmDisabledReason: blocked })}
      {...(now === undefined ? {} : { now })}
      onConfirm={() => void confirm()}
      onCancel={onClose}
    />
  );
}
