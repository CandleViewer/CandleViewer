import { useEffect, useRef, useState, type CSSProperties, type JSX } from "react";
import { Link, useInRouterContext } from "react-router";
import { Icon, IconButton } from "@candleviewer/ui";
import { announce } from "../app-shell/announcer";
import type { WsState } from "../../lib/ws/state/types";
import type { PositionsApi } from "../positions/api";
import { positionsApi } from "../positions/api";
import { shellAccountSignals, useShellAccountSignals } from "../../shell/accountState";
import { useShellSelector } from "../../shell/useShellSelector.js";
import { getActiveClient } from "../../lib/ws/client/activeClient";
import { reconciliationReads, type ReconciliationDigest, type ReconciliationReads } from "./digest";
import { MAX_WATCHED, watchPositionDeltas } from "./positionsWatch";
import {
  clearReassurance,
  dropReassurance,
  readReassurance,
  streamReady,
  touchReassurance,
} from "./reassurance";
import {
  buildSummary,
  type RecoveredSummary,
  type Segment,
  type SummaryAccount,
} from "./summaryModel";

const BOX: CSSProperties = {
  display: "flex",
  flexWrap: "wrap",
  alignItems: "flex-start",
  gap: "var(--space-inset-sm)",
  padding: "var(--space-inset-sm)",
  borderLeft: "calc(var(--border-thick) * 1px) solid var(--color-status-success-strong)",
  background: "var(--color-status-success-subtle)",
  boxShadow: "var(--elevation-chrome)",
  color: "var(--color-text-primary)",
  fontVariantNumeric: "tabular-nums",
};
const P: CSSProperties = { margin: 0 };

const LINK: CSSProperties = { color: "var(--color-text-link)" };

/** A line of segments; a link is the router's inside one, a plain anchor outside (a bare shell). */
function Line({
  segments,
  style,
}: {
  segments: readonly Segment[];
  style?: CSSProperties;
}): JSX.Element {
  const routed = useInRouterContext();
  return (
    <p style={{ ...P, ...style }}>
      {segments.map((s, i) =>
        s.href === undefined ? (
          <span key={i}>{s.text}</span>
        ) : routed ? (
          <Link key={i} to={s.href} style={LINK}>
            {s.text}
          </Link>
        ) : (
          <a key={i} href={s.href} style={LINK}>
            {s.text}
          </a>
        ),
      )}
    </p>
  );
}

const TABBABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

/**
 * FM-24: the slot's next Tab stop after `region` in document order; past the last one, the
 * workspace's `main` landmark (made focusable for the move only), so focus never drops to `body`.
 */
export function nextStopAfter(region: HTMLElement): HTMLElement | null {
  const all = [...document.querySelectorAll<HTMLElement>(TABBABLE)];
  return (
    all.find(
      (el) =>
        !region.contains(el) &&
        (region.compareDocumentPosition(el) & Node.DOCUMENT_POSITION_FOLLOWING) !== 0,
    ) ?? mainLandmark()
  );
}

function mainLandmark(): HTMLElement | null {
  const main = document.querySelector<HTMLElement>("main");
  if (main === null) return null;
  if (!main.hasAttribute("tabindex")) {
    main.setAttribute("tabindex", "-1");
    main.addEventListener("blur", () => main.removeAttribute("tabindex"), { once: true });
  }
  return main;
}

export interface RecoveredRegionProps {
  readonly summary: RecoveredSummary;
  readonly onDismiss: () => void;
}

/**
 * SCR-152's `recovered` region (E17-D02 §6 and §10 B7; E08-D03 §3; E29-D03 §4.6; E08-D14 DF-17),
 * CMP-077's success state: "Reconnected", the while-you-were-offline lines with their links, and
 * Dismiss (an icon button, top-right; `Esc` inside the region). A `region` named "Connection", as
 * every CMP-077 state: no focus trap, and it owns no live region (SR-03 is said through the shell
 * announcer, once). It is never auto-hidden (held ≥ 10 s and until dismissed, E08-D11 D3).
 * **FM-24:** dismissing from inside the region returns focus to the slot's next Tab stop (the
 * `main` landmark when there is none), as the dismissing control leaves with the region; focus
 * elsewhere stays where it is.
 */
