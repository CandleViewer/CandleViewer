import type { JSX, ReactNode } from "react";
import { Icon } from "../icons/Icon.js";
import { FreshnessMarker } from "./FreshnessMarker.js";

/** CMP-078's five states (E17-D02 §7 Props; `15` CMP-078). */
export type StaleDataShadeState = "fresh" | "stale" | "escalated" | "stale-server" | "disconnected";

const pad = (n: number): string => String(n).padStart(2, "0");
const finite = (ms: number): number => (Number.isFinite(ms) ? Math.max(0, ms) : 0);

/** "14:02:11": an epoch-ms instant as UTC wall time (the deck's "as of {time} UTC"). */
function utcTime(epochMs: number): string {
  const d = new Date(finite(epochMs));
  return `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}:${pad(d.getUTCSeconds())}`;
}

/** "as of 14:02:11 UTC": the end of a stale row's description (E29-D03 §4.4; D04 `CMP-114/row-stale`). */
export function staleAsOf(updatedAtMs: number): string {
  return `as of ${utcTime(updatedAtMs)} UTC`;
}

/** "00:12": the age of the last data, as the Disconnected label draws it (E17-D02 §7). */
function mmss(ms: number): string {
  const total = Math.floor(finite(ms) / 1000);
  return `${pad(Math.floor(total / 60))}:${pad(total % 60)}`;
}

/**
 * The grid-row variant (`15` CMP-078 "grid row: de-emphasised in place, never re-sorted"): a class swap on the row,
 * no node of its own, as CMP-239's cell marker; the row's description carries `staleAsOf`. `fresh` adds nothing.
 */
export function staleDataRowClassName(state: StaleDataShadeState): string | undefined {
  return state === "fresh" ? undefined : `cv-stale-row cv-stale-row--${state}`;
}

export interface StaleDataShadeProps {
  readonly state: StaleDataShadeState;
  /** The id of the text node: the host's region names it in `aria-describedby` (E08-D03 §5). */
  readonly id: string;
  /** The age of the last good value (stale, escalated, disconnected); absent means no age is drawn or read. */
  readonly ageMs?: number;
  /** The last good value's time, epoch ms: the account-scope line's "as of" (E29-D03 §4.4). */
  readonly lastGoodTs?: number;
  /** `stale-server`: the baseline `snap`'s `ts` ("Stale (server) — since 14:02:11"). */
  readonly sinceTs?: number;
  /** `escalated`: the header strip's sentence, "Stale 15 s — new orders blocked on BTCUSDT" (the host's words). */
  readonly strip?: string;
  /** Replaces the state's own line, drawn and read the same ("Resyncing book…", an account-scope line). */
  readonly label?: string;
  /** The shaded panel or grid: kept mounted in every state, so a state change never moves focus. */
  readonly children: ReactNode;
}

/** The state's line, as E17-D02 §7 words it; `null` for `fresh`. */
function lineOf(props: StaleDataShadeProps): string | null {
  const custom = props.label?.trim();
  if (props.state === "fresh") return null;
  if (custom !== undefined && custom !== "") return custom;
  const age = props.ageMs;
  switch (props.state) {
    case "stale":
    case "escalated":
      // No age given is no age drawn: never a fabricated 0 (C-2.12).
      if (props.lastGoodTs !== undefined) return `Not up to date · ${staleAsOf(props.lastGoodTs)}`;
      return age === undefined ? "Not up to date" : `Last update ${Math.floor(finite(age) / 1000)} s ago`;
    case "stale-server":
      return props.sinceTs === undefined
        ? "Stale (server)"
        : `Stale (server) — since ${utcTime(props.sinceTs)}`;
    case "disconnected":
      return age === undefined ? "Disconnected" : `Disconnected — last data ${mmss(age)}`;
  }
}

/**
 * CMP-078 StaleDataShade (E17-D02 §7; `15` CMP-078; the account scope of E29-D03 §4.4 and E29-D04 §2.8.2): the
 * panel keeps its last values under a dim (stale, escalated) or a scrim (disconnected), with the state's words
 * above it at full opacity. Colour is never the signal: the words carry it.
 *
 * - **A11y.** The dim is `aria-hidden`; the line is a plain node whose `id` the host's region names in
 *   `aria-describedby`, so the panel reads "Stale, last update 7 seconds ago" with no per-cell announcement. It owns
 *   no live region (the host announces once per episode, E17-D02 §11) and never moves focus, takes no focus and is
 *   never `inert`: a block is the host's T2 (CMP-079), not this shade's.
 * - **Fresh** adds no class, no dim and no line; the wrapper stays so the panel is never remounted (focus kept).
 * - **Tokens.** The dim is `color.data-confidence.stale.surface` composited at 0.15 — the `color.overlay.stale`
 *   alias `15` names does not exist and is PROPOSED to E05 (E17-D02 §14.4 CR-1; E29-D04 DR-5); the scrim is
 *   `color.surface.overlay` at `opacity.scrim` (CR-2). The settle (E08-D11 D11) is a flip here: no motion.
 * - **Never over an exit (C-2.6).** The `disconnected` scrim takes the pointer: never wrap the positions grid,
 *   an orders grid or any cancel, close or stop control with it (E17-D01 A1: the grid stays uncovered). Rows use
 *   the grid-row variant (`staleDataRowClassName`), which takes nothing.
 * - **The escalated strip** leads with the CMP-019 warning glyph (E17-D02 §7's ⚠), decorative: the sentence
 *   carries the meaning.
 */
export function StaleDataShade(props: StaleDataShadeProps): JSX.Element {
  const { state, id, children } = props;
  const line = lineOf(props);
  const fresh = state === "fresh";
  const age = props.ageMs;
  // The chip (CMP-239) carries an age: with none given there is no chip, never a "Stale 0s".
  const chip = (state === "stale" || state === "escalated") && age !== undefined;
  return (
    <div
      className={fresh ? "cv-stale-shade" : `cv-stale-shade cv-stale-shade--${state}`}
      data-cmp="CMP-078"
      data-state={state}
    >
      {state === "escalated" && props.strip !== undefined ? (
        <p className="cv-stale-shade__strip">
          <span className="cv-stale-shade__glyph">
            <Icon name="warning" size="sm" />
          </span>
          {props.strip}
        </p>
      ) : null}
      <div className="cv-stale-shade__body">
        {children}
        {fresh ? null : <div className="cv-stale-shade__dim" aria-hidden="true" />}
      </div>
      {line === null ? null : (
        <p className="cv-stale-shade__text" id={id}>
          {chip ? (
            <FreshnessMarker
              presentation="compact"
              state="stale"
              lastUpdatedAgeMs={finite(age)}
              escalated={state === "escalated"}
            />
          ) : null}
          <span>{line}</span>
        </p>
      )}
    </div>
  );
}
