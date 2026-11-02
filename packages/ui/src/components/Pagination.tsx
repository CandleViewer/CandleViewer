import { useId, type JSX, type KeyboardEvent } from "react";
import { Button } from "./Button.js";

/** E42-D04 §14 `labels.page.*` and CMP-053's name (`15` CMP-053 A11y). */
export const PAGINATION_COPY = {
  nav: "Pagination",
  newest: "Newest",
  newer: "Newer",
  older: "Older",
} as const;

export type PaginationLabels = { readonly [K in keyof typeof PAGINATION_COPY]: string };

export interface PaginationProps {
  /**
   * Cursor mode (keyset paging, E42-D04 D4): Newest, Newer and Older, no page number, no total and no current
   * page. The only mode built: page mode ships with its first consumer.
   */
  readonly mode?: "cursor";
  /** Back to the newest page (the first cursor). */
  readonly onNewest: () => void;
  /** The newer page: a cursor the host kept. */
  readonly onNewer: () => void;
  /** The older page: the page's `next_cursor`. */
  readonly onOlder: () => void;
  /** T2 (E09-D09 §2.2) on Newest and Newer: nothing is newer, as on page 1 (`admin.newest`). */
  readonly newerReason?: string;
  /** The host's node that already shows `newerReason`; without it the pager shows the reason itself. */
  readonly newerReasonId?: string;
  /** T2 on Older: nothing is older (`admin.oldest`, whose node is the host's `audit.end` line). */
  readonly olderReason?: string;
  /** The host's node that already shows `olderReason`, such as the `audit.end` line under the last row. */
  readonly olderReasonId?: string;
  /** T2 on every button, in place of the direction reasons (a `429`: `admin.rate_limited`, AL-16). */
  readonly blockedReason?: string;
  /** The host's one notice that shows `blockedReason` (one notice, many pointers). */
  readonly blockedReasonId?: string;
  /** The words, default `PAGINATION_COPY`. */
  readonly labels?: Partial<PaginationLabels>;
  /** Emits `data-density` on the buttons; absent = inherit. */
  readonly density?: "comfortable" | "compact";
}

const trimmed = (text: string | undefined): string | undefined => text?.trim() || undefined;

/** Every key that acts acts once per press (E42-D04 §12): a held key's repeats are dropped, never a page each. */
const dropRepeats = (event: KeyboardEvent<HTMLButtonElement>): void => {
  if (event.repeat && (event.key === "Enter" || event.key === " ")) event.preventDefault();
};

interface Direction {
  readonly label: string;
  readonly onPress: () => void;
  readonly reason: string | undefined;
  readonly reasonId: string | undefined;
}

/**
 * CMP-053 Pagination in cursor mode (E42-D04 D4, §4 Keys; `15` CMP-053): a `nav` named "Pagination" holding three
 * CMP-001 buttons, Newest, Newer and Older, with no `aria-current`, page number or total. A button with nothing in
 * its direction, or every button given `blockedReason`, is T2 (E09-D09 §2.2): it keeps its label and its Tab stop,
 * takes `aria-disabled` and the `lock` leading the label, and is described by its reason alone, shown under the
 * buttons (2a) or by the host's node. One reason per control: `blockedReason` replaces the direction reasons. A press
 * on a T2 button asks for nothing and says the reason once; a held key asks for one page. Focus after a page loads is
 * the host's (the new page's first row).
 */
export function Pagination({
  onNewest,
  onNewer,
  onOlder,
  newerReason,
  newerReasonId,
  olderReason,
  olderReasonId,
  blockedReason,
  blockedReasonId,
  labels,
  density,
}: PaginationProps): JSX.Element {
  const words = { ...PAGINATION_COPY, ...labels };
  const newerLine = useId();
  const olderLine = useId();
  const blockedLine = useId();
  const blocked = trimmed(blockedReason);
  const newer = trimmed(newerReason);
  const older = trimmed(olderReason);
  const blockedHost = trimmed(blockedReasonId);
  const newerHost = trimmed(newerReasonId);
  const olderHost = trimmed(olderReasonId);
  // The lines this pager shows itself: each reason no host node already carries, once.
  const lines: { readonly id: string; readonly text: string }[] =
    blocked !== undefined
      ? blockedHost === undefined
        ? [{ id: blockedLine, text: blocked }]
        : []
      : [
          ...(newer !== undefined && newerHost === undefined
            ? [{ id: newerLine, text: newer }]
            : []),
          ...(older !== undefined && olderHost === undefined
            ? [{ id: olderLine, text: older }]
            : []),
        ];
  const gate = (own: string | undefined, host: string | undefined, line: string) =>
    blocked !== undefined
      ? { reason: blocked, reasonId: blockedHost ?? blockedLine }
      : own !== undefined
        ? { reason: own, reasonId: host ?? line }
        : { reason: undefined, reasonId: undefined };
  const directions: readonly Direction[] = [
    { label: words.newest, onPress: onNewest, ...gate(newer, newerHost, newerLine) },
    { label: words.newer, onPress: onNewer, ...gate(newer, newerHost, newerLine) },
    { label: words.older, onPress: onOlder, ...gate(older, olderHost, olderLine) },
  ];
  return (
    <nav aria-label={words.nav} className="cv-pagination" data-cmp="CMP-053" data-mode="cursor">
      <div className="cv-pagination__buttons">
        {directions.map(({ label, onPress, reason, reasonId }) => (
          <Button
            key={label}
            variant="secondary"
            {...(density === undefined ? {} : { density })}
            {...(reason === undefined || reasonId === undefined
              ? {}
              : { disabledReason: reason, disabledReasonId: reasonId })}
            onKeyDown={dropRepeats}
            onClick={onPress}
          >
            {label}
          </Button>
        ))}
      </div>
      {lines.map((line) => (
        <p key={line.id} id={line.id} className="cv-pagination__reason">
          {line.text}
        </p>
      ))}
    </nav>
  );
}
