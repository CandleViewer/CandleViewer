/**
 * SCR-142's region (h): the bulk archive import (US-REC-007; E16-D04 §2 (h), §8, §10; E16-D06 KB-17, FM-13, SR-24 to
 * SR-26, T2-09, T2-10; BQ-4, BQ-12). The form is the confirm (BQ-12, an additive and resumable action): a known
 * symbol (CMP-009: the recorder's symbols and the instrument index's, never free text or a URL) and an inclusive UTC
 * range of at most 366 days (CMP-047), the consequence line and the archive-derived tag, then Import archives. Its
 * validity look is a seam (the reason under it, a press moving focus there) until #484 PR 3's CMP-001
 * `unavailableReasonId` lands; the view-as leg is T2 and wins. While the job runs the card shows its days; then the
 * finished line with the summary the served `ArchiveImportResult` carries (BQ-4), or a failure as the card's alert.
 */
import { useId, useRef, useState, useSyncExternalStore, type JSX } from "react";
import {
  Callout,
  Card,
  DateRangePicker,
  FormField,
  Icon,
  InlineError,
  KeyValueRow,
  ProgressBar,
  Select,
  Table,
  Tag,
  Text,
  type DateRangeValue,
  type TableColumn,
} from "@candleviewer/ui";
import { formatDate, type RecorderFrame, type RecordingStatus, type StorageUsage } from "../model";
import type { ArchiveImportResult, ImportBody } from "../recorderApi";
import { useRunningIndex } from "../../symbol-search/searchSession";
import { PANEL_TEXT } from "./panelCopy";
import { STORAGE_DECK } from "./storageCopy";
import {
  importProgress,
  importReason,
  importSummary,
  verbOf,
  type SkippedFile,
} from "./storageJobs";
import type { StorageJob } from "./useStorageJob";
import { WriteButton, type WriteGate } from "./WriteButton";

const noSubscription = (): (() => void) => () => undefined;

/**
 * The symbols the import offers: the instruments the shell's index lists once it runs (E08-S09; `given` in tests),
 * with the recorder's own (the report's, the status's and the frame's), deduplicated and sorted.
 */
export function useImportSymbols(
  given: readonly string[] | undefined,
  report: StorageUsage | null,
  status: RecordingStatus | null,
  frame: RecorderFrame | null,
): readonly string[] {
  const index = useRunningIndex();
  const snapshot = useSyncExternalStore(index?.subscribe ?? noSubscription, () =>
    index === null ? null : index.getSnapshot(),
  );
  const listed = given ?? snapshot?.entries.map((entry) => entry.symbol) ?? [];
  const recorded = [
    ...(report?.symbols ?? []).map((s) => s.symbol),
    ...(status?.symbols ?? []).map((s) => s.symbol),
    ...(frame?.symbols ?? []).map((s) => s.symbol),
  ].filter((symbol): symbol is string => symbol !== undefined);
  return [...new Set([...recorded, ...listed])].sort();
}

const isImportResult = (value: unknown): value is ArchiveImportResult =>
  typeof value === "object" &&
  value !== null &&
  "files_total" in value &&
  "files_skipped" in value &&
  Array.isArray(value.files_skipped);

const [IMPORT] = STORAGE_DECK["storage.import.button"];
const [CONSEQUENCE] = STORAGE_DECK["storage.import.consequence"];
const [TAG] = STORAGE_DECK["storage.import.tag"];
const [DAY, STATUS, REASON] = STORAGE_DECK["storage.import.columns"];
const [, SKIPPED] = STORAGE_DECK["storage.import.status"];

/**
 * Day and Status take their words' widths and the reason the rest, at least 32 em: narrower than the three, the table
 * stacks one block per file, so a reason (the sentence and its code token) is never cut (A-486P3-02).
 */
const SKIPPED_COLUMNS: readonly TableColumn<SkippedFile>[] = [
  { id: "day", header: DAY, cell: (row) => row.day, widthEm: 8, minWidthEm: 8 },
  {
    id: "status",
    header: STATUS,
    cell: (row) => (
      <>
        <Icon name={row.status === SKIPPED ? "warning" : "error"} /> {row.status}
      </>
    ),
    widthEm: 9,
    minWidthEm: 9,
  },
  { id: "reason", header: REASON, cell: (row) => row.reason, minWidthEm: 32 },
];

export interface ImportCardProps {
  readonly symbols: readonly string[];
  readonly job: StorageJob<ImportBody>;
  readonly gate: WriteGate | null;
  readonly onStart: (request: ImportBody) => void;
  /** The section's one polite region: the skipped files' table renders none of its own. */
  readonly announce: (text: string) => void;
  /** The clock: the range's last pickable day is today, UTC (an archive exists for past days only). */
  readonly now: () => number;
}

