import type { CSSProperties, JSX } from "react";
import { Icon, type IconName } from "@candleviewer/ui";
import { formatAge } from "../../lib/ws/state/connectionRegion";

/** The five chip values (E17-D02 §3, CMP-076). Read-only and Resyncing are never chip states. */
export type ConnectionChipStatus = "live" | "delayed" | "stale" | "reconnecting" | "offline";

export interface ConnectionStatusProps {
  readonly status: ConnectionChipStatus;
  /** Epoch ms of the last good data, `null` if none. */
  readonly lastGoodTs: number | null;
  readonly latencyMs?: number | null;
  readonly attempt?: number;
  /** `connecting` before the session's first `auth_ok` (§5, Q1): "Connecting…", no counter. */
  readonly firstConnect?: boolean;
  readonly staleAgeMs?: number;
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

/** The chip word (E17-D02 §10 A). Words without a number are PROPOSED where §10 A has none. */
export function chipWord(p: ConnectionStatusProps): string {
  switch (p.status) {
    case "live":
      return p.latencyMs == null ? "Live" : `Live ${Math.round(p.latencyMs)} ms`;
    case "delayed":
      return p.throttleMultiplier === undefined
        ? "Reduced rate"
        : `Reduced rate ×${p.throttleMultiplier}`;
    case "stale":
      return p.staleAgeMs === undefined ? "Stale" : `Stale ${Math.floor(p.staleAgeMs / 1000)}s`;
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
 * PROPOSED / deferred visuals: `density` (one compact pill for now); hover and focus-ring styling
 * (inline styles have no pseudo-classes: the browser's focus ring shows); the `type.ui.caption` /
 * `.label` token (inherited font); the 20 px pill inside a 24 px target (the pill is the target);
 * the `serverStale` and `upstreamDown` detail states (no source in the shell store).
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
  return (
    <button
      type="button"
      aria-label={name.filter(Boolean).join(", ")}
      title={at === null ? undefined : `last ${at} UTC`}
      data-status={status}
      style={{ ...PILL, background: `var(--color-${fill})` }}
    >
      <span data-glyph="" style={{ color: `var(--color-${ink})`, display: "inline-flex" }}>
        {"icon" in glyph ? (
          <Icon name={glyph.icon} size="sm" />
        ) : (
          <span aria-hidden="true">{glyph.text}</span>
        )}
      </span>
      <span>{word}</span>
      {age === null ? null : <span>· {age}</span>}
    </button>
  );
}
