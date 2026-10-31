/**
 * Bulk-action aggregator (E40-S01): runs one action per selected id and reports every outcome plus
 * a summary. One failure never stops the others, a rejected or thrown call is a per-id failure,
 * and duplicate ids run once. Calls run with bounded concurrency so a large selection cannot
 * flood the API.
 */
export type BulkAction = "enable" | "disable" | "delete" | "snooze" | "unsnooze";

export type BulkOutcome =
  | { readonly id: string; readonly ok: true }
  | { readonly id: string; readonly ok: false; readonly error: string };

export interface BulkSummary {
  readonly total: number;
  readonly ok: number;
  readonly failed: number;
}

export interface BulkResult {
  readonly action: BulkAction;
  readonly outcomes: readonly BulkOutcome[];
  readonly summary: BulkSummary;
  readonly failedIds: readonly string[];
}

/** Resolves on success; rejects (or throws) with an Error to mark that id failed. */
export type BulkRunner = (action: BulkAction, id: string) => Promise<void>;

export const BULK_CONCURRENCY = 4;

function messageOf(error: unknown): string {
  return error instanceof Error && error.message !== "" ? error.message : "request failed";
}

export function summarise(outcomes: readonly BulkOutcome[]): BulkSummary {
  const ok = outcomes.filter((outcome) => outcome.ok).length;
  return { total: outcomes.length, ok, failed: outcomes.length - ok };
}

export async function runBulkAction(
  action: BulkAction,
  ids: readonly string[],
  runner: BulkRunner,
  concurrency: number = BULK_CONCURRENCY,
): Promise<BulkResult> {
  const unique = [...new Set(ids)];
  const outcomes: BulkOutcome[] = new Array<BulkOutcome>(unique.length);
  let next = 0;
  const worker = async (): Promise<void> => {
    while (next < unique.length) {
      const index = next;
      next += 1;
      const id = unique[index] as string;
      try {
        await runner(action, id);
        outcomes[index] = { id, ok: true };
      } catch (error: unknown) {
        outcomes[index] = { id, ok: false, error: messageOf(error) };
      }
    }
  };
  const lanes = Math.max(1, Math.min(Math.floor(concurrency), unique.length));
  await Promise.all(Array.from({ length: lanes }, worker));
  const failedIds = outcomes.flatMap((outcome) => (outcome.ok ? [] : [outcome.id]));
  return { action, outcomes, summary: summarise(outcomes), failedIds };
}
