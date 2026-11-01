import { useLayoutEffect, useRef, type FocusEvent, type JSX, type ReactNode } from "react";
import { Icon } from "../icons/Icon.js";
import type { IconName } from "../icons/registry.js";
import { Button } from "./Button.js";
import { Card } from "./Card.js";
import { Link, type LinkRoute } from "./Link.js";
import { Skeleton } from "./Skeleton.js";

/** The tile's read; `error` and `unavailable` take the down treatment, the octagon (E42-D03 D8). */
export type SystemHealthTileState = "loading" | "ready" | "error" | "unavailable";
/** A ready tile's tone, one glyph shape each: check, triangle, octagon, clock, ring (E42-D05 D2). */
export type SystemHealthTileTone = "ok" | "warning" | "danger" | "stale" | "neutral";
/** The data's environment; for an unknown one the host passes none, so no badge shows. */
export type SystemHealthTileEnv = "live" | "demo" | "testnet";

/** The tile's own words (E42-D03 §14 `tile.*`, E42-D05 §15 `health.*`); every other string is the host's. */
export const SYSTEM_HEALTH_TILE_COPY = {
  error: "Error",
  unavailable: "Unavailable",
  attention: "Attention:",
  notReceived: "not received",
  asOf: "as of",
  lastGood: "last good",
  staleSince: "stale since",
  stillSafe: "Native stops on the exchange are unaffected.",
  runbook: "Runbook",
  retry: "Retry",
  /** PROPOSED: a loading tile's hidden words, never live. */
  loading: "Loading…",
  tone: { ok: "ok", warning: "warning", danger: "down", stale: "stale", neutral: "Not built yet" },
  env: { live: "LIVE", demo: "DEMO", testnet: "TESTNET" },
} as const;
const COPY = SYSTEM_HEALTH_TILE_COPY;

export interface SystemHealthTileProps {
  /** The heading, which is the link to its area: "Users", or "{plain label} ({name})" on SCR-143. */
  readonly label: string;
  readonly href: string;
  /** The app's router link, as CMP-021's `as`; without it, a plain `href`. */
  readonly linkAs?: LinkRoute | undefined;
  readonly headingLevel?: 2 | 3 | 4 | undefined;
  readonly state: SystemHealthTileState;
  /** A ready tile's tone; default `neutral`, never a green the host did not choose. */
  readonly tone?: SystemHealthTileTone | undefined;
  /** The contract's word, verbatim (default: the state's or the tone's), then " — {detail}". */
  readonly stateWord?: string | undefined;
  readonly detail?: string | undefined;
  /** Passed, a value line; `null`, `undefined`, `""` or a non-finite number reads "— not received". */
  readonly value?: number | string | null | undefined;
  /** "probe" before the number; the short unit ("ms") and its words ("milliseconds"). */
  readonly valueLabel?: string | undefined;
  readonly unit?: string | undefined;
  readonly unitSpoken?: string | undefined;
  /** Epoch ms, drawn `hh:mm:ss` UTC: the number's own "as of", then "as of", "last good", "stale since". */
  readonly valueAsOf?: number | undefined;
  readonly asOf?: number | undefined;
  readonly lastGoodAt?: number | undefined;
  readonly staleSince?: number | undefined;
  /** What stops working, the reassurance (the host decides per component), the hint, its runbook. */
  readonly stopsWorking?: string | undefined;
  readonly stillSafe?: boolean | undefined;
  readonly hint?: string | undefined;
  readonly runbookHref?: string | undefined;
  /**
   * Retry, last; kept while loading, busy, so a pressed Retry keeps focus. The host drops it after
   * a good read: a Retry that held focus then hands it to the heading link, as any line does.
   */
  readonly onRetry?: (() => void) | undefined;
  readonly env?: SystemHealthTileEnv | undefined;
  /** The host's lines after the value: CMP-036 rows, a CMP-023 meter, CMP-173 rows. */
  readonly children?: ReactNode;
}

const GLYPH: Readonly<Record<Exclude<SystemHealthTileTone, "neutral">, IconName>> = {
  ok: "check",
  warning: "warning",
  danger: "danger",
  stale: "pending",
};

/** `hh:mm:ss` in UTC (admin times are UTC, E42-D03 §1), or null for no real time. */
function utc(ms: number | undefined): string | null {
  if (ms === undefined || !Number.isFinite(ms)) return null;
  const s = ((Math.floor(ms / 1000) % 86_400) + 86_400) % 86_400;
  const two = (n: number): string => String(n).padStart(2, "0");
  return `${two(Math.floor(s / 3600))}:${two(Math.floor(s / 60) % 60)}:${two(s % 60)}`;
}

/** A value line: never a number for a value not received (E42-D03 D4). */
function Value(props: SystemHealthTileProps): JSX.Element {
  const { value, valueLabel, unit, unitSpoken } = props;
  const received =
    typeof value === "number" ? Number.isFinite(value) : typeof value === "string" && value !== "";
  const at = utc(props.valueAsOf);
  return (
    <p className="cv-health-tile__value">
      {received ? (
        <>
          {valueLabel === undefined ? null : `${valueLabel} `}
          <span className="cv-health-tile__number">{String(value)}</span>
          {unit === undefined ? null : " "}
          <span aria-hidden={unitSpoken === undefined ? undefined : true}>{unit}</span>
          {unitSpoken === undefined ? null : (
            <span className="cv-visually-hidden">{unitSpoken}</span>
          )}
          {at === null ? null : ` · ${COPY.asOf} ${at}`}
        </>
      ) : (
        <>
          <span aria-hidden="true">—</span> {COPY.notReceived}
        </>
      )}
    </p>
  );
}

