import { useId, useState, type JSX, type KeyboardEvent, type MouseEvent } from "react";
import { Icon } from "../../icons/Icon.js";
import { Checkbox } from "../Checkbox.js";
import { Countdown } from "../Countdown.js";
import { cx } from "./cx.js";
import { useRoving, type RovingItemProps } from "./useRoving.js";

/*
 * CMP-044's ladder parts (E42-S02; E42-D03 §12, E42-D02 §4.1 and §4.3; `15` CMP-044's catalogued props): the rung
 * that derives the variant, the two-choice block, the acknowledgement, the step-up line and the audit marker. The
 * dialog owns the validity form and its hint; these parts own their rows and their words.
 */

/** E42-D03 §12's rung (AD-11): 0 hold, 1–2 standard, 3 typed, 4 typed where a typed value exists, else standard. */
export type ConfirmRung = 0 | 1 | 2 | 3 | 4;

/** One option of the two-choice block (UD-11/12): neither is ever pre-selected. */
export interface ConfirmChoice {
  /** Stable key: what `choice` and `onChoiceChange` carry. */
  readonly id: string;
  /** The option's whole label ("Leave positions open — you take over"). */
  readonly label: string;
  /** What choosing it does: the option's second line and its description (third, under a reason). */
  readonly consequence: string;
  /**
   * T2 (E09-D09 §2.2, rendering 2a): the option keeps `role="radio"` with `aria-disabled`, the CMP-019 `lock` (named
   * "Not available") leads its label, and this reason is its second line and its description; the arrows focus it
   * without checking it, and Space, Enter or a press re-shows the reason once. A key of E09-D09 §3.1, or one
   * proposed to it until registered (`admin.needs_count`).
   */
  readonly disabledReason?: string | undefined;
}

/** The unknown-positions tick (E42-D03 D21): a CMP-005 after the choices; Confirm waits on it. */
export interface ConfirmAcknowledge {
  readonly label: string;
  readonly checked: boolean;
  readonly onChange: (checked: boolean) => void;
}

/** The step-up line (E42-D02 §4.1): none, a live grace window, a code to come, or a fresh code every time (rung 4). */
export type ConfirmStepUpState = "none" | "grace" | "code" | "fresh";

/** One registered audit code and its SCR-135 label (E42-D02 D5): "{label} ({code})". */
export interface ConfirmAuditCode {
  readonly label: string;
  readonly code: string;
}

/** The ladder's words: CMP-044's catalogue (`15:519`), E42-D02 §4.1 and §4.3, E42-D03 §14 `dlg.*` (proposed). */
export const LADDER_COPY = {
  /** `dlg.choose_first`: a validity hint, never a T2 reason. */
  chooseFirst: "Choose an option first.",
  /** `dlg.ack_first`: a validity hint, never a T2 reason. */
  ackFirst: "Tick the acknowledgement first.",
  stepUpCode: "You'll confirm with your password and a code.",
  stepUpFresh: "This always needs a fresh code.",
  stepUpGrace: (classLabel: string): string => `Still trusted for ${classLabel} · `,
  marker: "Recorded in the audit log",
  /** E09-D09 §10 `glyph.name`: the lock's name where it leads a label. */
  lockName: "Not available",
} as const;

/** The variant a rung derives (`15` CMP-044 Props): 0 hold, 1–2 standard, 3 typed, 4 typed with a value, else standard. */
export function rungVariant(
  rung: ConfirmRung,
  typedConfirmValue: string | undefined,
): "standard" | "typed" | "hold" {
  if (rung === 0) return "hold";
  if (rung === 3) return "typed";
  if (rung === 4 && typedConfirmValue !== undefined && typedConfirmValue !== "") return "typed";
  return "standard";
}

/** A T2 option's reason; whitespace alone is none (a sighted user would see nothing). */
export function choiceReason(choice: ConfirmChoice): string | undefined {
  const reason = choice.disabledReason?.trim();
  return reason === undefined || reason === "" ? undefined : reason;
}

/** "Recorded in the audit log · Disable user (users.disable) + …"; with no code, the first words alone (D02 §4.3). */
export function markerText(codes: readonly ConfirmAuditCode[]): string {
  const named = codes.map((entry) => `${entry.label} (${entry.code})`).join(" + ");
  return named === "" ? LADDER_COPY.marker : `${LADDER_COPY.marker} · ${named}`;
}

interface ChoiceOptionProps {
  readonly choice: ConfirmChoice;
  readonly checked: boolean;
  readonly roving: RovingItemProps;
  readonly onChoose: (id: string) => void;
  readonly onRefused: (reason: string) => void;
}

