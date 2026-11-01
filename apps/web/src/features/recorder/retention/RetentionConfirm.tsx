/**
 * SCR-141's confirms (E16-D03 §5; E16-D06 KB-12, KB-13, SD-02 to SD-04, F-01, frozen (iii), (iv), (viii)): a reduction
 * takes CMP-044 `typed` — the title by its kind, the consequence paragraph (the symbols it cannot size named inside it)
 * as the dialog's description, the effect line, the pinned lines, the preview's total, the step-up sentence and "This
 * action is audited.", then the field "Type {word} to confirm" (exact, case-sensitive) and the destructive button naming
 * its object and its timing; anything else takes CMP-044 `standard` with the lengthening or the plain body. Both are
 * `role="dialog"` (D03-D13) and open on Cancel (F-01, E42-D02's rung order); `Enter` in the typed field confirms nothing.
 *
 * One confirm is one attempt (S-5353-01, -02): it renders the set Apply froze when it opened and sends exactly that set,
 * and it owns its step-up host, so nothing a closed confirm left held can surface under another. While its PUT is in
 * flight it is locked (H22): Cancel, ✕, the scrim and Esc do nothing. A challenge that answers it once it has closed is
 * dropped unsent and said where the action was. SCR-006 sits at one slot, whatever the variant. A drifted form (another
 * diff, a reason on Apply) closes it before anything is sent; Esc, its expiry or a third failure leave "Not sent" here.
 *
 * #484 PR 3 gives CMP-044 the typed validity look (`typedReason`, `notes`): until it lands, the destructive button is
 * natively disabled until the word matches, described by the instruction, and the closing lines sit above the field.
 */
import { useEffect, useRef, type JSX } from "react";
import { ConfirmDialog, Text } from "@candleviewer/ui";
import type {
  ApiResult,
  RetentionPoliciesBody,
  RetentionPoliciesSaved,
  RetentionQuery,
} from "../recorderApi";
import { useStepUpHost } from "../stepUpHost";
import { RETENTION_DECK } from "./retentionCopy";
import type { Preview, SteadyState } from "./retentionEstimate";
import type { Classification, SymbolCode } from "./retentionModel";
import {
  confirmLabelText,
  consequenceText,
  pinnedLines,
  plainConfirmText,
  previewTotalText,
  titleText,
  typedLabel,
} from "./retentionText";

/** The confirm as Apply opened it: what it shows is what it sends (S-5353-02). */
export interface ConfirmAttempt {
  /** One per opening: the confirm and its step-up host are keyed by it. */
  readonly n: number;
  readonly body: RetentionPoliciesBody;
  readonly query: RetentionQuery;
  /** The request's items as JSON: a form whose items differ has drifted off this confirm. */
  readonly diff: string;
  /** The classification as JSON: a form that would say other words has drifted off it too. */
  readonly shape: string;
  readonly classification: Classification;
  /** The preview rendered for this diff (a reduction always has one before its confirm opens). */
  readonly preview: Preview | null;
  /** The symbols the change reaches that the storage report does not list: named, never sized. */
  readonly unlisted: readonly SymbolCode[];
  readonly steady: SteadyState | null;
  readonly applyNow: boolean;
  /** The add row was complete when the confirm opened, so `body` carries it. */
  readonly pendingSent: boolean;
}

export interface RetentionConfirmProps {
  readonly open: boolean;
  readonly attempt: ConfirmAttempt;
  /** The PUT is in flight: the confirm is locked (H22). */
  readonly busy: boolean;
  /** The form no longer matches this confirm (another diff, or Apply has a reason): nothing is sent. */
  readonly drifted: boolean;
  /** Sends `attempt.body` once (the editor's PUT); a renewal calls it again as a new request. */
  readonly send: () => Promise<ApiResult<RetentionPoliciesSaved>>;
  /** The PUT's answer, or its re-send's after the step-up. */
  readonly onAnswer: (res: ApiResult<RetentionPoliciesSaved>) => void;
  /** A challenge answered this confirm after it closed: dropped unsent, said at the point of action. */
  readonly onNotSent: () => void;
  /** The re-send got no answer: its outcome is unknown, so the editor reads the set back (never "Not sent"). */
  readonly onOutcomeUnknown: () => Promise<void>;
  /** The form drifted while this confirm was open: it closes before anything is sent. */
  readonly onDrift: () => void;
  readonly onCancel: () => void;
  /** CMP-044's clock (its guard), injectable for tests. */
  readonly now?: (() => number) | undefined;
}

