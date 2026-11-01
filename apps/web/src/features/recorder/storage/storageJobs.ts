/**
 * SCR-142's job words (E16-S04; E16-D04 §6, §8, §14; E16-D06 SR-13, SR-24 to SR-28, §16.4; G-08; BQ-4, BQ-11): the
 * jobs strip's lines, a compaction's and an import's terminal lines, the import form's range rule and progress, and
 * the import summary from the served `ArchiveImportResult` (BQ-4: the served names; a skip code is routed to E16-D04's
 * sentence, else shown as its token). A compaction reports `kind: retention_sweep` and shares that slot (BQ-11): the
 * action that issued the id names the job here, never `kind`. Nothing here reads a problem's `message` or `detail`.
 */
import { DECK, fill } from "../copy";
import { formatHourMinute, parseMs } from "../model";
import type {
  ArchiveImportResult,
  CompactionRunResult,
  ImportBody,
  RefusalRoute,
} from "../recorderApi";
import { refusalText } from "../refusal";
import type { JobView } from "../useJobPoll";
import { PANEL_TEXT } from "./panelCopy";
import { IMPORT_SKIP_REASONS, STORAGE_DECK } from "./storageCopy";
import { formatCount } from "./storageModel";

/** The two jobs SCR-142 starts; the purge is SCR-140's dialog (E16-D04 §7). */
export type StorageJobKind = "compact" | "import";

/** The deck's `{verb}` (D04 §14's variables: Compaction · Import). */
const VERB: Readonly<Record<StorageJobKind, string>> = { compact: "Compaction", import: "Import" };

/** "Compaction started", said once as the job is accepted (SR-24). */
export const startedLine = (kind: StorageJobKind): string =>
  fill(STORAGE_DECK["storage.job.started"][0], { "{verb}": VERB[kind] });

/**
 * A running job's strip line: "Compaction running · 42 %", the whole percentage, never rounded up to a finish it
 * has not reached; "Compaction queued" until the job reports running (G-08: the served status word).
 */
export function progressLine(kind: StorageJobKind, view: JobView): string {
  if (view.job?.status !== "running") return fill(PANEL_TEXT.queued, { "{verb}": VERB[kind] });
  return fill(STORAGE_DECK["storage.job.running"][0], {
    "{verb}": VERB[kind],
    "{pct}": Math.floor(view.pct),
  });
}

/** A terminal line: its words, its tone inside the card, and whether it is the assertive one (SR-26). */
export interface OutcomeView {
  readonly text: string;
  readonly tone: "success" | "danger" | "warning";
  readonly assertive: boolean;
  /** A second line under it, said with it: a succeeded compaction's partitions left as they were, as counts. */
  readonly detail?: string;
}

const polite = (text: string, tone: OutcomeView["tone"]): OutcomeView => ({
  text,
  tone,
  assertive: false,
});

const isCompactionResult = (value: unknown): value is CompactionRunResult =>
  typeof value === "object" &&
  value !== null &&
  "failed" in value &&
  "deferred" in value &&
  Array.isArray(value.failed) &&
  Array.isArray(value.deferred);

/**
 * The served `CompactionRunResult`'s partitions left as they were (C-486P3-05, PROPOSED for E16-D04): those whose
 * merge failed its row-count check and those a replay was reading, as counts only, never their keys; null when the
 * run left none, or the result is not a compaction's.
 */
function leftAsTheyWere(result: unknown): string | null {
  if (!isCompactionResult(result)) return null;
  const parts = [
    ...(result.failed.length === 0
      ? []
      : [fill(PANEL_TEXT.compactFailed, { "{n}": formatCount(result.failed.length) })]),
    ...(result.deferred.length === 0
      ? []
      : [fill(PANEL_TEXT.compactDeferred, { "{n}": formatCount(result.deferred.length) })]),
  ];
  return parts.length === 0 ? null : fill(PANEL_TEXT.compactLeft, { "{parts}": parts.join(", ") });
}

/**
 * A compaction's line (E16-D02 §3.2 reused, D04 `JOB/outcomes`): each polite, once (SR-13); a success that left
 * partitions as they were says how many under it (C-486P3-05).
 */
export function compactOutcome(view: JobView, nowMs: number): OutcomeView | null {
  switch (view.phase) {
    case "succeeded": {
      const at = parseMs(view.job?.finished_at) ?? nowMs;
      const text = fill(DECK["storage.compact.succeeded"][0], { "{HH:MM}": formatHourMinute(at) });
      const detail = leftAsTheyWere(view.job?.result);
      return detail === null ? polite(text, "success") : { ...polite(text, "success"), detail };
    }
    case "failed": {
      const code = view.job?.error ?? "failed";
      return polite(fill(DECK["storage.compact.failed"][0], { "`<code>`": code }), "danger");
    }
    case "cancelled":
      return polite(DECK["storage.compact.cancelled"][0], "warning");
    case "unknown":
      return polite(DECK["storage.compact.unknown"][0], "warning");
    default:
      return null;
  }
}

/** The import's at most (`22` `importTradeArchive`: an inclusive UTC range of at most 366 days). */
export const IMPORT_MAX_DAYS = 366;
const DAY_MS = 86_400_000;

/** The inclusive days from `from` to `to` (ISO dates, UTC); not positive when inverted. */
export const rangeDays = (from: string, to: string): number =>
  Math.round((Date.parse(`${to}T00:00:00Z`) - Date.parse(`${from}T00:00:00Z`)) / DAY_MS) + 1;

/** The import form's range: CMP-047's two ISO days, either still empty. */
export interface ImportRange {
  readonly start: string | null;
  readonly end: string | null;
}

