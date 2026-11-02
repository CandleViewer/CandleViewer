/**
 * S-36's bulk-cancel dialog (E29-S02 PR2; E29-D02 §8.3, D01 D7): "Cancel selected" and "Cancel all in
 * view…" open it; it never opens for one row's own Cancel, which asks nothing (D02 §8.2).
 *
 * - **Confirm** (CMP-044, `alertdialog`): the target rows (symbol, side, size, account, environment),
 *   or past ten rows in view the active chips restated; the count per account; and the rows left
 *   out, the native-stop line first (D02 §8.5). LIVE adds the typed word (D01 D7); nothing is sent
 *   before Confirm, and "Keep orders" sends nothing.
 * - **Result** (CMP-043): one line per account, a failure in its reason's words and the rows it left
 *   under it, nothing dropped (the "Cancel-all partial failure" scenario); "Retry failed" sends a new
 *   request for the failed targets only (BQ-8). The lines in its body describe it (`aria-describedby`),
 *   so opening it says them once; it opens on its first control (D02 §11.1).
 */
import { useId, useRef, type JSX, type RefObject } from "react";
import { Button, ConfirmDialog, Dialog } from "@candleviewer/ui";
import { DECK } from "../copy";
import { bindProposed } from "./copy";
import {
  countText,
  excludedLines,
  lineText,
  type AccountWords,
  type BulkPlan,
  type BulkResult,
} from "./model/bulk";
import { orderLine } from "./view";

/** D02 §8.3: past this many rows in view, Cancel all in view restates the chips instead of a list. */
export const LIST_AT_MOST = 10;

export type BulkState =
  | { readonly phase: "confirm" | "sending"; readonly plan: BulkPlan }
  | { readonly phase: "result"; readonly result: BulkResult; readonly sending: boolean };

export interface BulkCancelDialogProps {
  readonly state: BulkState | null;
  /** LIVE asks for the typed word (D01 D7). */
  readonly live: boolean;
  /** The active chips restated ("Account: Sub-1 · Symbol: BTCUSDT"), `""` with none. */
  readonly chipsLine: string;
  readonly wordsOf: (accountId: string) => AccountWords;
  /** The environment's word for a target's line. */
  readonly environment: string;
  readonly onConfirm: () => void;
  readonly onRetry: () => void;
  readonly onClose: () => void;
  /** Where focus returns when the dialog's opener has gone (D02 §11.1: never `body`). */
  readonly fallbackFocusRef?: RefObject<HTMLElement | null> | undefined;
}

const countsOf = (plan: BulkPlan): readonly [string, number][] => {
  const counts = new Map<string, number>();
  for (const row of plan.targets) counts.set(row.accountId, (counts.get(row.accountId) ?? 0) + 1);
  return [...counts];
};

function Restatement({
  plan,
  chipsLine,
  wordsOf,
  environment,
}: Pick<BulkCancelDialogProps, "chipsLine" | "wordsOf" | "environment"> & {
  readonly plan: BulkPlan;
}): JSX.Element {
  const listed = plan.scope === "selected" || plan.targets.length <= LIST_AT_MOST;
  return (
    <div className="cv-orders-bulk" data-part="BulkRestatement">
      {listed ? (
        <ul className="cv-orders-bulk__targets">
          {plan.targets.map((row) => (
            <li key={row.id}>{orderLine(row, environment)}</li>
          ))}
        </ul>
      ) : chipsLine === "" ? null : (
        <p>{chipsLine}</p>
      )}
      <ul className="cv-orders-bulk__counts">
        {countsOf(plan).map(([accountId, n]) => (
          <li key={accountId}>{countText(n, wordsOf(accountId))}</li>
        ))}
      </ul>
      {excludedLines(plan.excluded).map((line) => (
        <p key={line} className="cv-orders-bulk__excluded">
          {line}
        </p>
      ))}
    </div>
  );
}

export function BulkCancelDialog({
  state,
  live,
  chipsLine,
  wordsOf,
  environment,
  onConfirm,
  onRetry,
  onClose,
  fallbackFocusRef,
}: BulkCancelDialogProps): JSX.Element {
  const footer = useRef<HTMLSpanElement>(null);
  const resultId = useId();
  const plan = state === null ? null : state.phase === "result" ? state.result.plan : state.plan;
  const n = String(plan?.targets.length ?? 0);
  const one = plan?.targets.length === 1;
  const confirming = state !== null && state.phase !== "result";
  const result = state?.phase === "result" ? state : null;
  return (
    <>
      <ConfirmDialog
        open={confirming}
        title={
          one
            ? bindProposed("blotter.ui.bulk.cancel_title.one")
            : bindProposed("blotter.ui.bulk.cancel_title", { "4": n })
        }
        confirmLabel={
          one
            ? bindProposed("blotter.ui.bulk.cancel_confirm.one")
            : bindProposed("blotter.ui.bulk.cancel_confirm", { "4": n })
        }
        cancelLabel={bindProposed("blotter.ui.bulk.cancel_keep")}
        confirmVariant="danger"
        variant={live ? "typed" : "standard"}
        {...(live ? { typedConfirmValue: bindProposed("blotter.ui.bulk.typed_word") } : {})}
        busy={state?.phase === "sending"}
        restatement={
          plan === null ? undefined : (
            <Restatement
              plan={plan}
              chipsLine={chipsLine}
              wordsOf={wordsOf}
              environment={environment}
            />
          )
        }
        onConfirm={onConfirm}
        onCancel={onClose}
        fallbackFocusRef={fallbackFocusRef}
      />
      <Dialog
        open={result !== null}
        onOpenChange={(open) => {
          if (!open) onClose();
        }}
        title={bindProposed("blotter.ui.result.title")}
        busy={result?.sending === true}
        initialFocusRef={footer}
        {...(fallbackFocusRef === undefined ? {} : { fallbackFocusRef })}
        aria-describedby={resultId}
        footer={
          <span ref={footer} className="cv-orders-bulk__footer">
            <Button onClick={onClose}>{bindProposed("blotter.ui.result.close")}</Button>
            {result?.result.retry == null ? null : (
              <Button variant="primary" loading={result.sending} onClick={onRetry}>
                {DECK["blotter.ui.result.retry"].string}
              </Button>
            )}
          </span>
        }
      >
        {result === null ? null : (
          <div id={resultId} className="cv-orders-bulk" data-part="BulkResult">
            <ul className="cv-orders-bulk__lines">
              {result.result.lines.map((line) => (
                <li key={line.accountId} data-kind={line.kind}>
                  {lineText(line, wordsOf(line.accountId))}
                  {line.failedRows.length === 0 ? null : (
                    <ul>
                      {line.failedRows.map((row) => (
                        <li key={row.id}>{orderLine(row, environment)}</li>
                      ))}
                    </ul>
                  )}
                </li>
              ))}
            </ul>
            {excludedLines(result.result.plan.excluded).map((line) => (
              <p key={line} className="cv-orders-bulk__excluded">
                {line}
              </p>
            ))}
          </div>
        )}
      </Dialog>
    </>
  );
}
