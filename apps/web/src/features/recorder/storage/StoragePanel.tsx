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
import { useCallback, useEffect, useId, useRef, useState, type JSX } from "react";
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
import { fill } from "../copy";
import { useRecorderExtensions, type StoragePanelProps } from "../extensions";
import { diskFacts, parseMs } from "../model";
import { sayPolitely } from "../pageAnnouncer";
import { focusLanding } from "../RecorderChrome";
import { BudgetMeters } from "./BudgetMeters";
import { reportStorage } from "./storageAnalytics";
import { STORAGE_DECK } from "./storageCopy";
import {
  attributionLine,
  isBacklogged,
  lagBannerOf,
  lagThresholdLine,
  stampView,
  symbolRows,
  tierViews,
  type TierId,
} from "./storageModel";
import { SymbolTable } from "./SymbolTable";
import { TierCards } from "./TierCards";
import { useStorageReport } from "./useStorageReport";

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
}

/** The view-as leg as a write's T2 needs it: the reason (`rbac.view_as`) and the one notice's id. */
export interface WriteGate {
  readonly user: string;
  readonly noticeId: string;
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

/** Where focus lands after a Retry succeeds (FM-14): the section's heading, or a card's. */
type Landing = { readonly kind: "section" } | { readonly kind: "tier"; readonly tier: TierId };

export function StoragePanel({
  headingId,
  status,
  storage,
  historySinceMs = null,
  stale: topicStale,
  frame,
  openRetention,
  onSuggested,
  viewAs = null,
  say = sayPolitely,
  now = Date.now,
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

  // FM-14: once a Retry's read lands, focus goes to the heading of what it restored, if its Retry is gone.
  const cards = useRef(new Map<TierId, HTMLDivElement>());
  const hostRef = useCallback(
    (tier: TierId) => (element: HTMLDivElement | null) => {
      if (element === null) cards.current.delete(tier);
      else cards.current.set(tier, element);
    },
    [],
  );
  const [landing, setLanding] = useState<Landing | null>(null);
  const downTiers = views
    .filter((view) => view.health.down)
    .map((view) => view.tier)
    .join(",");
  useEffect(() => {
    if (landing === null) return;
    setLanding(null);
    if (landing.kind === "section") {
      if (!failed && !stale) focusLanding(document.getElementById(headingId));
    } else if (!downTiers.split(",").includes(landing.tier)) {
      focusLanding(cards.current.get(landing.tier)?.querySelector("h3"));
    }
  }, [landing, failed, stale, downTiers, headingId]);
  const retry = (to: Landing) => async (): Promise<void> => {
    await reads.retry();
    setLanding(to);
  };

  const stampRetry = stale && !failed;
  return (
    <GatedAnnounceProvider announce={say}>
      <section
        aria-labelledby={headingId}
        style={{ display: "grid", gap: "var(--space-stack-md)", minWidth: 0 }}
      >
        <div style={{ display: "grid", gap: "var(--space-stack-xs)" }}>
          <Heading level={2} variant="heading-lg" id={headingId}>
            {TITLE}
          </Heading>
          {stamp === null ? null : (
            <div
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
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => void retry({ kind: "section" })()}
                >
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
          <Callout
            tone="danger"
            live="off"
            title={UNAVAILABLE}
            retry={{ label: RETRY, onClick: () => void retry({ kind: "section" })() }}
          />
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
              onRetry={(tier) => void retry({ kind: "tier", tier })()}
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
      </section>
    </GatedAnnounceProvider>
  );
}