/**
 * Import archives' validity reason (D04 §1.3 the validity look, `IMPORT/form-validity`): "Choose a range of at most
 * 366 days." while the range is empty, inverted or longer; then, as an archive exists for past days only (D04 §8),
 * a range ending after `todayIso` (UTC) has its own, PROPOSED (C-486P3-03 (a)); undefined once the form can be sent.
 */
export function importReason(
  symbol: string,
  range: ImportRange,
  todayIso: string,
): string | undefined {
  if (symbol === "") return PANEL_TEXT.chooseSymbol;
  const { start, end } = range;
  const days = start === null || end === null ? 0 : rangeDays(start, end);
  if (days < 1 || days > IMPORT_MAX_DAYS) return STORAGE_DECK["storage.import.range.reason"][0];
  return end !== null && end > todayIso
    ? fill(PANEL_TEXT.endAfterToday, { "{date}": todayIso })
    : undefined;
}

/** The import card's bar: "{done} of {n} days · {pct} %" from `progress_pct` over the requested range. */
export function importProgress(
  view: JobView,
  request: ImportBody,
): { readonly text: string; readonly value: number } {
  const days = Math.max(0, rangeDays(request.from, request.to));
  const text = fill(STORAGE_DECK["storage.import.progress"][0], {
    "{done}": Math.round((view.pct * days) / 100),
    "{n}": days,
    "{pct}": Math.floor(view.pct),
  });
  return { text, value: view.pct };
}

/**
 * An import's terminal line (D04 §8): finished, polite once; failed, inside its card, `role="alert"` once (SR-26,
 * the closed assertive set); cancelled and lost, polite once.
 */
export function importOutcome(view: JobView, request: ImportBody): OutcomeView | null {
  switch (view.phase) {
    case "succeeded": {
      const text = fill(STORAGE_DECK["storage.import.finished"][0], {
        "{symbol}": request.symbol,
        "{from}": request.from,
        "{to}": request.to,
      });
      return polite(text, "success");
    }
    case "failed": {
      const code = view.job?.error ?? "failed";
      const text = fill(STORAGE_DECK["storage.import.failed"][0], { "{code}": code });
      return { text, tone: "danger", assertive: true };
    }
    case "cancelled":
      return polite(STORAGE_DECK["storage.import.cancelled"][0], "warning");
    case "unknown":
      return polite(STORAGE_DECK["storage.import.unknown"][0], "warning");
    default:
      return null;
  }
}

/** A skip code's E16-D04 sentence with the code token after it; a code with no sentence is its token alone. */
export function skipReasonText(code: string): string {
  const key = Object.hasOwn(IMPORT_SKIP_REASONS, code)
    ? IMPORT_SKIP_REASONS[code as keyof typeof IMPORT_SKIP_REASONS]
    : null;
  return key === null ? code : `${STORAGE_DECK[key][0]} (${code})`;
}

export interface SummaryRow {
  readonly label: string;
  readonly value: string;
}

/** One skipped file: its day (from the archive's name, else the name), its status word and its reason. */
export interface SkippedFile {
  readonly file: string;
  readonly day: string;
  readonly status: string;
  readonly reason: string;
}

export interface ImportSummaryView {
  readonly rows: readonly SummaryRow[];
  readonly overlap: string | null;
  readonly skipped: readonly SkippedFile[];
  readonly resume: string | null;
}

const [, SKIPPED, ERROR] = STORAGE_DECK["storage.import.status"];
const ISO_DAY = /\d{4}-\d\d-\d\d/;

/**
 * The summary (AC 6; BQ-4): files processed of the range's files, those an earlier run finished, rows written, rows
 * discarded as overlap with the overlap report ("recorded data wins"), and every skipped file with its reason; a
 * download failure is an error row (D04 §8's statuses), any other skip a skipped one.
 */
export function importSummary(result: ArchiveImportResult): ImportSummaryView {
  const words = PANEL_TEXT.summary;
  const rows: SummaryRow[] = [
    {
      label: words.processed,
      value: fill(words.ofTotal, {
        "{n}": formatCount(result.files_processed),
        "{total}": formatCount(result.files_total),
      }),
    },
    ...(result.files_already_imported > 0
      ? [{ label: words.alreadyImported, value: formatCount(result.files_already_imported) }]
      : []),
    { label: words.written, value: formatCount(result.rows_written) },
    { label: words.overlap, value: formatCount(result.rows_discarded_overlap) },
    { label: words.skipped, value: formatCount(result.files_skipped.length) },
  ];
  const overlap =
    result.rows_discarded_overlap > 0
      ? fill(STORAGE_DECK["storage.import.overlap"][0], {
          "{rows}": formatCount(result.rows_discarded_overlap),
        })
      : null;
  const skipped = result.files_skipped.map(({ file, reason }) => ({
    file,
    day: ISO_DAY.exec(file)?.[0] ?? file,
    status: reason === "import_download_failed" ? ERROR : SKIPPED,
    reason: skipReasonText(reason),
  }));
  const resume = skipped.length > 0 ? STORAGE_DECK["storage.import.resume"][0] : null;
  return { rows, overlap, skipped, resume };
}

/**
 * A refusal at the point of action (E16-D06 §16.4; T4): the deck's "A compaction is already running." (the import's
 * with its article, PROPOSED), else the generic T4 with the code token; no answer is the app's own words.
 */
export function refusalFor(kind: StorageJobKind, route: RefusalRoute): string {
  if (kind === "import" && route.kind === "deck" && route.key === "storage.job.refused.running") {
    return `${PANEL_TEXT.importRunning} (${route.code})`;
  }
  return refusalText(route, "compact");
}