/** One radio of the block: CMP-006's ring and focus ring, its label, its reason (T2) and its consequence. */
function ChoiceOption({
  choice,
  checked,
  roving,
  onChoose,
  onRefused,
}: ChoiceOptionProps): JSX.Element {
  const base = useId();
  const labelId = `${base}-label`;
  const reasonId = `${base}-reason`;
  const consequenceId = `${base}-consequence`;
  const reason = choiceReason(choice);
  const onKeyDown = (event: KeyboardEvent<HTMLElement>): void => {
    // Enter never confirms from the group (a radio has no Enter of its own), and a held key acts once.
    if (event.key === "Enter" || (event.key === " " && event.repeat)) {
      event.preventDefault();
      if (event.key === "Enter" && !event.repeat && reason !== undefined) onRefused(reason);
      return;
    }
    roving.onKeyDown(event);
  };
  const onClick = (event: MouseEvent<HTMLElement>): void => {
    // The whole row is the target; a T2 option takes focus to show its reason and changes nothing.
    event.currentTarget.focus();
    if (reason === undefined) onChoose(choice.id);
    else onRefused(reason);
  };
  return (
    <div
      ref={roving.ref}
      role="radio"
      tabIndex={roving.tabIndex}
      aria-checked={checked}
      aria-disabled={reason === undefined ? undefined : true}
      aria-labelledby={labelId}
      aria-describedby={cx(reason !== undefined && reasonId, consequenceId)}
      className="cv-radio cv-focus-ring-host cv-confirm__choice"
      data-checked={checked ? "" : undefined}
      data-gated={reason === undefined ? undefined : ""}
      onKeyDown={onKeyDown}
      onFocus={roving.onFocus}
      onBlur={roving.onBlur}
      onClick={onClick}
    >
      <span className="cv-radio__mark" aria-hidden="true">
        <span className="cv-radio__ring cv-focus-ring-target" />
      </span>
      <span className="cv-confirm__choice-text">
        <span id={labelId} className="cv-confirm__choice-label">
          {reason === undefined ? null : (
            <span className="cv-confirm__choice-lock">
              <Icon name="lock" decorative={false} label={LADDER_COPY.lockName} />
            </span>
          )}
          {choice.label}
        </span>
        {reason === undefined ? null : (
          <span id={reasonId} className="cv-confirm__choice-reason">
            {reason}
          </span>
        )}
        <span id={consequenceId} className="cv-confirm__choice-consequence">
          {choice.consequence}
        </span>
      </span>
    </div>
  );
}

export interface LadderInputsProps {
  readonly choices: readonly ConfirmChoice[];
  /** The block's lead: its visible first line and the radiogroup's name. */
  readonly lead: string;
  /** The chosen id (the host's); a T2 option is never shown checked. */
  readonly choice: string | undefined;
  readonly onChoose: (id: string) => void;
  readonly acknowledge: ConfirmAcknowledge | undefined;
  readonly onAcknowledge: (checked: boolean) => void;
  /** A T2 option's reason, re-shown once per press in the dialog's polite region. */
  readonly onRefused: (reason: string) => void;
}

/**
 * The two-choice block and the tick, in that order (E42-D03 §12): the radiogroup is labelled by its lead,
 * `aria-required`, none checked; Tab enters it without checking (the first option holds the stop), Space checks, the
 * arrows move and check, except that a T2 option is focused without being checked and the checked one stays. Nothing
 * renders without choices or a tick.
 */
export function LadderInputs({
  choices,
  lead,
  choice,
  onChoose,
  acknowledge,
  onAcknowledge,
  onRefused,
}: LadderInputsProps): JSX.Element | null {
  const leadId = useId();
  const checked = choices.some((c) => c.id === choice && choiceReason(c) === undefined)
    ? choice
    : undefined;
  const choose = (id: string): void => {
    if (id !== checked) onChoose(id);
  };
  const roving = useRoving({
    items: choices.map((c) => ({ value: c.id, locked: choiceReason(c) !== undefined })),
    checked,
    onSelect: choose,
    onRefused: (id) => {
      const option = choices.find((c) => c.id === id);
      const reason = option === undefined ? undefined : choiceReason(option);
      if (reason !== undefined) onRefused(reason);
    },
  });
  if (choices.length === 0 && acknowledge === undefined) return null;
  return (
    <>
      {choices.length === 0 ? null : (
        <div className="cv-confirm__choices">
          <p id={leadId} className="cv-confirm__lead">
            {lead}
          </p>
          <div
            role="radiogroup"
            aria-labelledby={leadId}
            aria-required="true"
            className="cv-radio-group cv-confirm__group"
          >
            {choices.map((option) => (
              <ChoiceOption
                key={option.id}
                choice={option}
                checked={option.id === checked}
                roving={roving.itemProps(option.id)}
                onChoose={choose}
                onRefused={onRefused}
              />
            ))}
          </div>
        </div>
      )}
      {acknowledge === undefined ? null : (
        <Checkbox
          label={acknowledge.label}
          checked={acknowledge.checked}
          onChange={onAcknowledge}
        />
      )}
    </>
  );
}

export interface ConfirmStepUpLineProps {
  readonly state: ConfirmStepUpState | undefined;
  readonly classLabel: string | undefined;
  /** Epoch ms, the server's: CMP-035 counts it on the wall clock. */
  readonly graceEndsAt: number | undefined;
}

/**
 * The step-up line (E42-D02 §4.1): it says before the press whether a code will be asked. A grace window shows its
 * class and its count (CMP-035, silent); once it has passed, or without its class or its end, the line is the code
 * line: a grace is never claimed that the dialog cannot show.
 */
export function ConfirmStepUpLine({
  state,
  classLabel,
  graceEndsAt,
}: ConfirmStepUpLineProps): JSX.Element | null {
  const [lapsedAt, setLapsedAt] = useState<number | null>(null);
  if (state === undefined || state === "none") return null;
  if (state === "fresh") return <p className="cv-confirm__stepup">{LADDER_COPY.stepUpFresh}</p>;
  const named = classLabel?.trim() ?? "";
  if (
    state === "grace" &&
    named !== "" &&
    graceEndsAt !== undefined &&
    Number.isFinite(graceEndsAt) &&
    lapsedAt !== graceEndsAt
  ) {
    return (
      <p className="cv-confirm__stepup">
        {LADDER_COPY.stepUpGrace(named)}
        <Countdown
          expiresAt={graceEndsAt}
          thresholds={[]}
          onExpire={() => setLapsedAt(graceEndsAt)}
        />
      </p>
    );
  }
  return <p className="cv-confirm__stepup">{LADDER_COPY.stepUpCode}</p>;
}