export function RecoveredRegion({ summary, onDismiss }: RecoveredRegionProps): JSX.Element {
  const ref = useRef<HTMLElement>(null);
  const dismissRef = useRef<() => void>(() => undefined);
  const dismiss = (): void => {
    const region = ref.current;
    const inside = region !== null && region.contains(document.activeElement);
    const next = inside && region !== null ? nextStopAfter(region) : null;
    onDismiss();
    next?.focus();
  };
  dismissRef.current = dismiss;
  // `Esc` inside the region dismisses it (E17-D02 §13 "Esc innermost-cancel"); a listener on the
  // region, not a handler prop, as a `section` is no control of its own.
  useEffect(() => {
    const region = ref.current;
    if (region === null) return undefined;
    const onKey = (e: KeyboardEvent): void => {
      if (e.key !== "Escape") return;
      e.stopPropagation();
      dismissRef.current();
    };
    region.addEventListener("keydown", onKey);
    return () => region.removeEventListener("keydown", onKey);
  }, []);
  return (
    <section ref={ref} aria-label="Connection" data-state="recovered" style={BOX}>
      <span style={{ display: "inline-flex", color: "var(--color-status-success-strong)" }}>
        <Icon name="success" size="md" />
      </span>
      <div style={{ flex: "1 1 12em", minWidth: 0 }}>
        <p style={{ ...P, fontWeight: 600 }}>{summary.title}</p>
        {summary.body === null ? null : <Line segments={summary.body} />}
        {summary.line2 === null ? null : (
          <Line segments={summary.line2} style={{ color: "var(--color-text-secondary)" }} />
        )}
      </div>
      <IconButton icon="close" label="Dismiss" variant="ghost" onClick={dismiss} />
    </section>
  );
}

/** The `Me.accounts` entries the summary may name (the session's own; SR-E29-10). */
type MeAccounts = readonly {
  readonly exchange_account_id: string;
  readonly label?: string;
  readonly environment?: string;
}[];

export const summaryAccounts = (accounts: MeAccounts | undefined): SummaryAccount[] =>
  (accounts ?? []).map((a) => ({
    id: a.exchange_account_id.toLowerCase(),
    label: a.label ?? "Account",
    env: (a.environment ?? "").toUpperCase(),
  }));

export interface RecoveredRegionSlotProps {
  readonly ws: WsState;
  /** SCR-153 row 9's hand-over: the private feed is down, so the snapshots are not in. */
  readonly privateFeedDown: boolean;
  /** Whether the region may show: the slot holds no other CMP-077 state. */
  readonly visible: boolean;
  readonly reads?: ReconciliationReads;
  /** The reassurance gate's read (`listPositions`), injectable for tests. */
  readonly positions?: Pick<PositionsApi, "listPositions">;
  /** The reassurance drop's watch of the `positions` topic, injectable for tests. */
  readonly watch?: (
    ids: readonly string[],
    onMoved: (id: string) => void,
    onTouched: (id: string) => void,
  ) => () => void;
  readonly now?: () => number;
}

/** The live client's `positions` deltas; nothing to watch without a client. */
const watchLive = (
  ids: readonly string[],
  onMoved: (id: string) => void,
  onTouched: (id: string) => void,
): (() => void) => {
  const client = getActiveClient();
  return client === null
    ? () => undefined
    : watchPositionDeltas(client, ids, onMoved, undefined, onTouched);
};

interface Episode {
  readonly fromMs: number;
}

/**
 * The `recovered` container: kept mounted beside CMP-077's other states so it sees the outage
 * begin, then, once the link is up and the `system` stream and the private snapshots are in
 * (E17-D01:226), reads each account's digest and the window's fills, builds the summary and says
 * SR-03 ("Reconnected. …", assertive) once per episode exit. A new outage drops the summary.
 * It also follows the client's kill switch into the shell's account states (E29-D03 §4.1), and
 * runs the reassurance gate's REST read (`reassurance.ts`) at each connect and reconnect, the last
 * verdicts dropped first, and for an account when its lock begins.
 */
