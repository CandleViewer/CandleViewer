import type { CSSProperties, JSX, ReactNode } from "react";
import { Icon } from "../icons/Icon.js";
import { ColorSwatch } from "./ColorSwatch.js";
import { contrastRatio } from "./internal/contrast.js";

/** The catalogue's kinds plus J21's `scales`, `chart` (E12-D05) and `ladder` (E32-D04). */
export type PreviewTileKind =
  "candles" | "chart" | "footprint" | "heatmap" | "ladder" | "scales" | "theme";
export type PreviewTileSource = "live" | "sample";
/** `ready` draws the image; `empty` and `error` are availability and failure (J21). Never loading. */
export type PreviewTileStatus = "ready" | "empty" | "error";

/** Default English copy (plan gap 9, BQ-21); every string is a prop. */
export const PREVIEW_TILE_COPY = {
  unavailable: "Preview unavailable",
  empty: "Preview unavailable — no bars loaded",
  error: "Preview unavailable — chart error; settings still apply",
  sample: "Sample bars: not this chart",
  contrastWarning: (ratio: string): string =>
    `Low contrast: body text on this preview measures ${ratio}:1, below 4.5:1`,
  themeSample: { bid: "Bid 64,210.5", ask: "Ask 64,211.0", position: "BTCUSDT long 0.500 BTC" },
} as const;

/** The pair the BQ-18 warning measures: the tile's body text on its own surface. */
export const PREVIEW_TILE_CONTRAST_PAIR = {
  text: "color.text.primary",
  surface: "color.surface.sunken",
  min: 4.5,
} as const;

export interface PreviewTileProps {
  readonly kind?: PreviewTileKind;
  /** The configuration in words: the tile's accessible name while it draws ("Preview: BTCUSDT 1 minute, …"). */
  readonly label: string;
  /** `sample` adds the visible "not this chart" line (E12-D05 W-19). */
  readonly source?: PreviewTileSource;
  readonly status?: PreviewTileStatus;
  /** The host's renderer output (a second engine view); its colours are its own. */
  readonly children?: ReactNode;
  /** `ladder` only: one figure, or the five figures of the collapsed form, joined by " · ". */
  readonly value?: string | readonly string[];
  /** The visible "Changes:" line under the tile; read in DOM order, not referenced by the tile. */
  readonly caption?: string;
  /**
   * Token name -> value, applied as scoped custom properties on the tile only (BQ-18):
   * `{ "color.surface.sunken": "#0B0E13" }` sets `--color-surface-sunken`. Invalid names are ignored.
   */
  readonly tokenOverrides?: Readonly<Record<string, string>>;
  readonly emptyText?: string;
  readonly errorText?: string;
  readonly unavailableName?: string;
  readonly sampleText?: string;
  readonly contrastWarning?: (ratio: string) => string;
  readonly themeSample?: { readonly bid: string; readonly ask: string; readonly position: string };
}

const TOKEN_NAME = /^[a-z][a-z0-9-]*(\.[a-z0-9-]+)+$/;

/** The overrides as `--a-b-c` custom properties; a name outside the token grammar is dropped. */
function scopedProperties(overrides: Readonly<Record<string, string>>): CSSProperties {
  const style: Record<string, string> = {};
  for (const [name, value] of Object.entries(overrides)) {
    if (TOKEN_NAME.test(name)) style[`--${name.replace(/\./g, "-")}`] = value;
  }
  return style as CSSProperties;
}

/** The pair's ratio when both sides are overridden with opaque hex values; otherwise no check. */
function overrideRatio(overrides: Readonly<Record<string, string>>): number | null {
  const text = overrides[PREVIEW_TILE_CONTRAST_PAIR.text];
  const surface = overrides[PREVIEW_TILE_CONTRAST_PAIR.surface];
  return text === undefined || surface === undefined ? null : contrastRatio(text, surface);
}

/**
 * CMP-228 PreviewTile: the miniature preview beside a settings form. One `role="img"` named in words,
 * never focusable, never a live region, never the only disclosure. No spinner: a recomputing host keeps
 * its last frame. Empty and error tiles are named "Preview unavailable" and say why in visible text.
 */
export function PreviewTile({
  kind = "candles",
  label,
  source = "live",
  status = "ready",
  children,
  value,
  caption,
  tokenOverrides = {},
  emptyText = PREVIEW_TILE_COPY.empty,
  errorText = PREVIEW_TILE_COPY.error,
  unavailableName = PREVIEW_TILE_COPY.unavailable,
  sampleText = PREVIEW_TILE_COPY.sample,
  contrastWarning = PREVIEW_TILE_COPY.contrastWarning,
  themeSample = PREVIEW_TILE_COPY.themeSample,
}: PreviewTileProps): JSX.Element {
  const ready = status === "ready";
  const collapsed = ready && kind === "ladder" && Array.isArray(value);
  const state = ready ? (collapsed ? "collapsed" : source) : status;
  const ratio = overrideRatio(tokenOverrides);
  const warning =
    ratio !== null && ratio < PREVIEW_TILE_CONTRAST_PAIR.min
      ? contrastWarning(ratio.toFixed(2))
      : null;

  let image: ReactNode = children;
  if (status === "empty") image = <span className="cv-preview-tile__status">{emptyText}</span>;
  else if (status === "error")
    image = (
      <span className="cv-preview-tile__status">
        <span className="cv-preview-tile__glyph">
          <Icon name="error" />
        </span>
        {errorText}
      </span>
    );
  else if (kind === "ladder" && value !== undefined)
    image = (
      <span className="cv-preview-tile__value">
        {typeof value === "string" ? value : value.join(" · ")}
      </span>
    );
  else if (kind === "theme" && children === undefined)
    image = (
      <span className="cv-preview-tile__sample">
        <span className="cv-preview-tile__row">
          <ColorSwatch decorative color="var(--color-buy-default)" label="" />
          {themeSample.bid}
        </span>
        <span className="cv-preview-tile__row">
          <ColorSwatch decorative color="var(--color-sell-default)" label="" />
          {themeSample.ask}
        </span>
        <span className="cv-preview-tile__row">{themeSample.position}</span>
      </span>
    );

  return (
    <div className="cv-preview-tile" data-cmp="CMP-228" data-kind={kind} data-state={state}>
      <div
        role="img"
        aria-label={ready ? label : unavailableName}
        aria-live="off"
        className="cv-preview-tile__frame"
        style={scopedProperties(tokenOverrides)}
      >
        {image}
      </div>
      {ready && source === "sample" ? <p className="cv-preview-tile__note">{sampleText}</p> : null}
      {warning !== null ? (
        <p className="cv-preview-tile__note cv-preview-tile__warning">
          <span className="cv-preview-tile__glyph">
            <Icon name="warning" />
          </span>
          {warning}
        </p>
      ) : null}
      {caption !== undefined ? <p className="cv-preview-tile__caption">{caption}</p> : null}
    </div>
  );
}
