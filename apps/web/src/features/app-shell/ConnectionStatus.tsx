import { useLayoutEffect, useRef, useState, type CSSProperties, type JSX } from "react";
import { Icon, useFocusRing, type IconName } from "@candleviewer/ui";
import type { ChipStatus } from "../../lib/ws/state/connectionPresentation";
import { formatAge } from "../../lib/ws/state/connectionRegion";
import { useReducedMotion } from "./motion";

/** The five chip values (E17-D02 §3, CMP-076). Read-only and Resyncing are never chip states. */
export type ConnectionChipStatus = ChipStatus;

export interface ConnectionStatusProps {
  readonly status: ConnectionChipStatus;
  /** Epoch ms of the last good data, `null` if none. */
  readonly lastGoodTs: number | null;
  readonly latencyMs?: number | null;
  readonly attempt?: number;
  /** `connecting` before the session's first `auth_ok` (§5, Q1): "Connecting…", no counter. */
  readonly firstConnect?: boolean;
  readonly staleAgeMs?: number;
  /** §2 row 12: `meta.stale` on a ticker or book: "Stale (server)". */
  readonly serverStale?: boolean;
  /** §2 row 13: the exchange's public feed is down: "Stale — exchange feed down". */
  readonly upstreamDown?: boolean;
  readonly strong?: boolean;
  readonly throttleMultiplier?: number;
  /** The clock for the age; the container ticks it at 1 Hz while disconnected. */
  readonly nowMs: number;
}

type Glyph = { readonly icon: IconName } | { readonly text: string };
/**
 * Glyph, fill and glyph ink per state (E17-D02 §5): ✓ live, ◐ delayed, ⚠ stale (strong at T2),
 * ↻ reconnecting, ✕ offline; the word is always `color.text.primary`. The CMP-019 registry has no
 * half-circle or refresh glyph, so those two are text glyphs (PROPOSED).
 */
const LOOK: Record<ConnectionChipStatus | "strong", readonly [Glyph, string, string]> = {
  live: [{ icon: "check" }, "surface-raised", "data-confidence-live-indicator"],
  delayed: [{ text: "◐" }, "status-info-subtle", "status-info-default"],
  stale: [{ icon: "warning" }, "surface-raised", "data-confidence-stale-indicator"],
  strong: [{ icon: "warning" }, "status-warning-subtle", "status-warning-strong"],
  reconnecting: [{ text: "↻" }, "status-danger-subtle", "status-danger-strong"],
  offline: [{ icon: "close" }, "status-danger-subtle", "status-danger-strong"],
};

/**
 * The chip word (E17-D02 §10 A). Words without a number are PROPOSED where §10 A has none. The age
 * reads "Stale 7 s" (#5345, as §10 C and §11 space it): §10 A's "Stale 7s" is not part of its own
 * name "Stale 7 seconds", which SC 2.5.3 (Label in Name) needs; "7 s" is.
 */
export function chipWord(p: ConnectionStatusProps): string {
  switch (p.status) {
    case "live":
      return p.latencyMs == null ? "Live" : `Live ${Math.round(p.latencyMs)} ms`;
    case "delayed":
      return p.throttleMultiplier === undefined
        ? "Reduced rate"
        : `Reduced rate ×${p.throttleMultiplier}`;
    case "stale":
      if (p.upstreamDown === true) return "Stale — exchange feed down";
      if (p.serverStale === true) return "Stale (server)";
      return p.staleAgeMs === undefined ? "Stale" : `Stale ${Math.floor(p.staleAgeMs / 1000)} s`;
    case "reconnecting":
      if (p.firstConnect === true) return "Connecting…";
      return p.attempt === undefined ? "Reconnecting" : `Reconnecting (${p.attempt})`;
    case "offline":
      return "Offline — retry stopped";
  }
}

/** "13:42:05", UTC. */
const utc = (ms: number): string => new Date(ms).toISOString().slice(11, 19);

const PILL: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: "var(--space-inset-xs)",
  height: "var(--size-control-compact)",
  minHeight: "var(--size-target-min)",
  padding: "0 var(--space-inset-sm)",
  borderRadius: "var(--radius-badge)",
  border: "calc(var(--border-hairline) * 1px) solid var(--color-border-default)",
  color: "var(--color-text-primary)",
  font: "inherit",
  fontVariantNumeric: "tabular-nums",
};

