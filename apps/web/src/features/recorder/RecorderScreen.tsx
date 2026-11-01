/**
 * SCR-140 Admin: recorder & storage (E16-S01; E16-D02 §1–§3, §5.2, §8, §9.3; E16-D06 KB-01, FM-14, RG-07 to RG-11,
 * SR-01, SR-05 to SR-08, SR-14, SR-15, BG-01, BG-05, BG-06; Q-04; BQ-3, BQ-6, BQ-7, BQ-11, BQ-12): the page's
 * content, which CMP-087 AdminLayout (E42-S01) hosts. CMP-088 PageHeader holds the H1 "Recorder" and "Record a
 * symbol"; then the default statement, the banner slot, the disk card, the summary line, the search and filters,
 * the grid, the gaps of the last 24 h and SCR-142's section once registered. The summary's 10 s batch and the
 * level-3, incident and failed-purge banners (once per condition) are said through the shell's two regions, which a
 * modal leaves exposed: the page keeps no live region of its own (#484 PR 3). Loading draws skeletons; a
 * first read that fails names its part with Retry, whose success, or the loss of the pressed Retry, restores focus
 * to the H1 (F-05); no frame for 2 s turns the page stale; with no symbol, CMP-026 replaces the grid. The server's
 * times are read on the server's clock (the newest frame's `ts`, else the status's `generated_at`). A T2 press
 * anywhere on the page is said once through the shell announcer (its own GatedAnnounceProvider: the shell's says
 * nothing, #5135). Nothing polls (Q-04). The page renders the server's answers and decides no write (C-12.4).
 * Mounted at R-340 /admin/recorder inside the admin area, behind its Owner-only guard (#484 PR 3).
 */
import {
  useCallback,
  useEffect,
  useId,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
  type JSX,
} from "react";
import {
  Button,
  Callout,
  EmptyState,
  GatedAnnounceProvider,
  PageHeader,
  Skeleton,
  Text,
  type FilterBarFilter,
} from "@candleviewer/ui";
import { afterAssertiveBudget, announce, clearAnnouncements, forget } from "../app-shell/announcer";
import { reportRecorder } from "./analytics";
import { CompactNow } from "./CompactNow";
import { DECK, TEXT, fill } from "./copy";
import { registerRecorderExtensions, useRecorderExtensions } from "./extensions";
import { AUTO_FILTER, DEEP_FILTERS, PINNED_FILTER, type GridSort, type RowContext } from "./grid";
import {
  buildRows,
  createBatchAnnouncer,
  diskCard,
  diskFacts,
  firstSeen,
  formatDuration,
  levelChange,
  levelThreeBanner,
  parseMs,
  rowChanges,
  rowStates,
  staleLine,
  summaryLine,
  type AnnouncerClock,
  type DiskLevel,
  type Politeness,
  type RowState,
} from "./model";
import { sayPolitely } from "./pageAnnouncer";
import { PAGE_TEXT } from "./pageCopy";
import {
  BannerSlot,
  DiskCardPanel,
  GapTable,
  SummaryLine,
  asLanding,
  focusLanding,
  incidentSentence,
  useGapLanding,
  type IncidentBanner,
} from "./RecorderChrome";
import { RecorderGrid } from "./RecorderGrid";
import { RecordSymbolDialog } from "./RecordSymbolDialog";
import { purgeTargets } from "./purge";
import { PurgeDialog } from "./PurgeDialog";
import { PurgeView } from "./PurgeView";
import { usePurge } from "./usePurge";
import { useRecorderData, type RecorderDataOptions } from "./useRecorderData";
import { useRunningIndex } from "../symbol-search/searchSession";

/** The H1's id (the skip link's target, CMP-088) and SCR-142's heading's ("Storage details"). */
export const RECORDER_H1_ID = "cv-recorder-title";
export const STORAGE_HEADING_ID = "cv-recorder-storage";