export function RetentionConfirm({
  open,
  attempt,
  busy,
  drifted,
  send,
  onAnswer,
  onNotSent,
  onOutcomeUnknown,
  onDrift,
  onCancel,
  now,
}: RetentionConfirmProps): JSX.Element {
  const stepUp = useStepUpHost(onOutcomeUnknown, RETENTION_DECK["retention.title"][0]);
  const { clear } = stepUp;
  /** This confirm is open: an answer that finds it closed holds nothing. */
  const live = useRef(open);
  useEffect(() => {
    live.current = open;
    // Closed: no challenge of this attempt stays held, and its gate goes with it.
    if (!open) clear();
  }, [open, clear]);
  useEffect(
    () => () => {
      live.current = false;
    },
    [],
  );
  // The form moved under the confirm: it closes, its PUT in flight or not (a challenge that answers it then is
  // dropped). SCR-006, its re-send or its notice wait for the next press instead.
  const gated = stepUp.gate !== null;
  useEffect(() => {
    if (open && drifted && !gated) onDrift();
  }, [open, drifted, gated, onDrift]);

  function confirm(): void {
    if (drifted) {
      onDrift();
      return;
    }
    void stepUp.start(async () => {
      const res = await send();
      if (res.stepUp !== null && !live.current) {
        onNotSent();
        return;
      }
      stepUp.route("setRetentionPolicies", res, onAnswer);
    });
  }
  // H22: a request in flight keeps its confirm, so its answer lands where it was asked for.
  const cancel = (): void => {
    if (!busy) onCancel();
  };

  const { classification, preview, unlisted, steady, applyNow } = attempt;
  const clock = now === undefined ? {} : { now };
  const reduction = classification.kind === "reduction" ? classification : null;
  const plain = reduction === null ? plainConfirmText(classification, steady, applyNow) : null;
  const sized = preview?.rows.length ?? 0;
  // Two symbols or fewer: the preview's summary line; more say their size once, in the paragraph.
  const total =
    preview !== null && sized > 0 && sized + unlisted.length <= 2
      ? previewTotalText(preview)
      : null;
  const variant =
    reduction === null
      ? ({
          title: plain?.title ?? "",
          confirmLabel: RETENTION_DECK["retention.footer.buttons"][1],
          confirmVariant: "primary",
        } as const)
      : ({
          title: titleText(reduction.confirm.title),
          variant: "typed",
          typedConfirmValue: reduction.confirm.word,
          typedInstruction: typedLabel(reduction.confirm.word),
          confirmLabel: confirmLabelText(reduction.confirm.timing),
          confirmVariant: "danger",
        } as const);
  const restatement =
    reduction === null
      ? (plain?.body ?? "")
      : consequenceText(reduction.confirm, preview, true, unlisted);
  return (
    <ConfirmDialog
      open={open}
      role="dialog"
      {...variant}
      restatement={<p style={{ margin: 0 }}>{restatement}</p>}
      restatementLabel=""
      busy={busy}
      onConfirm={() => confirm()}
      onCancel={() => cancel()}
      {...clock}
    >
      {reduction === null ? null : (
        <>
          <Text as="p" tone="secondary">
            {RETENTION_DECK["retention.effect"][0]}
          </Text>
          {pinnedLines(reduction.exempt).map((line) => (
            <Text key={line} as="p">
              {line}
            </Text>
          ))}
          {total === null ? null : <Text as="p">{total}</Text>}
        </>
      )}
      <Text as="p">{RETENTION_DECK["retention.stepup.code"][0]}</Text>
      <Text as="p" tone="secondary">
        {RETENTION_DECK["retention.audited"][0]}
      </Text>
      {/* One slot for SCR-006 and its notice, whatever the variant: it never remounts under its own press. */}
      {stepUp.gate}
    </ConfirmDialog>
  );
}
