/**
 * Region (b) of SCR-141, the global defaults (E16-D03 §2 (b), §3, §7; E16-D06 KB-09, KB-10): CMP-065 with one row per
 * `22` `StreamKind` in the contract's order. A row holds the stream, the CMP-008 field "Retention (days)" (the unit in
 * its name, through the column's label, and in `aria-valuetext`), the Action CMP-009 (two of the contract's four
 * actions: `downsample` and `pin` are absences), the read-only "Kept in Parquet until {total}", and the baseline chip
 * "Default {n} d" or "Reset to default". The help switches on the action (D03-D3); the trades row states the
 * derived-stream rule in advance; a Delete-after row on a stream kept with no end date warns. The field checks its
 * value on blur (CMP-008 commits only then), in product words; every write is T2 while viewing as (the one notice).
 */
import { useId, type CSSProperties, type JSX } from "react";
import {
  Button,
  Callout,
  FormSection,
  NumericStepperInput,
  Select,
  Tag,
  Text,
} from "@candleviewer/ui";
import { RETENTION_DECK, STREAM_WORDS } from "./retentionCopy";
import {
  OFFERED_ACTIONS,
  isAtSeed,
  validateDays,
  type DraftRow,
  type OfferedAction,
  type StreamKind,
} from "./retentionModel";
import {
  DERIVED_HELP,
  RETENTION_TEXT,
  baselineText,
  fieldErrorText,
  helpText,
  keptUntilText,
  noSourceText,
} from "./retentionText";

/** The view-as leg (E16-D03 §1.3): its reason on every write control, which points at the one notice. */
export interface WriteGate {
  readonly reason: string;
  readonly noticeId: string;
}

/** The Action select's two options, in the deck's words. */
export const ACTION_OPTIONS = OFFERED_ACTIONS.map((action) => ({
  value: action,
  label: RETENTION_DECK[`retention.action.${action}`][0],
}));

const isOffered = (value: string): value is OfferedAction =>
  (OFFERED_ACTIONS as readonly string[]).includes(value);

const DAYS_UNIT = RETENTION_DECK["retention.field.days"][1];

export interface GlobalDefaultsProps {
  /** The eight global rows, in the contract's order. */
  readonly rows: readonly DraftRow[];
  readonly onDays: (stream: StreamKind, days: number) => void;
  readonly onAction: (stream: StreamKind, action: OfferedAction) => void;
  readonly onReset: (stream: StreamKind) => void;
  /** The id each row's field takes (the summary's links and the dialog's first focus reach it by id). */
  readonly fieldId: (stream: StreamKind) => string;
  readonly gate: WriteGate | null;
}

/**
 * Five tracks that wrap together at 200 % (D03 §9 reflow): every row keeps the header's columns. Each is wide enough
 * for the stepper with four digits and for "Move to Parquet after" whole (A-5353-04), five to the 960 px dialog; none
 * is wider than the section, so a 320 px viewport stacks them in one (A-5353-09).
 */
const ROW: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fill, minmax(min(10.75rem, 100%), 1fr))",
  alignItems: "start",
  columnGap: "var(--space-inset-sm)",
  rowGap: "var(--space-stack-xs)",
};

export function GlobalDefaults({
  rows,
  onDays,
  onAction,
  onReset,
  fieldId,
  gate,
}: GlobalDefaultsProps): JSX.Element {
  return (
    <FormSection title={RETENTION_DECK["retention.section.global"][0]} headingLevel={3}>
      {/* The columns' words (D03 §2): each row's controls carry them in their own names. */}
      <div style={ROW}>
        {RETENTION_TEXT.global.map((words) => (
          <Text key={words} variant="label" tone="secondary">
            {words}
          </Text>
        ))}
      </div>
      {rows.map((row) => (
        <GlobalRow
          key={row.stream}
          row={row}
          fieldId={fieldId(row.stream)}
          onDays={onDays}
          onAction={onAction}
          onReset={onReset}
          gate={gate}
        />
      ))}
    </FormSection>
  );
}

interface GlobalRowProps {
  readonly row: DraftRow;
  readonly fieldId: string;
  readonly onDays: (stream: StreamKind, days: number) => void;
  readonly onAction: (stream: StreamKind, action: OfferedAction) => void;
  readonly onReset: (stream: StreamKind) => void;
  readonly gate: WriteGate | null;
}

function GlobalRow({ row, fieldId, onDays, onAction, onReset, gate }: GlobalRowProps): JSX.Element {
  const id = useId();
  const nameId = `${id}-name`;
  const helpId = `${id}-help`;
  const derivedId = `${id}-derived`;
  const name = STREAM_WORDS[row.stream];
  const error = validateDays(row.days);
  // A field in error keeps the help of the action it has; the help reads the days only once they are valid.
  const help = helpText(row.stream, error === null ? row.days : 1, row.action);
  const warning = noSourceText(row.stream, row.action);
  const t2 = gate === null ? {} : { disabledReason: gate.reason, disabledReasonId: gate.noticeId };
  return (
    <div
      role="group"
      aria-labelledby={nameId}
      style={{ display: "grid", gap: "var(--space-stack-xs)" }}
    >
      <div style={ROW}>
        <Text id={nameId} variant="body-strong">
          {name}
        </Text>
        <NumericStepperInput
          id={fieldId}
          // Named "Trades Retention (days)": the row's stream and the column's words, unit included.
          label={`${name} ${RETENTION_TEXT.global[1]}`}
          aria-describedby={row.stream === "trades" ? `${helpId} ${derivedId}` : helpId}
          value={row.days}
          step={1}
          largeStep={10}
          precision={0}
          suffix={DAYS_UNIT}
          invalid={error !== null}
          {...(error === null ? {} : { errorMessage: fieldErrorText(error) })}
          {...(gate === null ? {} : { disabledReason: gate.reason })}
          onChange={(next) => onDays(row.stream, next)}
        />
        <Select
          aria-label={`${name} ${RETENTION_TEXT.global[2]}`}
          options={ACTION_OPTIONS}
          value={row.action}
          {...(gate === null ? {} : { disabledReason: gate.reason })}
          onChange={(value) => {
            if (isOffered(value)) onAction(row.stream, value);
          }}
        />
        {/* A field in error has no horizon to state until it is valid (it keeps its column). */}
        <Text variant="caption" tone="secondary">
          {error === null ? keptUntilText(row.stream, row.days, row.action) : null}
        </Text>
        {isAtSeed(row) ? (
          <Tag label={baselineText(row.stream)} />
        ) : (
          <Button variant="ghost" size="sm" {...t2} onClick={() => onReset(row.stream)}>
            {RETENTION_DECK["retention.reset"][0]}
          </Button>
        )}
      </div>
      <Text id={helpId} variant="caption" tone="secondary" as="p">
        {help}
      </Text>
      {row.stream === "trades" ? (
        <Text id={derivedId} variant="caption" tone="secondary" as="p">
          {DERIVED_HELP}
        </Text>
      ) : null}
      {warning === null ? null : <Callout tone="warning" live="off" title={warning} />}
    </div>
  );
}
