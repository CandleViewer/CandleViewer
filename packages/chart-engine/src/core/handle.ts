// Engine handle. Real GL/layer wiring lands in E06 (spike) and E11 (engine
// core). No DOM globals, no React, no fetch here (C-2.16).

import type { ThemeMetrics } from "../theme/ThemeIngest.js";

/**
 * Theme token object handed in by the host (the engine never imports the
 * design system). `colors` maps token names (e.g. `color.buy.default`) to CSS
 * colour strings; `palette`/`convention` identify the chart colour mode.
 */
export interface EngineTheme {
  readonly palette: "default" | "cvd-safe";
  readonly convention: "standard" | "inverted";
  readonly colors: Readonly<Record<string, string>>;
  /** E14-T04: the §8 `ThemeTokens.metrics` (one shape, BQ-2); resolved by `ingestMetrics`. */
  readonly metrics?: ThemeMetrics;
}

export interface EngineOptions {
  /** Receives the packed palette whenever it changes (GPU palette-texture upload). */
  readonly uploadPalette?: (theme: EngineTheme, packed: Float32Array) => void;
}

export interface EngineStats {
  readonly paletteUploads: number;
}

import { DEFAULT_RENDER_FLAGS, type RenderFlags } from "./flags.js";

export interface EngineHandle {
  /** Applies a theme; re-uploads the palette texture only if it changed. */
  setTheme(theme: EngineTheme): void;
  stats(): EngineStats;
  /** Applies accessibility render flags from the next frame; no scene rebuild. */
  setFlags(flags: RenderFlags): void;
  /** Latest flags read by the render loop each frame. */
  getFlags(): RenderFlags;
  /** Releases pooled GPU resources and worker subscriptions. */
  dispose(): void;
}

function themeKey(theme: EngineTheme): string {
  const names = Object.keys(theme.colors).sort();
  return [theme.palette, theme.convention, ...names.map((n) => `${n}=${theme.colors[n]}`)].join(
    "|",
  );
}

function pack(theme: EngineTheme): Float32Array {
  const names = Object.keys(theme.colors).sort();
  const out = new Float32Array(names.length * 4);
  names.forEach((name, i) => {
    const hex = /^#([0-9a-f]{6})$/i.exec(theme.colors[name] ?? "")?.[1];
    const v = hex === undefined ? 0 : Number.parseInt(hex, 16);
    out.set([((v >> 16) & 255) / 255, ((v >> 8) & 255) / 255, (v & 255) / 255, 1], i * 4);
  });
  return out;
}

export function createEngine(options: EngineOptions = {}): EngineHandle {
  let disposed = false;
  let uploads = 0;
  let currentKey: string | null = null;
  let flags: RenderFlags = DEFAULT_RENDER_FLAGS;
  return {
    setTheme(theme: EngineTheme): void {
      if (disposed) return;
      const key = themeKey(theme);
      if (key === currentKey) return;
      currentKey = key;
      uploads += 1;
      options.uploadPalette?.(theme, pack(theme));
    },
    stats(): EngineStats {
      return { paletteUploads: uploads };
    },
    setFlags(f: RenderFlags): void {
      flags = f;
    },
    getFlags(): RenderFlags {
      return flags;
    },
    dispose(): void {
      disposed = true;
    },
  };
}
