/**
 * SCR-142's region (b) (E16-D04 §2 (b), §1.4, §5; E16-D06 RG-13, SD-06; D04-D1, D04-D7): what stops first on every
 * level ≥ 1, a status beside the figures and never an alert (SCR-140's level banner and its summary announce a
 * crossing, E16-D06 F-07); the recording budget's meter with E16-D02's headline keyed on `level`; the disk volume's
 * meter; the projection, the formula and the scale; and the suggested actions, handed to the page (SCR-141 opens
 * from Shorten retention, the grid's filters from the others). Every figure is text; the meters are no Tab stops.
 */
import type { JSX } from "react";
import { Button, Callout, ProgressBar, Tag, Text } from "@candleviewer/ui";
import { DECK, TEXT } from "../copy";
import type { DiskFacts, RecorderPolicy, StorageUsage } from "../model";
import {
  accelerationWord,
  budgetMeter,
  causeLine,
  degradationOf,
  formulaLine,
  headlineOf,
  projectionLine,
  scaleLine,
  volumeMeter,
} from "./storageModel";

const [, SHORTEN, REDUCE, UNPIN] = DECK["d02.8.r19"];

export interface BudgetMetersProps {
  readonly facts: DiskFacts;
  readonly report: StorageUsage | null;
  readonly policy: RecorderPolicy | null;
  readonly nothingRecorded: boolean;
  readonly nowMs: number;
  /** The page's history (its rows' oldest start): growth 0 reads "Steady" past an hour of it (C-486P3-02). */
  readonly historySinceMs: number | null;
  /** The sample is stale: the figures keep their text, tagged "stale" (D04 `SCR-142/stale-sample`). */
  readonly stale: boolean;
  readonly openRetention?: (() => void) | undefined;
  readonly onSuggested?: ((action: string) => void) | undefined;
}

interface Suggestion {
  readonly label: string;
  readonly run: () => void;
}

/** D02 §8.3's three, as links (T1): Shorten retention opens SCR-141 when it is registered, else the page's own. */
function suggestions(
  openRetention: (() => void) | undefined,
  onSuggested: ((action: string) => void) | undefined,
): Suggestion[] {
  const shorten =
    openRetention ?? (onSuggested === undefined ? undefined : () => onSuggested(SHORTEN));
  return [
    ...(shorten === undefined ? [] : [{ label: SHORTEN, run: shorten }]),
    ...(onSuggested === undefined
      ? []
      : [REDUCE, UNPIN].map((label) => ({ label, run: () => onSuggested(label) }))),
  ];
}

export function BudgetMeters({
  facts,
  report,
  policy,
  nothingRecorded,
  nowMs,
  historySinceMs,
  stale,
  openRetention,
  onSuggested,
}: BudgetMetersProps): JSX.Element {
  const budget = budgetMeter(facts);
  const volume = volumeMeter(report);
  const degraded = degradationOf(facts, policy);
  const accelerated = accelerationWord(facts);
  const cause = causeLine(facts);
  const lines = [projectionLine(facts, nowMs), formulaLine(facts, policy), scaleLine(policy)];
  // A refused volume is not freed by shortening or unpinning (E16-D02 C-8): no suggestion there.
  const offered =
    facts.level >= 1 && !facts.volumeRefused ? suggestions(openRetention, onSuggested) : [];
  return (
    <div style={{ display: "grid", gap: "var(--space-stack-sm)" }}>
      {degraded === null ? null : (
        <Callout tone={facts.level === 3 ? "danger" : "warning"} live="off" title={degraded.title}>
          {degraded.lines.map((line) => (
            <span key={line} style={{ display: "block" }}>
              {line}
            </span>
          ))}
        </Callout>
      )}
      {stale ? (
        <span>
          <Tag label={TEXT.staleTag} />
        </span>
      ) : null}
      {budget === null ? null : (
        <ProgressBar
          kind="meter"
          label={budget.label}
          value={budget.value}
          valueText={budget.text}
          tone={budget.tone}
        />
      )}
      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          alignItems: "center",
          gap: "var(--space-inset-xs)",
        }}
      >
        <Text variant="body-strong">
          {headlineOf(facts, policy, nothingRecorded, nowMs, historySinceMs)}
        </Text>
        {accelerated === null ? null : <Tag label={accelerated} />}
      </div>
      {cause === null ? null : <Text as="p">{cause}</Text>}
      {volume === null ? null : (
        <ProgressBar
          kind="meter"
          label={volume.label}
          value={volume.value}
          valueText={volume.text}
          tone={volume.tone}
        />
      )}
      {lines.map((line) =>
        line === null ? null : (
          <Text key={line} as="p" tone="secondary">
            {line}
          </Text>
        ),
      )}
      {offered.length === 0 ? null : (
        <div style={{ display: "flex", flexWrap: "wrap", gap: "var(--space-inset-xs)" }}>
          {offered.map(({ label, run }) => (
            <Button key={label} variant="ghost" size="sm" onClick={run}>
              {label}
            </Button>
          ))}
        </div>
      )}
    </div>
  );
}
