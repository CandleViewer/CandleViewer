/**
 * SCR-142 Admin: storage and database (E16-S04; E16-D04 §2–§5, §9, §10; E16-D06 KB-14, FM-14, RG-13, SR-27, T2-09,
 * T2-12, §13 "Reading the picture", §20.3 (i), (ix); BQ-5 to BQ-15): a section of `/admin/recorder` that SCR-140
 * draws once this part is registered (`register.ts`). Its heading takes the page's `headingId` ("Storage details"
 * lands there). Top to bottom: the sample stamp (its Retry, first in the Tab order, while stale), the one view-as
 * notice, the banners (the unavailable report, the ingestion backlog), region (b) the meters and what stops first,
 * (c) the three tier cards, (d) the row counts' fallback, (e) the per-symbol table, (f) the slow queries' fallback,
 * then the System health link and the section's one polite region. It reads the 60 s sample (`useStorageReport`) and
 * the page's live frame; it renders the server's answers and decides no write (C-12.4). No store console, no host
 * path (R-I1, §20.3 (ix)).
 */
import {
  useCallback,
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type FocusEvent,
  type JSX,
  type ReactNode,
} from "react";
import { Link as RouterLink } from "react-router";
import {
  Button,
  Callout,
  FreshnessMarker,
  GatedAnnounceProvider,
  Heading,
  Icon,
  Link,
  Skeleton,
  Text,
  type LinkRoute,
} from "@candleviewer/ui";
import { DECK, fill } from "../copy";
import { useRecorderExtensions, type StoragePanelProps } from "../extensions";
import { diskFacts, parseMs } from "../model";
import { sayPolitely } from "../pageAnnouncer";
import { recorderApi, type ImportBody } from "../recorderApi";
import { focusLanding } from "../RecorderChrome";
import { BudgetMeters } from "./BudgetMeters";
import { ImportCard, useImportSymbols } from "./ImportCard";
import { CompactConfirm, MaintenanceCard, type StripLine } from "./MaintenanceCard";
import { reportStorage } from "./storageAnalytics";
import { STORAGE_DECK } from "./storageCopy";
import { compactOutcome, importOutcome, progressLine, verbOf } from "./storageJobs";
import {
  attributionLine,
  isBacklogged,
  lagBannerOf,
  lagThresholdLine,
  stampView,
  symbolRows,
  tierViews,
  TIERS,
  type TierId,
} from "./storageModel";
import { SymbolTable } from "./SymbolTable";
import { TierCards } from "./TierCards";
import { useStorageJob } from "./useStorageJob";
import { useStorageReport } from "./useStorageReport";
import { WriteButton, type WriteGate } from "./WriteButton";

/** A view-as context (E09-D09 §3.1 `rbac.view_as`): its target's name. */
export interface ViewAs {
  readonly user: string;
}

export interface StoragePanelOptions {
  /**
   * The view-as context (BQ-8): no client source exists yet, so nothing passes it and the leg is dormant; set, every
   * write is T2 and points at the one notice, while the reads, the tables and a running job keep updating.
   */
  readonly viewAs?: ViewAs | null | undefined;
  /** What a press says, once, politely: the shell announcer (a T2 reason, a refusal at the point of action). */
  readonly say?: ((text: string) => void) | undefined;
  /** The section's clock (tests inject the fake one). */
  readonly now?: (() => number) | undefined;
  /** The import's instrument list; the shell's running index by default. */
  readonly instruments?: readonly string[] | undefined;
}

const routerLink: LinkRoute = ({ to, ...anchor }) => <RouterLink to={to} {...anchor} />;
const [TITLE] = STORAGE_DECK["storage.title"];
const [UNAVAILABLE] = STORAGE_DECK["storage.unavailable"];
const [STALE_SAID] = STORAGE_DECK["storage.stale.announce"];
const [RETRY] = STORAGE_DECK["storage.tier.retry"];
const [NOTICE] = STORAGE_DECK["notice.panel_read_only"];
const [HEALTH_LINK] = STORAGE_DECK["storage.links.health"];
const [ROWS_FALLBACK] = STORAGE_DECK["storage.proposed.rows"];
const [QUERIES_FALLBACK] = STORAGE_DECK["storage.proposed.queries"];

/** Which Retry: the sample stamp's, the unavailable banner's, or a down tier's card's (its host's `data-cv-retry`). */
type RetryAt = "stamp" | "banner" | TierId;
const isRetryAt = (value: string | null | undefined): value is RetryAt =>
  value === "stamp" || value === "banner" || TIERS.some((tier) => tier === value);
/** A pressed Retry's read has landed: the control that was pressed, found by its host. */
interface Landing {
  readonly at: RetryAt;
  readonly control: HTMLElement | null;
}