export interface RecorderScreenProps {
  /** The reads' options: the topic's client and clock (tests inject a fake socket). */
  readonly data?: RecorderDataOptions;
  /** The add's instrument list; the shell's running index by default. */
  readonly instruments?: readonly string[];
  /** The summary batch's 10 s clock (tests inject a fake one). */
  readonly announcerClock?: AnnouncerClock;
}

const noSubscription = (): (() => void) => () => undefined;

/** The USDT perpetuals the shell's instrument index lists, once it runs (E08-S09). */
function useInstruments(given: readonly string[] | undefined): readonly string[] {
  const index = useRunningIndex();
  const snapshot = useSyncExternalStore(index?.subscribe ?? noSubscription, () =>
    index === null ? null : index.getSnapshot(),
  );
  return given ?? snapshot?.entries.map((entry) => entry.symbol) ?? [];
}

const [, SHORTEN, REDUCE, UNPIN] = DECK["d02.8.r19"];
const split = (sentence: string): readonly [string, string] => {
  const end = sentence.indexOf(". ");
  return end < 0 ? [sentence, ""] : [sentence.slice(0, end + 1), sentence.slice(end + 2)];
};
const LEVEL_3 = "level-3";

/**
 * The page's two channels into the shell's regions (E17-D02 §11; RG-10 and RG-11 now), pre-rendered at load and
 * exempt from a modal's `inert`, so they are heard under every dialog and the row detail. The page keeps no live
 * region of its own: an exempt node inside it keeps the whole path down to it live under a modal, the shell's
 * scrolling canvas included (axe `scrollable-region-focusable`, #484 PR 3).
 */
const PAGE_CHANNELS = { polite: "recorder:summary", assertive: "recorder:alert" } as const;
/** Every key the page writes under: its two channels, a press's (`pageAnnouncer`) and a purge's (`usePurge`). */
const PAGE_KEYS = "recorder:";

interface ShellVoice {
  readonly say: (politeness: Politeness, text: string) => void;
  /** Drops the assertive lines still waiting their turn (the page going). */
  readonly hush: () => void;
}
/**
 * The page's voice through those channels. A write's key is forgotten first, so the same words in a later episode are
 * said again; once per condition and the 10 s cadence are the batch announcer's. An assertive line waits its turn in
 * the shell's region (5 s from its last message, whoever wrote it, E17-D02 §11), so it never cuts another writer's
 * (A-5347-d05). A line already waiting when its condition ends is still said: the batch announcer's release reaches
 * what it holds, not the region's queue.
 */
function shellVoice(): ShellVoice {
  const waiting = new Set<{ cancel: () => void }>();
  const write = (politeness: Politeness, text: string): void => {
    const key = PAGE_CHANNELS[politeness];
    forget(key);
    announce(politeness, text, key);
  };
  return {
    say(politeness, text) {
      if (politeness === "polite") {
        write(politeness, text);
        return;
      }
      const turn = { cancel: (): void => undefined };
      waiting.add(turn);
      turn.cancel = afterAssertiveBudget(() => {
        waiting.delete(turn);
        write(politeness, text);
      });
    },
    hush() {
      for (const turn of waiting) turn.cancel();
      waiting.clear();
    },
  };
}
/** An incident's key (BG-05): its symbol and its gap's start; "open" before the gap is on record (C-5309-07). */
const incidentKey = (incident: IncidentBanner): string =>
  `incident:${incident.symbol}:${incident.fromMs ?? "open"}`;

