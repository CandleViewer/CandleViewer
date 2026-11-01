/**
 * SCR-140's chrome parts (E16-D02 §1, §3, §8, §9.3, §10.2; E16-D06 RG-07, RG-08, RG-10, RG-11, SR-01, SR-05 to
 * SR-09, SR-15, BG-01, BG-05): the banner slot (at most one, by priority: disk level 3, an incident, a purge
 * running), the disk card on CMP-050 and CMP-023, the summary line with its one polite region, the page's one
 * assertive region (RG-11's `alert`), and the gap table. Each draws what the model computed; none decides a write
 * (C-12.4).
 */
import { useRef, type JSX, type ReactNode, type RefObject } from "react";
import {
  Button,
  Callout,
  Card,
  ProgressBar,
  Skeleton,
  Table,
  Text,
  useFocusRing,
  type TableColumn,
} from "@candleviewer/ui";
import { TEXT, fill } from "./copy";
import { PurgeView, type PurgeViewState } from "./PurgeView";
import { formatClock, formatDate, formatDuration, updatedLine, type DiskCard } from "./model";
import { GAP_REASONS, PAGE_TEXT, UNKNOWN_GAP } from "./pageCopy";
import type { Gap } from "./useRecorderData";

/** A sentence's first full stop splits a banner into its title and its body (CMP-028: title, then body). */
function split(sentence: string): readonly [string, string] {
  const end = sentence.indexOf(". ");
  return end < 0 ? [sentence, ""] : [sentence.slice(0, end + 1), sentence.slice(end + 2)];
}

/** The design system's ring, drawn inside the landing (CMP-039's inset form): a caption's overflow clips no part. */
const RING = ["cv-focus-ring", "cv-focus-ring--inset"] as const;

/**
 * Readies an element that is no Tab stop to take focus, as the shell's route focus does (`tabindex="-1"`, kept until
 * blur), with CMP-039's inset ring while it holds focus (D-5309-10: the UA's own ring is all but invisible in dark);
 * a dialog's fallback focus target too (A-5347-03).
 */
export function asLanding(element: HTMLElement | null | undefined): HTMLElement | null {
  if (element == null) return null;
  if (!element.hasAttribute("tabindex")) {
    element.setAttribute("tabindex", "-1");
    element.addEventListener("blur", () => element.removeAttribute("tabindex"), { once: true });
  }
  const added = RING.filter((name) => !element.classList.contains(name));
  if (added.length > 0) {
    element.classList.add(...added);
    element.addEventListener("blur", () => element.classList.remove(...added), { once: true });
  }
  return element;
}

/** Moves focus to an element that is no Tab stop (`asLanding`). */
export function focusLanding(element: HTMLElement | null | undefined): void {
  asLanding(element)?.focus();
}

/** The row detail's panel id (CMP-046 `id`): one row detail on the page. */
export const DETAIL_ID = "cv-recorder-detail";

/** The open row detail's heading (CMP-046's title, a focus target), or null while it is closed (A-5347-03). */
export function detailHeading(): HTMLElement | null {
  const title = document.getElementById(DETAIL_ID)?.getAttribute("aria-labelledby") ?? null;
  return title === null ? null : document.getElementById(title);
}

export interface IncidentBanner {
  readonly symbol: string;
  readonly dropped: number;
  /** The gap's interval; null until the coverage read has it on record (C-5309-07). */
  readonly fromMs: number | null;
  readonly toMs: number | null;
}

export interface BannerSlotProps {
  /** The level-3 banner's sentence (the model's `levelThreeBanner`), or null below level 3. */
  readonly levelThree: string | null;
  readonly incident: IncidentBanner | null;
  /** A purge this client started (`usePurge`): its running line or its outcome (`PurgeView`). */
  readonly purge: PurgeViewState | null;
  readonly onViewGaps: () => void;
  /** "Retention policy", once SCR-141 is registered (BQ-11). */
  readonly onRetentionPolicy?: (() => void) | undefined;
  /** The level-3 banner's "Purge data…", busy while this client's purge runs (D02 §3, §6.5). */
  readonly onPurge?: { readonly busy: boolean; readonly open: () => void } | undefined;
  /** A failed purge's "Open {symbol}": the symbol's row detail (D02 §3.2), given while the symbol has a row. */
  readonly onOpenSymbol?: ((symbol: string) => void) | undefined;
}

