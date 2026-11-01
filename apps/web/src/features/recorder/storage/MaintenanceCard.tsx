/**
 * SCR-142's region (g) (E16-D04 §2 (g), §6; E16-D06 KB-15, FM-13, RG-13, SR-13, SR-24, T2-08; F-13, F-14; BQ-10,
 * BQ-13): the maintenance card, Compact Parquet… (also on the Parquet card) and the jobs strip, one line per job
 * this client started, "Compaction running · 42 %" as its CMP-023's value text (the words are seen, never spoken
 * per poll: the section's region says the start and the end), then a finished compaction's line inside the card,
 * no banner. No Stop control: `22` has no cancel route, so a started job runs to its end (D04-G10). The vacuum is
 * D04-G8's, not built. Compact Parquet… opens CMP-044 standard: compaction deletes nothing (BQ-10), Cancel first.
 */
import { useId, type JSX, type ReactNode } from "react";
import { Callout, Card, ConfirmDialog, InlineError, ProgressBar, Text } from "@candleviewer/ui";
import { DECK } from "../copy";
import { PANEL_TEXT } from "./panelCopy";
import { STORAGE_DECK } from "./storageCopy";
import type { OutcomeView } from "./storageJobs";

/** One strip line: the job's verb names its bar; the line is the bar's value text. */
export interface StripLine {
  readonly key: string;
  readonly verb: string;
  readonly text: string;
  readonly value: number;
  /**
   * §16.4 row 10: a refused poll's T4 under the line, the line kept (CMP-027 inline, no live role: the shell
   * announcer says it once); null otherwise (C-486P3-01).
   */
  readonly refused: string | null;
}

export interface MaintenanceCardProps {
  /** Compact Parquet…, the panel's (it shares its state with the Parquet card's). */
  readonly compact: ReactNode;
  readonly lines: readonly StripLine[];
  /** A finished compaction's line. */
  readonly outcome: OutcomeView | null;
}

export function MaintenanceCard({ compact, lines, outcome }: MaintenanceCardProps): JSX.Element {
  return (
    <Card title={PANEL_TEXT.maintenance} headingLevel={3}>
      <div style={{ display: "grid", gap: "var(--space-stack-sm)" }}>
        <div>{compact}</div>
        {lines.map((line) => (
          <JobLine key={line.key} line={line} />
        ))}
        {outcome === null ? null : (
          <Callout tone={outcome.tone} live="off" title={outcome.text}>
            {outcome.detail}
          </Callout>
        )}
      </div>
    </Card>
  );
}

/**
 * A strip line: CMP-023 `progress`, named by the job's verb, its visible and read value the line (D04 §6); a refused
 * poll's T4 under it (E16-D06 §16.4 row 10).
 */
function JobLine({ line }: { readonly line: StripLine }): JSX.Element {
  const labelId = useId();
  return (
    <div style={{ display: "grid", gap: "var(--space-stack-xs)" }}>
      <div className="cv-num" data-size="sm">
        <span id={labelId} className="cv-visually-hidden">
          {line.verb}
        </span>
        <ProgressBar aria-labelledby={labelId} value={line.value} valueText={line.text} />
      </div>
      {line.refused === null ? null : <InlineError message={line.refused} live="off" />}
    </div>
  );
}

export interface CompactConfirmProps {
  readonly open: boolean;
  readonly onConfirm: () => void;
  readonly onCancel: () => void;
  /** CMP-044's clock (its activation guard), injectable for tests. */
  readonly now?: (() => number) | undefined;
}

/** `JOB/confirm-compact`: CMP-044 standard, "This action is audited.", Cancel / Compact / ✕ (KB-15). */
export function CompactConfirm({
  open,
  onConfirm,
  onCancel,
  now,
}: CompactConfirmProps): JSX.Element {
  return (
    <ConfirmDialog
      open={open}
      role="dialog"
      title={DECK["storage.compact.title"][0]}
      message={DECK["storage.compact.body"][0]}
      confirmLabel={PANEL_TEXT.compact}
      confirmVariant="primary"
      cancelLabel={STORAGE_DECK["storage.confirm.cancel"][0]}
      onConfirm={onConfirm}
      onCancel={onCancel}
      {...(now === undefined ? {} : { now })}
    >
      <Text as="p" tone="secondary">
        {STORAGE_DECK["storage.audited"][0]}
      </Text>
    </ConfirmDialog>
  );
}