export function RecorderScreen({
  data: dataOptions,
  instruments,
  announcerClock,
}: RecorderScreenProps): JSX.Element {
  const extensions = useRecorderExtensions();
  const data = useRecorderData(dataOptions);
  const names = useInstruments(instruments);
  const [filters, setFilters] = useState<readonly FilterBarFilter[]>([]);
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<GridSort | undefined>(undefined);
  const [adding, setAdding] = useState(false);
  const [retentionOpen, setRetentionOpen] = useState(false);
  /** An add's planning estimate, the Size cell's rate ("est.") until the storage report measures one. */
  const [estimates, setEstimates] = useState<ReadonlyMap<string, number>>(new Map());
  const gapsLanding = useGapLanding();
  // The row detail (D02 §6.7), opened from a row or by `openRowDetail(symbol)`, which this page registers.
  const [detail, setDetail] = useState<string | null>(null);
  const openDetail = useCallback((symbol: string) => setDetail(symbol), []);
  useEffect(() => registerRecorderExtensions({ openRowDetail: openDetail }), [openDetail]);
  const purge = usePurge();
  // A purge's end changes the disk figures: the storage report is read again, once (C-5347-03).
  const { rereadStorage } = data;
  useEffect(() => {
    if (purge.ended) rereadStorage();
  }, [purge.ended, rereadStorage]);
  // The page's own clock, the injected one in tests (C-5309-13), read once at mount.
  const mountedAt = useRef<number | null>(null);
  mountedAt.current ??= (dataOptions?.now ?? Date.now)();
  /** The header's "Record a symbol": where the add returns focus once the empty state's CTA is gone (C-5309-03). */
  const recordId = useId();
  const recordButton = useMemo(
    () => ({
      get current(): HTMLElement | null {
        return document.getElementById(recordId);
      },
    }),
    [recordId],
  );
  /** The H1, readied to take focus: a dialog's or the drawer's last landing when its opener is gone (A-5347-03). */
  const pageHeading = useMemo(
    () => ({
      get current(): HTMLElement | null {
        return asLanding(document.getElementById(RECORDER_H1_ID));
      },
    }),
    [],
  );
  /** The card's Purge data…: where the dialog returns focus when its opener went (the banner's, FM-04), else the H1. */
  const purgeId = useId();
  const purgeFallback = useMemo(
    () => ({
      get current(): HTMLElement | null {
        return document.getElementById(purgeId) ?? pageHeading.current;
      },
    }),
    [purgeId, pageHeading],
  );

  // The story's own key, once per entry (C-z); StrictMode's second run is the same entry.
  const viewed = useRef(false);
  useEffect(() => {
    if (viewed.current) return;
    viewed.current = true;
    reportRecorder({ name: "recorder.screen_viewed" });
  }, []);

  const { view } = data;
  const frame = view.frame;
  const loading = [data.list, data.status, data.storage].some((part) => part.state === "loading");
  const statusFailed = data.list.state === "failed" || data.status.state === "failed";
  const diskFailed = data.storage.state === "failed";
  // The page's clock is the server's (C-5309-11): the newest frame's `ts`, else the status's `generated_at`, the
  // client's read time only when neither is known. While stale it stands, so rows keep their words (§3.1).
  const generatedMs = frame === null ? parseMs(data.status.data?.generated_at) : null;
  const nowMs = view.serverMs ?? generatedMs ?? view.frameAtMs ?? mountedAt.current;
  const policy = frame?.policy ?? data.status.data?.policy ?? null;
  const facts = diskFacts(data.storage.data, frame);
  // A row that has written nothing yet is silent 60 s after the page first saw it (A-5309-08).
  const seen = useRef<ReadonlyMap<string, number>>(new Map());
  seen.current = firstSeen(seen.current, frame, data.status.data, nowMs);
  const rows = buildRows({
    rest: data.list.data ?? [],
    status: data.status.data,
    frame,
    gateClosed: facts.gateClosed,
    nowMs,
    firstSeenMs: seen.current,
  });
  const hasFigures = data.storage.data !== null || frame?.storage !== undefined;
  // The page's history (A-5309-03): the oldest row's start; under an hour, a growth of 0 is too early to call.
  const starts = (data.list.data ?? []).flatMap((row) => parseMs(row.started_at) ?? []);
  const historySinceMs = starts.length === 0 ? null : Math.min(...starts);
  const card = hasFigures
    ? diskCard(facts, policy, rows.length === 0, nowMs, historySinceMs)
    : null;
  const empty = !loading && !statusFailed && rows.length === 0;
  // The detail belongs to the grid: while none is drawn (the empty state, a failed first read), a detail asked for
  // is dropped, so it never opens by itself when rows arrive (C-5347-08).
  const gridShown = !empty && !(statusFailed && rows.length === 0);
  useEffect(() => {
    if (!gridShown && detail !== null) setDetail(null);
  }, [gridShown, detail]);
  const overall = frame?.overall ?? data.status.data?.overall ?? null;

  const measured = new Map(
    (data.storage.data?.symbols ?? []).flatMap((s) =>
      s.symbol === undefined || s.daily_growth_bytes == null
        ? []
        : [[s.symbol, s.daily_growth_bytes]],
    ),
  );
  const gapCounts = new Map<string, number>();
  for (const gap of data.gaps) gapCounts.set(gap.symbol, (gapCounts.get(gap.symbol) ?? 0) + 1);
  const context: RowContext = {
    nowMs,
    stale: view.stale,
    policy,
    diskLevel: facts.level,
    capBytes: facts.capBytes,
    growth: new Map([...estimates, ...measured]),
    estimated: new Set([...estimates.keys()].filter((symbol) => !measured.has(symbol))),
    stoppedAtMs: data.stoppedAtMs,
    gaps: gapCounts,
    accelerated: facts.accelerateRetention,
  };
  const listed = new Map((data.list.data ?? []).map((row) => [row.symbol, row]));

  // RG-10: the 10 s batch of state changes (SR-01, SR-02), a level crossing (F-07) and the turn to stale (SR-15);
  // RG-11: the level-3, incident and failed-purge banners, assertive, once per condition and after a pending batch
  // (BG-05, BG-06). Both through the shell's regions.
  const [{ announcer, voice }] = useState(() => {
    const shell = shellVoice();
    return { voice: shell, announcer: createBatchAnnouncer(shell.say, announcerClock) };
  });
  useEffect(
    () => () => {
      announcer.dispose();
      voice.hush();
      // The page's words go with it: none outlives the page in the shell's regions.
      clearAnnouncements(PAGE_KEYS);
    },
    [announcer, voice],
  );
  // A failed purge is one of the assertive set (BG-05): it joins another alert of its turn and waits behind a
  // pending batch (BG-06), as level 3 and an incident do.
  const failureKey = purge.failure?.key ?? null;
  const failureText = purge.failure?.text ?? null;
  useEffect(() => {
    if (failureKey !== null && failureText !== null) announcer.alert(failureKey, failureText);
  }, [failureKey, failureText, announcer]);
  const latest = useRef({ rows, card, nowMs, policy, stale: view.stale });
  latest.current = { rows, card, nowMs, policy, stale: view.stale };
  const states = useRef<ReadonlyMap<string, RowState> | null>(null);
  const level = useRef<DiskLevel | null>(null);
  const wasStale = useRef(false);
  const changes = `${rows.map((row) => `${row.symbol}:${row.state}`).join(",")}|${card?.level ?? ""}|${view.stale}`;
  useEffect(() => {
    if (loading) return;
    const now = latest.current;
    const phrases = rowChanges(states.current, now.rows, {
      nowMs: now.nowMs,
      maxSymbols: now.policy?.max_symbols ?? null,
    });
    states.current = rowStates(now.rows);
    if (now.card !== null) {
      const crossed = levelChange(level.current, now.card);
      level.current = now.card.level;
      if (crossed !== null) phrases.push(crossed);
    }
    if (now.stale && !wasStale.current) phrases.push(staleLine(now.nowMs));
    wasStale.current = now.stale;
    if (phrases.length > 0) announcer.push(phrases);
  }, [changes, loading, announcer]);

  // F-05 (FM-14): focus goes to the H1 once the reads are back, or once the pressed Retry went with the part it
  // brought back while another still fails (C-5309-05), never `<body>`; a Retry whose part still fails keeps it. It is
  // judged after the commit that drew the reads' answers, when a gone Retry is gone.
  const retried = useRef<{ readonly pressed: Element | null; readonly recovered: boolean } | null>(
    null,
  );
  const [retries, setRetries] = useState(0);
  const retry = (): void => {
    const pressed = document.activeElement;
    void data.retry().then((recovered) => {
      retried.current = { pressed: pressed === document.body ? null : pressed, recovered };
      setRetries((n) => n + 1);
    });
  };
  useLayoutEffect(() => {
    const done = retried.current;
    if (done === null) return;
    retried.current = null;
    const gone = done.pressed !== null && !done.pressed.isConnected;
    if (done.recovered || gone) focusLanding(document.getElementById(RECORDER_H1_ID));
  }, [retries]);
  // A-5347-d03, as F-05 lands: the last row going (an unpin, a stop) swaps the grid for the empty state, and focus
  // that went with the grid's controls lands on the H1, never `<body>`. A page that opens empty moves nothing.
  const hadRows = useRef(false);
  useLayoutEffect(() => {
    if (rows.length > 0) {
      hadRows.current = true;
      return;
    }
    if (!empty || !hadRows.current) return;
    const now = document.activeElement;
    if (now === null || now === document.body)
      focusLanding(document.getElementById(RECORDER_H1_ID));
  }, [rows.length, empty]);
  /** Applies chips for their fields, in place of what those fields held: a value is never ORed with one it replaces. */
  const applyFilters = (more: readonly FilterBarFilter[]): void =>
    setFilters((prev) => [...prev.filter((p) => !more.some((m) => m.field === p.field)), ...more]);
  const suggested = (action: string): void => {
    if (action === SHORTEN) {
      setSort({ columnId: "size", direction: "descending" });
      const largest = [...rows].sort((a, b) => (b.diskBytes ?? 0) - (a.diskBytes ?? 0))[0];
      if (largest !== undefined) extensions.openRowDetail?.(largest.symbol);
    } else if (action === REDUCE) applyFilters(DEEP_FILTERS);
    else if (action === UNPIN) applyFilters([PINNED_FILTER]);
  };
  const extView = {
    status: data.status.data,
    storage: data.storage.data,
    frame,
    stale: view.stale,
  };
  const { RetentionEditor, StoragePanel } = extensions;
  const openRetention = RetentionEditor === undefined ? undefined : () => setRetentionOpen(true);
  const record = (
    <Button id={recordId} variant="primary" iconLeft="plus" onClick={() => setAdding(true)}>
      {DECK["d02.8.r07"][0]}
    </Button>
  );
  const [statusTitle, statusBody] = split(TEXT.statusUnavailable);
  // An incident is the dropped count alone (C-5309-07): its gap's interval joins once the coverage read has it.
  const incidentRow = rows.find((row) => row.droppedMessages > 0 && row.state !== "stopped");
  const incidentGap = data.gaps.find((gap) => gap.symbol === incidentRow?.symbol);
  const incident: IncidentBanner | null =
    incidentRow === undefined
      ? null
      : {
          symbol: incidentRow.symbol,
          dropped: incidentRow.droppedMessages,
          fromMs: incidentGap?.fromMs ?? null,
          toMs: incidentGap?.toMs ?? null,
        };
  const levelThree = facts.level === 3 ? levelThreeBanner(facts, policy) : null;
  // Purge data… (D02 §6.5): the symbols it offers; its line in the card while level 3 or an incident holds the
  // banner slot, and its result there (§3, §3.2).
  const targets = purgeTargets(rows, data.storage.data);
  const purgeAction =
    targets.length === 0
      ? undefined
      : {
          busy: purge.busy,
          open: (symbol?: string) => purge.open(symbol),
          symbols: targets.map((target) => target.symbol),
        };
  const slotTaken = levelThree !== null || incident !== null;
  // "Open {symbol}" only while the purged symbol has a row: the detail closes at once without one (C-5347-d04).
  const purgedSymbol = purge.state?.symbol ?? null;
  const openPurged = rows.some((row) => row.symbol === purgedSymbol) ? openDetail : undefined;
  const purgeInCard =
    purge.state !== null && (slotTaken || purge.state.phase === "succeeded") ? (
      <PurgeView state={purge.state} placement="card" onOpen={openPurged} />
    ) : null;

  // BG-05: each banner is said once per condition key, its words as they were at its entry; a figure that moves later
  // says nothing (BG-04). The key goes when its condition ends, so a new episode is said again. An incident first
  // seen before its gap keeps its key when the gap lands: one incident, said once.
  const levelThreeText = useRef(levelThree);
  levelThreeText.current = levelThree;
  const levelThreeHolds = levelThree !== null;
  useEffect(() => {
    if (!levelThreeHolds) return undefined;
    announcer.alert(LEVEL_3, levelThreeText.current ?? "");
    return () => announcer.release(LEVEL_3);
  }, [levelThreeHolds, announcer]);
  const incidentNow = useRef(incident);
  incidentNow.current = incident;
  const alertedIncident = useRef<string | null>(null);
  const incidentShown = levelThree === null ? incident : null; // level 3 reports the gate's drops (D02 §3)
  const openKey = incidentShown === null ? null : `incident:${incidentShown.symbol}:open`;
  const gapKey = incidentShown === null ? null : incidentKey(incidentShown);
  const incidentId = gapKey !== null && alertedIncident.current === openKey ? openKey : gapKey;
  useEffect(() => {
    if (incidentId === null) return undefined;
    alertedIncident.current = incidentId;
    const now = incidentNow.current;
    if (now !== null) announcer.alert(incidentId, incidentSentence(now));
    return () => {
      announcer.release(incidentId);
      alertedIncident.current = null;
    };
  }, [incidentId, announcer]);
  // No condition left: no alert's words linger in the shell's region for a reading cursor to find.
  useEffect(() => {
    if (levelThreeHolds || incidentId !== null) return;
    clearAnnouncements(PAGE_CHANNELS.assertive);
  }, [levelThreeHolds, incidentId]);

  return (
    <GatedAnnounceProvider announce={sayPolitely}>
      <div style={{ display: "grid", gap: "var(--space-stack-md)", minWidth: 0 }}>
        <PageHeader title={DECK["d02.8.r02"][0]} headingId={RECORDER_H1_ID} actions={record} />
        {policy === null ? (
          loading ? (
            <Skeleton shape="text" count={2} />
          ) : null
        ) : (
          <div style={{ display: "grid", gap: "var(--space-stack-xs)" }}>
            <Text tone="secondary">
              {fill(DECK["d02.8.r03"][0], {
                "{dwell}": formatDuration(policy.autostart_delay_s),
                "{grace}": formatDuration(policy.autostop_grace_s),
              })}
            </Text>
            <Text tone="secondary">{DECK["d02.8.r04"][policy.autorecord_enabled ? 0 : 1]}</Text>
          </div>
        )}
        {statusFailed ? (
          <Callout
            tone="danger"
            live="polite"
            title={statusTitle}
            retry={{ label: TEXT.retry, onClick: retry }}
          >
            {statusBody}
          </Callout>
        ) : null}
        {diskFailed ? (
          <Callout
            tone="danger"
            live="polite"
            title={TEXT.diskUnavailable}
            retry={{ label: TEXT.retry, onClick: retry }}
          />
        ) : null}
        <BannerSlot
          levelThree={levelThree}
          incident={incident}
          purge={purge.state}
          onViewGaps={gapsLanding.land}
          onRetentionPolicy={openRetention}
          onPurge={
            purgeAction === undefined ? undefined : { busy: purge.busy, open: () => purge.open() }
          }
          onOpenSymbol={openPurged}
        />
        <DiskCardPanel
          card={card}
          loading={loading && card === null}
          onSuggested={suggested}
          actions={
            <>
              {openRetention === undefined ? null : (
                <Button variant="secondary" onClick={openRetention}>
                  {PAGE_TEXT.retentionPolicy}
                </Button>
              )}
              {StoragePanel === undefined ? null : (
                <Button
                  variant="secondary"
                  onClick={() => focusLanding(document.getElementById(STORAGE_HEADING_ID))}
                >
                  {PAGE_TEXT.storageDetails}
                </Button>
              )}
              <CompactNow />
              {purgeAction === undefined ? null : (
                <Button
                  id={purgeId}
                  variant="secondary"
                  loading={purge.busy}
                  onClick={() => purge.open()}
                >
                  {DECK["storage.purge.button"][0]}
                </Button>
              )}
            </>
          }
          purgeLine={purgeInCard}
        />
        {loading || statusFailed ? null : (
          <SummaryLine
            line={view.stale ? staleLine(nowMs) : summaryLine(rows, overall)}
            updatedAtMs={view.frameAtMs}
            onAutoReview={() => {
              applyFilters([AUTO_FILTER]);
              reportRecorder({ name: "recorder.auto_review_opened", source: "summary" });
            }}
          />
        )}
        {empty ? (
          <EmptyState
            variant="recording-not-started"
            headingLevel={2}
            title={DECK["d02.8.r05"][0]}
            description={DECK["d02.8.r06"][0]}
            actions={[{ label: DECK["d02.8.r07"][0], onClick: () => setAdding(true) }]}
          />
        ) : statusFailed && rows.length === 0 ? null : (
          <RecorderGrid
            rows={rows}
            context={context}
            listed={listed}
            frameAtMs={view.frameAtMs}
            filters={filters}
            onFiltersChange={setFilters}
            query={query}
            onQueryChange={setQuery}
            sort={sort}
            onSortChange={setSort}
            loading={loading}
            say={sayPolitely}
            onWritten={(write) => {
              if (write.kind === "added" || write.kind === "updated") data.merge(write.row);
              data.rereadList();
            }}
            onOpenDetail={openDetail}
            readBack={data.rereadList}
            fallbackFocusRef={pageHeading}
            detail={detail}
            onDetailClose={() => setDetail(null)}
            frame={frame}
            status={data.status.data}
            gaps={data.gaps}
            onCustomRetention={openRetention}
            purge={purgeAction}
          />
        )}
        <GapTable gaps={data.gaps} nowMs={nowMs} hostRef={gapsLanding.hostRef} />
        {StoragePanel === undefined ? null : (
          <StoragePanel headingId={STORAGE_HEADING_ID} {...extView} />
        )}
        <RecordSymbolDialog
          open={adding}
          onClose={() => setAdding(false)}
          rows={rows}
          policy={policy}
          instruments={names}
          onAdded={(row) => {
            data.merge(row);
            const daily = "estimate" in row ? row.estimate?.daily_bytes_estimate : undefined;
            if (daily !== undefined) setEstimates((prev) => new Map(prev).set(row.symbol, daily));
            data.rereadList();
          }}
          readBack={data.rereadList}
          fallbackFocusRef={recordButton}
        />
        <PurgeDialog
          open={purge.dialogFor !== undefined}
          symbol={purge.dialogFor ?? null}
          symbols={targets}
          onClose={purge.close}
          onStarted={purge.started}
          readBack={data.rereadStorage}
          fallbackFocusRef={purgeFallback}
        />
        {RetentionEditor === undefined ? null : (
          <RetentionEditor
            open={retentionOpen}
            onClose={() => setRetentionOpen(false)}
            {...extView}
          />
        )}
      </div>
    </GatedAnnounceProvider>
  );
}