/** "1 204": D02 §3's grouping of a count. */
const grouped = (count: number): string =>
  Math.round(count).toLocaleString("en-US").replaceAll(",", " ");

/**
 * The banner slot (D02 §3): level 3, then an incident, then a purge running; 0 px when none applies. Level 3 and an
 * incident are CMP-028 danger drawing their words with no live role of their own: the page says each once per
 * condition through its one assertive region, never again while it holds, a moving figure included (SR-07, SR-08,
 * BG-04, BG-05). A purge is info with its CMP-023 bar, its line said once at its arrival and its percentage never
 * (SR-09, BG-02).
 */
export function BannerSlot({
  levelThree,
  incident,
  purge,
  onViewGaps,
  onRetentionPolicy,
  onPurge,
  onOpenSymbol,
}: BannerSlotProps): JSX.Element | null {
  if (levelThree !== null) {
    const [title, body] = split(levelThree);
    const actions = [
      ...(onPurge === undefined
        ? []
        : [{ label: TEXT.levelThreeActions[0], onClick: onPurge.open, loading: onPurge.busy }]),
      ...(onRetentionPolicy === undefined
        ? []
        : [{ label: PAGE_TEXT.retentionPolicy, onClick: onRetentionPolicy }]),
    ];
    return (
      <Callout key="level-3" tone="danger" live="off" title={title} actions={actions}>
        {body}
      </Callout>
    );
  }
  if (incident !== null) {
    const [title, body] = split(incidentSentence(incident));
    // "View gaps" lands on the gap table, which exists once a gap is on record: the action is offered then, never as
    // a button that does nothing (C-5309-d03).
    const actions = incident.fromMs === null ? [] : [{ label: TEXT.viewGaps, onClick: onViewGaps }];
    return (
      <Callout key="incident" tone="danger" live="off" title={title} actions={actions}>
        {body}
      </Callout>
    );
  }
  if (purge !== null) {
    // Its words are said once by `usePurge`, through the shell's announcer (A-5347-04).
    return (
      <PurgeView
        key={`purge-${purge.symbol}`}
        state={purge}
        placement="banner"
        onOpen={onOpenSymbol}
      />
    );
  }
  return null;
}

/** The incident's sentence: with its gap's interval once on record, else without one (C-5309-07, PROPOSED). */
export function incidentSentence(incident: IncidentBanner): string {
  const values = { "{count}": grouped(incident.dropped), "{symbol}": incident.symbol };
  return incident.fromMs === null || incident.toMs === null
    ? fill(TEXT.incidentOpen, values)
    : fill(TEXT.incident, {
        ...values,
        "{from}": formatClock(incident.fromMs),
        "{to}": formatClock(incident.toMs),
      });
}

/** What the page's assertive region says: re-keyed per write, so the same words after a release are said again. */
export interface Said {
  readonly text: string;
  readonly n: number;
}

/**
 * The page's one assertive region (RG-11's `alert`; E16-D06 BG-05): pre-rendered empty at load, written once per
 * condition by the batch announcer (`alert`, after a pending batch, BG-06), emptied when no condition holds. Like the
 * shell's own regions it stays in the accessibility tree under a modal (`data-cv-inert-exempt`, E05-D02 H23), so a
 * condition that begins while a dialog is open is still read out (A-5309-d02).
 */
export function AlertRegion({ said }: { readonly said: Said }): JSX.Element {
  return (
    <div className="cv-visually-hidden" role="alert" aria-atomic="true" data-cv-inert-exempt="">
      {said.n === 0 || said.text === "" ? null : <span key={said.n}>{said.text}</span>}
    </div>
  );
}

const TONES = { primary: "default", warning: "warning", danger: "danger" } as const;