export function ImportCard({
  symbols,
  job,
  gate,
  onStart,
  announce,
  now,
}: ImportCardProps): JSX.Element {
  const id = useId();
  const reasonId = `${id}-reason`;
  const buttonId = `${id}-import`;
  const [symbol, setSymbol] = useState("");
  // The first symbol offered stays the default: a list that grows as the index loads never moves it (C-486P3-11).
  const first = symbols[0];
  if (symbol === "" && first !== undefined) setSymbol(first);
  const [range, setRange] = useState<DateRangeValue>({ start: null, end: null });
  const chosen = symbols.includes(symbol) ? symbol : (symbols[0] ?? "");
  const today = formatDate(now());
  const reason = importReason(chosen, range, today);
  // T2 wins (E09-D09 §9.1): while viewing as, the validity reason is neither shown nor described.
  const unready = gate === null ? reason : undefined;
  const rangeHost = useRef<HTMLDivElement>(null);
  /** The well took an entry during this key press (`onChange` comes before the press reaches its host). */
  const taken = useRef(false);
  const onRange = (next: DateRangeValue): void => {
    taken.current = true;
    setRange(next);
  };

  const press = (): void => {
    // A typed day the well rejected stays in it with its error, and the range keeps its last good day: nothing is
    // sent, and focus goes to the field (C-486P3-03 (b)).
    const rejected = rangeHost.current?.querySelector<HTMLInputElement>(
      "input[aria-invalid='true']",
    );
    if (rejected !== null && rejected !== undefined) {
      rejected.focus();
      return;
    }
    const { start, end } = range;
    if (reason !== undefined || start === null || end === null) {
      document.getElementById(reasonId)?.focus(); // the one rule's reason is this form's error summary (FM-13)
      return;
    }
    onStart({ symbol: chosen, from: start, to: end });
  };

  const view = job.view;
  const request = job.request;
  const progress =
    view !== null && request !== null && view.phase === "running"
      ? importProgress(view, request)
      : null;
  const result = view?.phase === "succeeded" ? view.job?.result : null;
  const summary = isImportResult(result) ? importSummary(result) : null;
  const outcome = job.outcome;

  return (
    <Card title={IMPORT} headingLevel={3}>
      <div style={{ display: "grid", gap: "var(--space-stack-sm)" }}>
        <Text as="p" tone="secondary">
          {CONSEQUENCE}
        </Text>
        <span>
          <Tag label={TAG} />
        </span>
        <FormField label={PANEL_TEXT.importSymbol}>
          <Select
            options={symbols.map((name) => ({ value: name, label: name }))}
            value={chosen === "" ? undefined : chosen}
            onChange={setSymbol}
          />
        </FormField>
        {/*
         * KB-17: Enter in From moves to To, and in To to Import archives, once the well has taken the entry (it
         * commits first); an entry it rejected keeps its error and focus (C-486P3-03 (c)).
         */}
        <div
          ref={rangeHost}
          role="presentation"
          onKeyDownCapture={() => {
            taken.current = false;
          }}
          onKeyDown={(event) => {
            if (event.key !== "Enter" || !(event.target instanceof HTMLInputElement)) return;
            const inputs = [...event.currentTarget.querySelectorAll("input")];
            const at = inputs.indexOf(event.target);
            const committed = (at === 0 ? range.start : range.end) ?? "";
            const text = event.target.value.trim();
            if (!taken.current && text !== "" && text !== committed) return;
            const next = inputs[at + 1] ?? document.getElementById(buttonId);
            next?.focus();
          }}
        >
          <FormField label={PANEL_TEXT.importRange}>
            <DateRangePicker
              value={range}
              onChange={onRange}
              startLabel={PANEL_TEXT.importFrom}
              endLabel={PANEL_TEXT.importTo}
              max={today}
              now={now}
            />
          </FormField>
        </div>
        <span
          style={{ display: "inline-grid", justifyItems: "start", gap: "var(--space-stack-xs)" }}
        >
          <WriteButton
            id={buttonId}
            gate={gate}
            at="import"
            refusal={job.refusal}
            variant="primary"
            loading={job.busy}
            {...(unready === undefined ? {} : { "aria-describedby": reasonId })}
            onClick={press}
          >
            {IMPORT}
          </WriteButton>
          <Text id={reasonId} tabIndex={-1} variant="caption" tone="secondary">
            {unready}
          </Text>
        </span>
        {progress === null ? null : <ImportBar text={progress.text} value={progress.value} />}
        {/* §16.4 row 10: a refused poll's T4 under the bar, the bar kept (C-486P3-01). */}
        {progress === null || job.pollRefused === null ? null : (
          <InlineError message={job.pollRefused} live="off" />
        )}
        {outcome === null ? null : outcome.assertive ? (
          <Callout tone={outcome.tone} title={outcome.text} />
        ) : (
          <Callout tone={outcome.tone} live="off" title={outcome.text} />
        )}
        {summary === null ? null : (
          <div style={{ display: "grid", gap: "var(--space-stack-sm)" }}>
            <span>
              <Tag label={TAG} />
            </span>
            <dl style={{ margin: 0, display: "grid", gap: "var(--space-stack-xs)" }}>
              {summary.rows.map((row) => (
                <KeyValueRow
                  key={row.label}
                  label={row.label}
                  value={
                    <span className="cv-num" data-size="sm">
                      {row.value}
                    </span>
                  }
                />
              ))}
            </dl>
            {summary.overlap === null ? null : (
              <Callout tone="info" live="off" title={summary.overlap} />
            )}
            {summary.skipped.length === 0 ? null : (
              <Table
                columns={SKIPPED_COLUMNS}
                rows={summary.skipped}
                rowKey={(row) => row.file}
                caption={PANEL_TEXT.summary.skipped}
                announce={announce}
              />
            )}
            {summary.resume === null ? null : <Text as="p">{summary.resume}</Text>}
          </div>
        )}
      </div>
    </Card>
  );
}

/** The import's bar: CMP-023 `progress` named by the job's verb, "{done} of {n} days · {pct} %" its value text. */
function ImportBar({
  text,
  value,
}: {
  readonly text: string;
  readonly value: number;
}): JSX.Element {
  const labelId = useId();
  return (
    <div className="cv-num" data-size="sm">
      <span id={labelId} className="cv-visually-hidden">
        {verbOf("import")}
      </span>
      <ProgressBar aria-labelledby={labelId} value={value} valueText={text} />
    </div>
  );
}