export function StoragePanel({
  headingId,
  status,
  storage,
  historySinceMs = null,
  stale: topicStale,
  frame,
  purge,
  openRetention,
  onSuggested,
  viewAs = null,
  say = sayPolitely,
  now = Date.now,
  instruments,
}: StoragePanelProps & StoragePanelOptions): JSX.Element {
  const id = useId();
  const { openRowDetail } = useRecorderExtensions();
  const reads = useStorageReport(storage, now);
  const { report, failed, loading, health, healthFailed, nowMs } = reads;
  const facts = diskFacts(report, frame);
  const policy = frame?.policy ?? status?.policy ?? null;
  const sampledMs = parseMs(report?.generated_at);
  const stamp = stampView(sampledMs, nowMs, failed);
  const stale = stamp?.stale === true;
  // The page's topic is stale: what the section takes from its last frame is tagged so (C-486P3-08).
  const frameStale = topicStale && frame !== null;
  const pressure = {
    rate: frame?.ingest_rate_msgs_per_sec ?? status?.ingest_rate_msgs_per_sec ?? null,
    backlog: frame?.write_backlog_rows ?? status?.write_backlog_rows ?? null,
  };
  const nothingRecorded = (frame?.symbols ?? status?.symbols ?? []).length === 0;
  // Only a row the page lists has a detail to open (C-486P3-12): its frame's symbols and its status's.
  const listed = new Set(
    [...(frame?.symbols ?? []), ...(status?.symbols ?? [])]
      .map((s) => s.symbol)
      .filter((symbol): symbol is string => symbol !== undefined),
  );
  const noticeId = `${id}-notice`;
  const gate: WriteGate | null = viewAs === null ? null : { user: viewAs.user, noticeId };

  // The story's own key, once per entry (D04-D10); StrictMode's second run is the same entry.
  const viewed = useRef(false);
  useEffect(() => {
    if (viewed.current) return;
    viewed.current = true;
    reportStorage({ name: "storage.panel_viewed" });
  }, []);

  // RG-13: the section's one polite region, pre-rendered empty; each utterance re-keys its node. A condition's line
  // (stale, unavailable) leaves it when the condition ends, so the region never holds a state that has passed.
  const [said, setSaid] = useState({ text: "", n: 0 });
  const speak = useCallback((text: string) => setSaid((prev) => ({ text, n: prev.n + 1 })), []);
  const unsay = useCallback(
    (text: string) => setSaid((prev) => (prev.text === text ? { text: "", n: prev.n } : prev)),
    [],
  );

  // SR-27: the turn to stale is said once, as it begins; the stamp's age changes silently.
  const wasStale = useRef(false);
  useEffect(() => {
    if (stale && !wasStale.current) speak(STALE_SAID);
    if (!stale && wasStale.current) unsay(STALE_SAID);
    wasStale.current = stale;
  }, [stale, speak, unsay]);

  // A read that fails with no report to keep has no stamp to turn stale: the banner's words are said once per
  // episode, through the same region (A-486P3-07).
  const unreported = failed && report === null;
  const wasUnreported = useRef(false);
  useEffect(() => {
    if (unreported && !wasUnreported.current) speak(UNAVAILABLE);
    if (!unreported && wasUnreported.current) unsay(UNAVAILABLE);
    wasUnreported.current = unreported;
  }, [unreported, speak, unsay]);

  // The backlog warning holds over two frames (D04 `SCR-142/lag-warning`): one high frame is not a state.
  const lastBacklog = useRef<number | null>(null);
  const [lagging, setLagging] = useState(false);
  useEffect(() => {
    const backlog = frame?.write_backlog_rows ?? null;
    setLagging(isBacklogged(lastBacklog.current) && isBacklogged(backlog));
    lastBacklog.current = backlog;
  }, [frame]);
  const views = tierViews(report, health, facts, pressure, {
    lagging,
    healthStale: healthFailed,
    pressureStale: frameStale,
  });

  // FM-14: once a Retry's read lands, focus goes to what it restored if its Retry is gone; a read (no press) that
  // takes away the Retry holding focus lands the same way (E09-D09 §9.4; A-486P3-04). A Retry is found by its host
  // (`data-cv-retry`), never by `document.activeElement`: a click need not focus a button (C-486P3-10).
  const root = useRef<HTMLElement>(null);
  const cards = useRef(new Map<TierId, HTMLDivElement>());
  const hostRef = useCallback(
    (tier: TierId) => (element: HTMLDivElement | null) => {
      if (element === null) cards.current.delete(tier);
      else cards.current.set(tier, element);
    },
    [],
  );
  const retryButton = (at: RetryAt): HTMLElement | null =>
    root.current?.querySelector<HTMLElement>(`[data-cv-retry="${at}"] button`) ?? null;
  /**
   * Lands focus for the Retry `at` once it is gone: a stamp's read that failed on the banner's Retry, the next stop
   * (C-486P3-10); else on the heading of what it restored, the section's or the card's.
   */
  const land = useCallback(
    (at: RetryAt): void => {
      if (at !== "stamp" && at !== "banner") {
        focusLanding(cards.current.get(at)?.querySelector("h3"));
        return;
      }
      const banner =
        at === "stamp"
          ? root.current?.querySelector<HTMLElement>('[data-cv-retry="banner"] button')
          : null;
      if (banner === null || banner === undefined) focusLanding(document.getElementById(headingId));
      else banner.focus(); // a Tab stop of its own: no landing ring
    },
    [headingId],
  );
  /** The Retry that holds focus, while it does. */
  const focused = useRef<{ readonly at: RetryAt; readonly element: HTMLElement } | null>(null);
  /** A Retry whose read is out: its landing waits for the read (FM-14). */
  const pressed = useRef<RetryAt | null>(null);
  // Every commit: a Retry that held focus and is gone, with no press out, was taken away by a read.
  useLayoutEffect(() => {
    const was = focused.current;
    if (was === null || was.element.isConnected) return;
    focused.current = null;
    if (pressed.current === null && document.activeElement === document.body) land(was.at);
  });
  const track = (event: FocusEvent<HTMLElement>): void => {
    const at = event.target.closest("[data-cv-retry]")?.getAttribute("data-cv-retry");
    focused.current =
      event.target instanceof HTMLButtonElement && isRetryAt(at)
        ? { at, element: event.target }
        : null;
  };
  const untrack = (event: FocusEvent<HTMLElement>): void => {
    // Leaving a Retry that still stands is the user's move; a Retry a read takes away goes with its node.
    if (focused.current?.element === event.target && event.target.isConnected) {
      focused.current = null;
    }
  };
  const [landing, setLanding] = useState<Landing | null>(null);
  useEffect(() => {
    if (landing === null) return;
    setLanding(null);
    // The Retry still stands (the read brought no change): focus stays on it.
    if (landing.control?.isConnected === true) return;
    // Focus the user moved while the read was out stays where it went.
    if (document.activeElement !== null && document.activeElement !== document.body) return;
    land(landing.at);
  }, [landing, land]);
  const retry = (at: RetryAt) => async (): Promise<void> => {
    const control = retryButton(at);
    pressed.current = at;
    try {
      await reads.retry();
    } finally {
      pressed.current = null;
    }
    setLanding({ at, control });
  };

  // Compact Parquet… (D04 §6): one job and one confirm for its two buttons, the Parquet card's and region (g)'s.
  const compaction = useStorageJob<null>(
    "compact",
    (view) => compactOutcome(view, now()),
    speak,
    say,
  );
  const [confirmAt, setConfirmAt] = useState<string | null>(null);
  const confirmCompaction = (): void => {
    const at = confirmAt ?? "maintenance";
    setConfirmAt(null);
    void compaction.start(at, null, () => recorderApi.compact());
  };
  const compactButton = (at: string): ReactNode => (
    <WriteButton
      gate={gate}
      at={at}
      refusal={compaction.refusal}
      variant="secondary"
      loading={compaction.busy}
      onClick={() => setConfirmAt(at)}
    >
      {DECK["storage.compact.button"][0]}
    </WriteButton>
  );
  // Purge data… opens the page's one purge dialog (E16-D02 §6.5, #484 PR 3; BQ-9): on QuestDB and Parquet only.
  const purgeButton =
    purge === undefined ? null : (
      <WriteButton
        gate={gate}
        variant="secondary"
        loading={purge.busy}
        onClick={() => purge.open()}
      >
        {DECK["storage.purge.button"][0]}
      </WriteButton>
    );
  const cardActions = (tier: TierId): ReactNode =>
    tier === "parquet" ? (
      <>
        {compactButton("parquet")}
        {purgeButton}
      </>
    ) : tier === "questdb" ? (
      purgeButton
    ) : null;
  // The import (D04 §8): the card's form is its confirm (BQ-12).
  const importJob = useStorageJob<ImportBody>("import", importOutcome, speak, say);
  const symbols = useImportSymbols(instruments, report, status, frame);
  const startImport = (request: ImportBody): void =>
    void importJob.start("import", request, (body) => recorderApi.importArchive(body));

  // The jobs strip: one line per job this client started, while it runs, a refused poll's T4 under it.
  const lines: StripLine[] = [];
  for (const [kind, job] of [
    ["compact", compaction],
    ["import", importJob],
  ] as const) {
    const view = job.view;
    if (view?.phase === "running") {
      lines.push({
        key: kind,
        verb: verbOf(kind),
        text: progressLine(kind, view),
        value: view.pct,
        refused: job.pollRefused,
      });
    }
  }

  const stampRetry = stale && !failed;
  return (
    <GatedAnnounceProvider announce={say}>
      <section
        ref={root}
        aria-labelledby={headingId}
        style={{ display: "grid", gap: "var(--space-stack-md)", minWidth: 0 }}
        onFocus={track}
        onBlur={untrack}
      >
        <div style={{ display: "grid", gap: "var(--space-stack-xs)" }}>
          <Heading level={2} variant="heading-lg" id={headingId}>
            {TITLE}
          </Heading>
          {stamp === null ? null : (
            <div
              data-cv-retry="stamp"
              style={{
                display: "flex",
                flexWrap: "wrap",
                alignItems: "center",
                gap: "var(--space-inset-xs)",
              }}
            >
              {stale ? (
                // CMP-239 `stale` on the stamp (D04 §2 (a), §5 `stale-sample`; C-486P3-04 (b)): drawn beside its
                // words, which already say the state and the age, so assistive technology reads them once.
                <span aria-hidden="true">
                  <FreshnessMarker
                    presentation="compact"
                    state="stale"
                    lastUpdatedAgeMs={sampledMs === null ? 0 : nowMs - sampledMs}
                  />
                </span>
              ) : null}
              <Text variant="caption" tone="secondary">
                {stamp.text}
              </Text>
              {stampRetry ? (
                <Button variant="secondary" size="sm" onClick={() => void retry("stamp")()}>
                  {RETRY}
                </Button>
              ) : null}
            </div>
          )}
          {gate === null ? null : (
            <p
              id={noticeId}
              style={{
                margin: 0,
                display: "flex",
                gap: "var(--space-inset-xs)",
                alignItems: "center",
                color: "var(--color-text-secondary)",
              }}
            >
              <Icon name="lock" />
              {fill(NOTICE, { "{user}": gate.user })}
            </p>
          )}
        </div>
        {failed ? (
          <div data-cv-retry="banner">
            <Callout
              tone="danger"
              live="off"
              title={UNAVAILABLE}
              retry={{ label: RETRY, onClick: () => void retry("banner")() }}
            />
          </div>
        ) : null}
        {lagging && pressure.backlog !== null ? (
          // The threshold stated beside the banner (D04 `SCR-142/lag-warning`; C-486P3-04 (a)).
          <Callout tone="warning" live="off" title={lagBannerOf(pressure.backlog)}>
            {lagThresholdLine()}
          </Callout>
        ) : null}
        {loading ? (
          <div aria-busy="true" style={{ display: "grid", gap: "var(--space-stack-sm)" }}>
            <Skeleton shape="text" count={3} />
            <Skeleton shape="card" count={3} />
          </div>
        ) : (
          <>
            {report === null ? null : (
              <BudgetMeters
                facts={facts}
                report={report}
                policy={policy}
                nothingRecorded={nothingRecorded}
                nowMs={nowMs}
                historySinceMs={historySinceMs}
                stale={stale || frameStale}
                openRetention={openRetention}
                onSuggested={onSuggested}
              />
            )}
            <TierCards
              views={views}
              stale={stale}
              onRetry={(tier) => void retry(tier)()}
              actions={cardActions}
              hostRef={hostRef}
            />
            <Text as="p" tone="secondary">
              {ROWS_FALLBACK}
            </Text>
            <SymbolTable
              rows={symbolRows(report)}
              attribution={attributionLine(report)}
              onOpen={openRowDetail}
              listed={listed}
              announce={speak}
            />
            <Text as="p" tone="secondary">
              {QUERIES_FALLBACK}
            </Text>
            <MaintenanceCard
              compact={compactButton("maintenance")}
              lines={lines}
              outcome={compaction.outcome}
            />
            <ImportCard
              symbols={symbols}
              job={importJob}
              gate={gate}
              onStart={startImport}
              announce={speak}
              now={now}
            />
          </>
        )}
        <span>
          <Link to="/admin/health" as={routerLink}>
            {HEALTH_LINK}
          </Link>
        </span>
        {/* Live under a modal too, as the shell's regions are (E05-D02 H23; A-486P3-05). */}
        <div
          className="cv-visually-hidden"
          role="status"
          aria-live="polite"
          aria-atomic="true"
          data-cv-inert-exempt=""
        >
          {said.text === "" ? null : <span key={said.n}>{said.text}</span>}
        </div>
        <CompactConfirm
          open={confirmAt !== null}
          onConfirm={confirmCompaction}
          onCancel={() => setConfirmAt(null)}
        />
      </section>
    </GatedAnnounceProvider>
  );
}