export interface DiskCardPanelProps {
  /** The model's card; null when no figures exist (the disk read failed: its banner says so). */
  readonly card: DiskCard | null;
  readonly loading: boolean;
  /** D02 §8.3's suggested actions, by their words. */
  readonly onSuggested: (action: string) => void;
  /** The card's entry points and Compact now (D02 §1). */
  readonly actions: ReactNode;
  /** A purge's line while level 3 or an incident holds the banner slot, or its result (D02 §3, §3.2). */
  readonly purgeLine?: ReactNode;
}

/** The disk card (D02 §3, §8.3): the state-first headline, the bar with its words, the scale, the formula. */
export function DiskCardPanel({
  card,
  loading,
  onSuggested,
  actions,
  purgeLine = null,
}: DiskCardPanelProps): JSX.Element | null {
  if (loading) {
    return (
      <Card>
        <div aria-busy="true">
          <Skeleton shape="text" count={3} />
        </div>
      </Card>
    );
  }
  if (card === null) return null;
  const pct = card.meter === null ? 0 : (card.meter.value / card.meter.max) * 100;
  return (
    <Card title={card.headline} headingLevel={2}>
      <div style={{ display: "grid", gap: "var(--space-stack-sm)" }}>
        {card.meter === null ? null : (
          <ProgressBar
            label={PAGE_TEXT.budget}
            value={pct}
            valueText={card.meter.text}
            tone={TONES[card.tone]}
          />
        )}
        {card.scale === null ? null : (
          <Text variant="caption" tone="secondary">
            {card.scale}
          </Text>
        )}
        {card.lines.map((line) => (
          <Text key={line} tone="secondary">
            {line}
          </Text>
        ))}
        {purgeLine}
        {card.suggested.length === 0 ? null : (
          <div style={{ display: "flex", flexWrap: "wrap", gap: "var(--space-inset-xs)" }}>
            {card.suggested.map((action) => (
              <Button key={action} variant="ghost" size="sm" onClick={() => onSuggested(action)}>
                {action}
              </Button>
            ))}
          </div>
        )}
        <div
          style={{
            display: "flex",
            flexWrap: "wrap",
            alignItems: "start",
            gap: "var(--space-inset-xs)",
          }}
        >
          {actions}
        </div>
      </div>
    </Card>
  );
}

export interface SummaryLineProps {
  /** The model's summary (`summaryLine`), or its stale words (`staleLine`). */
  readonly line: string;
  /** When the newest frame was read: "updated hh:mm:ss UTC", outside the region (§8.2). */
  readonly updatedAtMs: number | null;
  /** The summary's "{m} auto-recorded" applies the Reason: Auto chip (§5.2). */
  readonly onAutoReview: () => void;
  /** The region's newest batch (SR-01): re-keyed per batch, so the same words twice are said twice. */
  readonly said: { readonly text: string; readonly n: number };
}

const AUTO = /^(\d+) auto-recorded$/;

/**
 * The summary line (D02 §1, §5.2, §9.3): the counts and the recorder's state word, "{m} auto-recorded" a link that
 * applies the chip, "updated hh:mm:ss UTC" beside it; and RG-10, the one polite region, pre-rendered empty, which
 * says the 10 s batch of state changes (never a ticking number, BG-01, BG-04); it too stays exposed under a modal
 * (`data-cv-inert-exempt`, A-5309-d02).
 */