export function RecoveredRegionSlot({
  ws,
  privateFeedDown,
  visible,
  reads = reconciliationReads,
  positions = positionsApi,
  watch = watchLive,
  now = Date.now,
}: RecoveredRegionSlotProps): JSX.Element | null {
  const accounts = useShellSelector((s) => s.me?.accounts);
  const pending = useRef<Episode | null>(null);
  const [summary, setSummary] = useState<RecoveredSummary | null>(null);
  const announced = useRef(true);
  const episodeKey = useRef("");

  useEffect(() => {
    shellAccountSignals.setKillSwitch(ws.killSwitch, null);
  }, [ws.killSwitch]);

  const ready = streamReady(ws, privateFeedDown);
  const linkUp = ws.link.kind === "up";

  // The reassurance gate (BQ-7 ruled, BQ-11): the last verdicts are dropped at each connect, and
  // each positions delta drops its account's verdict until the next read (review fold M1). The
  // watch runs for as long as the link is up, not only while `ready`: a resync or a stale baseline
  // that makes `ready` false must not leave verdicts no delta can drop. It stops with the link:
  // the verdicts then stand as the last read (nothing arrives to move them), and the stop applies
  // the frames still buffered first. Only the accounts one consumer can watch are read: past
  // `MAX_WATCHED` they stay unread.
  const scopeKey = (accounts ?? [])
    .slice(0, MAX_WATCHED)
    .map((a) => a.exchange_account_id.toLowerCase())
    .join(",");
  useEffect(() => {
    if (!linkUp) return undefined;
    clearReassurance();
    if (scopeKey === "") return undefined;
    return watch(scopeKey.split(","), dropReassurance, touchReassurance);
  }, [linkUp, scopeKey, watch]);
  // Nothing watches after unmount: a verdict held then could never be dropped.
  useEffect(() => clearReassurance, []);
  // The read at each connect and reconnect, once the stream is ready (the watch is already up).
  useEffect(() => {
    if (!ready || scopeKey === "") return undefined;
    const abort = new AbortController();
    void readReassurance(scopeKey.split(","), positions, abort.signal);
    return () => abort.abort();
  }, [ready, scopeKey, positions]);

  // A lock's start re-reads its account (BQ-11 (a)), once per episode: only an account the watch
  // covers, and only while it runs, so a verdict read here can always be dropped by a delta.
  const lockEpisodes = useShellAccountSignals((s) => s.accounts);
  const readLocks = useRef(new Set<number>());
  useEffect(() => {
    const watched = new Set(scopeKey === "" ? [] : scopeKey.split(","));
    const fresh: string[] = [];
    const held = new Set<number>();
    for (const [id, signal] of lockEpisodes) {
      const oms = signal.oms;
      if (oms?.state !== "stale") continue;
      held.add(oms.episode);
      if (readLocks.current.has(oms.episode)) continue;
      if (linkUp && watched.has(id)) fresh.push(id);
    }
    readLocks.current = held; // bounded by the store's accounts (L5)
    // Not aborted on a later change: an episode is read once, and its verdict lands in the store.
    if (fresh.length > 0) void readReassurance(fresh, positions);
  }, [lockEpisodes, positions, linkUp, scopeKey]);

  useEffect(() => {
    if (ws.outage === null) return;
    pending.current ??= { fromMs: ws.outage.sinceMs }; // the episode's start, kept past `auth_ok`
    setSummary(null); // the Disconnected region takes the slot
  }, [ws.outage]);

  useEffect(() => {
    const episode = pending.current;
    if (!ready || episode === null) return undefined;
    pending.current = null;
    const window = { fromMs: episode.fromMs, toMs: now() };
    const scope = summaryAccounts(accounts);
    const abort = new AbortController();
    let done = false;
    void (async () => {
      const digests = new Map<string, ReconciliationDigest>();
      for (const account of scope) {
        const got = await reads.getDigest(account.id, abort.signal);
        if (got.kind === "ok") digests.set(account.id, got.digest);
      }
      const ids = scope.map((a) => a.id);
      const fills = await reads.offlineFills(ids, window, abort.signal);
      if (abort.signal.aborted) return;
      done = true;
      setSummary(buildSummary({ window, accounts: scope, digests, fills }));
      announced.current = false;
      episodeKey.current = `reconciliation:recovered:${window.fromMs}`;
    })();
    return () => {
      abort.abort();
      if (!done) pending.current ??= episode; // an interrupted read is retried, never lost
    };
  }, [ready, accounts, reads, now]);

  // SR-03 is said once, and only once the region shows (a11y m2): a summary held behind another
  // CMP-077 state is said when the slot is its again.
  useEffect(() => {
    if (!visible || summary === null || announced.current) return;
    announced.current = true;
    announce("assertive", summary.announce, episodeKey.current);
  }, [visible, summary]);

  if (!visible || summary === null) return null;
  return <RecoveredRegion summary={summary} onDismiss={() => setSummary(null)} />;
}
