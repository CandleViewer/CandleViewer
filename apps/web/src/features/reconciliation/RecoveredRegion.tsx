import { useEffect, useRef, useState, type CSSProperties, type JSX } from "react";
import { Link, useInRouterContext } from "react-router";
import { Icon, IconButton } from "@candleviewer/ui";
import { announce } from "../app-shell/announcer";
import type { WsState } from "../../lib/ws/state/types";
import { shellAccountSignals } from "../../shell/accountState";
import { useShellSelector } from "../../shell/useShellSelector.js";
import { reconciliationReads, type ReconciliationDigest, type ReconciliationReads } from "./digest";
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
  readonly now?: () => number;
}

interface Episode {
  readonly fromMs: number;
}

/**
 * The `recovered` container: kept mounted beside CMP-077's other states so it sees the outage
 * begin, then, once the link is up and the `system` stream and the private snapshots are in
 * (E17-D01:226), reads each account's digest and the window's fills, builds the summary and says
 * SR-03 ("Reconnected. …", assertive) once per episode exit. A new outage drops the summary.
 * It also follows the client's kill switch into the shell's account states (E29-D03 §4.1).
 */
export function RecoveredRegionSlot({
  ws,
  privateFeedDown,
  visible,
  reads = reconciliationReads,
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

  const ready =
    ws.link.kind === "up" && ws.outage === null && ws.systemStream === "live" && !privateFeedDown;

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