export function SummaryLine({
  line,
  updatedAtMs,
  onAutoReview,
  said,
}: SummaryLineProps): JSX.Element {
  const ring = useFocusRing();
  const parts = line.split(" · ");
  return (
    <div
      style={{
        display: "flex",
        flexWrap: "wrap",
        justifyContent: "space-between",
        alignItems: "baseline",
        gap: "var(--space-inset-sm)",
      }}
    >
      <p style={{ margin: 0 }}>
        {parts.map((part, i) => {
          const auto = AUTO.exec(part);
          const sep = i === 0 ? "" : " · ";
          if (auto === null || auto[1] === "0") return `${sep}${part}`;
          // One key whatever the count, so a count that changes keeps the link and its focus (C-5309-04).
          return (
            <span key="auto">
              {sep}
              <button
                type="button"
                className={`cv-link ${ring.className}`}
                style={{ padding: 0, border: 0, background: "none" }}
                onClick={onAutoReview}
              >
                {part}
              </button>
            </span>
          );
        })}
      </p>
      {updatedAtMs === null ? null : (
        <span
          style={{
            color: "var(--color-text-tertiary)",
            font: "var(--type-ui-caption-font-weight) var(--type-ui-caption-font-size) / var(--type-ui-caption-line-height) var(--type-ui-caption-font-family)",
          }}
        >
          {updatedLine(updatedAtMs)}
        </span>
      )}
      <div
        className="cv-visually-hidden"
        role="status"
        aria-live="polite"
        aria-atomic="true"
        data-cv-inert-exempt=""
      >
        {said.n === 0 ? null : <span key={said.n}>{said.text}</span>}
      </div>
    </div>
  );
}

/** The gap table's columns (D02 §10.2). */
const GAP_COLUMNS = [
  {
    id: "start",
    header: PAGE_TEXT.gapColumns.start,
    cell: (g: Gap) => formatClock(g.fromMs),
    align: "end",
  },
  {
    id: "end",
    header: PAGE_TEXT.gapColumns.end,
    cell: (g: Gap) => formatClock(g.toMs),
    align: "end",
  },
  {
    id: "duration",
    header: PAGE_TEXT.gapColumns.duration,
    cell: (g: Gap) => formatDuration(Math.max(1, Math.round((g.toMs - g.fromMs) / 1000))),
    align: "end",
  },
  {
    id: "reason",
    header: PAGE_TEXT.gapColumns.reason,
    cell: (g: Gap) => (g.reason === null ? UNKNOWN_GAP : (GAP_REASONS[g.reason] ?? UNKNOWN_GAP)),
  },
] as const;

export interface GapTableProps {
  readonly gaps: readonly Gap[];
  /** The page's clock: a time on an earlier UTC day than it carries its date (C-5309-13). */
  readonly nowMs: number;
  /** Holds the table, so "View gaps" can reach its caption. */
  readonly hostRef: RefObject<HTMLDivElement>;
}

/** "10:14:03" on the page's UTC day, else "2026-09-13 23:10:00": the last 24 h span two days. */
const dayTime = (ms: number, nowMs: number): string =>
  formatDate(ms) === formatDate(nowMs) ? formatClock(ms) : `${formatDate(ms)} ${formatClock(ms)}`;

/** The gap table's columns on the page's clock: the page's table and the row detail's (D02 §6.7) alike. */
export function gapColumns(nowMs: number): readonly TableColumn<Gap>[] {
  return [
    { ...GAP_COLUMNS[0], cell: (g: Gap) => dayTime(g.fromMs, nowMs) },
    { ...GAP_COLUMNS[1], cell: (g: Gap) => dayTime(g.toMs, nowMs) },
    GAP_COLUMNS[2],
    GAP_COLUMNS[3],
  ];
}

/** The gaps of the last 24 h (D02 §1, §10.2; RG-08): a static CMP-049 table under the list, with no Tab stop. */
export function GapTable({ gaps, nowMs, hostRef }: GapTableProps): JSX.Element | null {
  if (gaps.length === 0) return null;
  return (
    <div ref={hostRef}>
      <Table
        columns={gapColumns(nowMs)}
        rows={gaps}
        rowKey={(g) => `${g.symbol}|${g.fromMs}|${g.toMs}|${g.reason ?? ""}`}
        caption={TEXT.gapsCaption}
      />
    </div>
  );
}

/** "View gaps" (D02 §3 degraded): focus moves to the gap table's caption. */
export function useGapLanding(): {
  readonly hostRef: RefObject<HTMLDivElement>;
  readonly land: () => void;
} {
  const hostRef = useRef<HTMLDivElement>(null);
  return { hostRef, land: () => focusLanding(hostRef.current?.querySelector("caption")) };
}