/** E04-D01 :205–210: a 200 ms opacity cross-fade, once per transition; instant under reduce. */
const FADE_BOX: CSSProperties = { display: "inline-flex", alignItems: "center", gap: "inherit" };
const FADE = "opacity var(--motion-duration-normal) cubic-bezier(var(--motion-easing-standard))";

/**
 * The chip's content fades in once per status change (#304 S10, BQ-10): the new state is drawn at
 * opacity 0 with no transition, and the next frame fades it in. The first render and every render
 * under reduced motion draw it at once, with `transition: none`.
 */
function useCrossFade(status: ConnectionChipStatus): CSSProperties {
  const reduce = useReducedMotion();
  const last = useRef(status);
  const [hidden, setHidden] = useState(false);
  useLayoutEffect(() => {
    if (last.current === status) return undefined;
    last.current = status;
    if (reduce) return undefined;
    setHidden(true);
    const id = requestAnimationFrame(() => setHidden(false));
    return () => {
      cancelAnimationFrame(id);
      setHidden(false);
    };
  }, [status, reduce]);
  if (reduce) return { ...FADE_BOX, transition: "none" };
  return {
    ...FADE_BOX,
    opacity: hidden ? 0 : 1,
    transition: hidden ? "none" : FADE,
  };
}

/**
 * CMP-076 ConnectionStatus (#304 S3; E17-D02 §5): props only; glyph + word + fill, never colour
 * alone; **owns no live region** (§11: the shell announcer does).
 *
 * Deferred: the details popover (a later #304 slice, once the `connection_quality` numbers reach
 * the client) and the tooltip (CMP-016 Tooltip, E05-S02 #265); until then the UTC time is in the
 * name and a `title`, and there is no `aria-haspopup`. It stays the merged spec's native `<button>`
 * with no action yet: a Tab stop keeps the name and time reachable from the keyboard, and the
 * popover slice adds the action without changing the Tab order.
 *
 * Focus is the CMP-039 ring (`useFocusRing()`, #304 S10, BQ-05). The hairline border is decoration:
 * the word and the glyph identify the control (SC 1.4.11 needs no 3:1 boundary; BQ-04, pending the
 * E47-T01 re-audit). The content cross-fades on a status change (BQ-10).
 *
 * PROPOSED / deferred visuals: `density` (one compact pill for now); hover styling; the `type.ui.caption` /
 * `.label` token (inherited font); the 20 px pill inside a 24 px target (the pill is the target).
 */
export function ConnectionStatus(props: ConnectionStatusProps): JSX.Element {
  const { status, lastGoodTs, nowMs } = props;
  const word = chipWord(props);
  const disconnected = status === "reconnecting" || status === "offline";
  // PROPOSED: the last-data age beside a disconnected word, as the region's L1 names it (§10 B).
  const age =
    disconnected && lastGoodTs !== null ? `last data ${formatAge(nowMs - lastGoodTs)} ago` : null;
  const at = lastGoodTs === null ? null : utc(lastGoodTs);
  // SC 2.5.3: the visible words lead; "last data" is said once ("…, last data 00:12 ago, 13:42:05 UTC").
  const time = at === null ? null : age === null ? `last data ${at} UTC` : `${at} UTC`;
  const name = [`Connection: ${word}`, age, time];
  const [glyph, fill, ink] = LOOK[status === "stale" && props.strong === true ? "strong" : status];
  const ring = useFocusRing();
  const fade = useCrossFade(status);
  return (
    <button
      type="button"
      className={ring.className}
      aria-label={name.filter(Boolean).join(", ")}
      title={at === null ? undefined : `last ${at} UTC`}
      data-status={status}
      style={{ ...PILL, background: `var(--color-${fill})` }}
    >
      <span data-fade="" style={fade}>
        <span data-glyph="" style={{ color: `var(--color-${ink})`, display: "inline-flex" }}>
          {"icon" in glyph ? (
            <Icon name={glyph.icon} size="sm" />
          ) : (
            <span aria-hidden="true">{glyph.text}</span>
          )}
        </span>
        <span>{word}</span>
        {age === null ? null : <span>· {age}</span>}
      </span>
    </button>
  );
}