/** Every part after the heading, in reading order, once the read answered. */
function Lines(
  props: SystemHealthTileProps & { readonly look: SystemHealthTileTone },
): JSX.Element {
  const { state, look, stopsWorking, hint, runbookHref } = props;
  const stale = utc(props.staleSince);
  const word =
    props.stateWord ??
    (state === "error" || state === "unavailable"
      ? COPY[state]
      : look === "stale" && stale !== null
        ? `${COPY.staleSince} ${stale}`
        : COPY.tone[look]);
  const last = utc(props.lastGoodAt);
  const at = utc(props.asOf);
  // E42-D03 board 09 (Warning): "last good" over what stops working, "as of" the last line.
  return (
    <>
      <p className="cv-health-tile__state">
        <span className="cv-health-tile__glyph" data-tone={look} aria-hidden="true">
          {look === "neutral" ? (
            <span className="cv-health-tile__ring" />
          ) : (
            <Icon name={GLYPH[look]} />
          )}
        </span>
        <span>
          {look === "warning" ? (
            <span className="cv-visually-hidden">{`${COPY.attention} `}</span>
          ) : null}
          {[word, props.detail].filter(Boolean).join(" — ")}
        </span>
      </p>
      {"value" in props ? <Value {...props} /> : null}
      {props.children}
      {last === null ? null : <p className="cv-health-tile__meta">{`${COPY.lastGood} ${last}`}</p>}
      {stopsWorking ? <p>{stopsWorking}</p> : null}
      {props.stillSafe === true ? <p>{COPY.stillSafe}</p> : null}
      {hint ? <p className="cv-health-tile__hint">{hint}</p> : null}
      {runbookHref ? (
        <p>
          <Link href={runbookHref}>
            {COPY.runbook}
            <span aria-hidden="true"> →</span>
          </Link>
        </p>
      ) : null}
      {at === null ? null : <p className="cv-health-tile__meta">{`${COPY.asOf} ${at}`}</p>}
    </>
  );
}

/** Retry: busy while loading, never disabled, so a pressed Retry keeps focus through the read. */
function Retry(props: { readonly loading: boolean; readonly onRetry: () => void }): JSX.Element {
  return (
    <div className="cv-health-tile__retry">
      <Button loading={props.loading} onClick={props.onRetry}>
        {COPY.retry}
      </Button>
    </div>
  );
}

/**
 * CMP-178 SystemHealthTile: a CMP-050 region tile of SCR-120 and SCR-143, named by its heading, which is its
 * CMP-021 link. Each read resolves on its own: the skeleton, then the word with one glyph shape per tone and
 * no number for a value not received. No live region (the shell announces a transition once), no sparkline.
 */
export function SystemHealthTile(props: SystemHealthTileProps): JSX.Element {
  const { label, href, linkAs, headingLevel = 3, state, tone = "neutral", env, onRetry } = props;
  const loading = state === "loading";
  const busy = loading || undefined;
  const look = state === "error" || state === "unavailable" ? "danger" : tone;
  const tile = useRef<HTMLDivElement>(null);
  // The element holding focus inside the tile, from focus landing there until focus leaves it.
  const held = useRef<Element | null>(null);
  // After each commit: whatever held focus and a re-render took out (a Retry a good read dropped,
  // a host row a re-read replaced, a link whose condition cleared) hands it to the heading link,
  // never to <body> (A-5330-02). Focus moved elsewhere on purpose is never taken back.
  useLayoutEffect(() => {
    const node = held.current;
    if (node === null || node.isConnected) return;
    held.current = null;
    const active = document.activeElement;
    if (active !== null && active !== document.body) return;
    tile.current?.querySelector<HTMLElement>(`h${headingLevel} a`)?.focus();
  });
  const onFocus = (event: FocusEvent<HTMLDivElement>): void => {
    held.current = event.target;
  };
  const onBlur = (event: FocusEvent<HTMLDivElement>): void => {
    const next = event.relatedTarget;
    if (next !== null) {
      if (!event.currentTarget.contains(next)) held.current = null;
      return;
    }
    // Focus went nowhere: a press on the page, or the element is being taken out. Once this event
    // is over, an element still in the document and no longer focused was left on purpose.
    const node = event.target;
    queueMicrotask(() => {
      if (held.current === node && node.isConnected && document.activeElement !== node) {
        held.current = null;
      }
    });
  };
  const title = (
    <>
      {linkAs === undefined ? (
        <Link href={href}>{label}</Link>
      ) : (
        <Link to={href} as={linkAs}>
          {label}
        </Link>
      )}
      {env === undefined ? null : " "}
      {env === undefined ? null : (
        <span className={`cv-health-tile__env cv-health-tile__env--${env}`}>{COPY.env[env]}</span>
      )}
    </>
  );
  return (
    <div
      ref={tile}
      className="cv-health-tile"
      data-cmp="CMP-178"
      data-state={state}
      aria-busy={busy}
      onFocus={onFocus}
      onBlur={onBlur}
    >
      <Card region title={title} headingLevel={headingLevel}>
        <div className="cv-health-tile__body">
          {loading ? <Skeleton /> : <Lines {...props} look={look} />}
          {loading ? (
            <span className="cv-health-tile__loading cv-visually-hidden">{COPY.loading}</span>
          ) : null}
          {onRetry === undefined ? null : <Retry loading={loading} onRetry={onRetry} />}
        </div>
      </Card>
    </div>
  );
}
