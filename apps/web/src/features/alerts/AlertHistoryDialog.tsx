/** Firing history of one alert (E40-S01; E40-D02 §2.6): firings newest first, suppressed ones marked, CSV export. */
import { useEffect, useState, type JSX } from "react";
import { Button, Dialog } from "@candleviewer/ui";
import type { AlertsApi } from "./alertsApi.js";
import { COPY } from "./alertsCopy.js";
import { groupFirings, historyCsv } from "./alertHistory.js";
import type { Alert, DeliveryRow } from "./types.js";

export interface AlertHistoryDialogProps {
  readonly alert: Alert;
  readonly api: Pick<AlertsApi, "deliveries">;
  readonly onClose: () => void;
  /** Where a suppressed firing's summary lives; absent until the notification centre ships. */
  readonly notificationsHref?: string | undefined;
  readonly download?: (filename: string, text: string) => void;
}

export function downloadCsv(filename: string, text: string): void {
  const url = URL.createObjectURL(new Blob([text], { type: "text/csv;charset=utf-8" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  // After the click has been handed to the browser, never in the same tick.
  setTimeout(() => URL.revokeObjectURL(url), 0);
}

const utc = (iso: string): string => {
  const ms = Date.parse(iso);
  return Number.isFinite(ms)
    ? `${new Date(ms).toISOString().slice(0, 19).replace("T", " ")} UTC`
    : iso;
};

export function AlertHistoryDialog({
  alert,
  api,
  onClose,
  notificationsHref,
  download = downloadCsv,
}: AlertHistoryDialogProps): JSX.Element {
  const [rows, setRows] = useState<readonly DeliveryRow[] | "error" | null>(null);
  const [truncated, setTruncated] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    void api.deliveries({ alertId: alert.id as string }, controller.signal).then((out) => {
      if (controller.signal.aborted) return;
      setTruncated(out.kind === "ok" && out.truncated === true);
      setRows(out.kind === "ok" ? out.value : "error");
    });
    return () => controller.abort();
  }, [api, alert.id]);
  const loaded = Array.isArray(rows) ? (rows as readonly DeliveryRow[]) : null;
  const firings = loaded === null ? [] : groupFirings(loaded);
  const H = COPY.history;
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title={H.title(alert.name)}
      size="lg"
      busy={rows === null}
      footer={
        <>
          <Button
            variant="secondary"
            iconLeft="download"
            disabled={loaded === null || loaded.length === 0}
            onClick={() => {
              if (loaded !== null) download(`alert-${alert.id}-history.csv`, historyCsv(loaded));
            }}
          >
            {H.export}
          </Button>
          <Button variant="primary" onClick={onClose}>
            {H.close}
          </Button>
        </>
      }
    >
      {rows === null ? <p role="status">{H.loading}</p> : null}
      {firings.length > 0 ? <p>{COPY.csvNote}</p> : null}
      {truncated ? <p role="note">{COPY.truncated}</p> : null}
      {rows === "error" ? <p role="alert">{H.error}</p> : null}
      {loaded !== null && firings.length === 0 ? <p>{H.empty}</p> : null}
      {firings.length > 0 ? (
        <ol aria-label={H.title(alert.name)}>
          {firings.map((firing) => (
            <li key={firing.key}>
              <time dateTime={firing.firedAt}>{utc(firing.firedAt)}</time>
              {" — "}
              {firing.channels.map((c) => `${c.channel} ${c.word}`).join(" · ")}
              {firing.message === "" ? null : <span>{`: ${firing.message}`}</span>}
              {firing.suppressedStorm ? (
                <span>
                  {` ${H.suppressed}. ${H.summary}`}
                  {notificationsHref === undefined ? null : (
                    <>
                      {" — "}
                      <a href={notificationsHref}>{H.summaryLink}</a>
                    </>
                  )}
                </span>
              ) : null}
            </li>
          ))}
        </ol>
      ) : null}
    </Dialog>
  );
}
