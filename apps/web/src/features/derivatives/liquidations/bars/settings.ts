// E24-S06 (#781) slice 1: the bars pane's two settings (D02 §10; ruled 6618373768 in #5699's RC fold, flattened
// names): `deriv.liq_mode` (`bars | heatmap`, default `bars`) and `deriv.liq_min_notional_usd` (a Decimal string,
// default "0"). They are the server's `Settings.deriv`, never local storage (#778's ruling, BQ-7). Until #5699
// merges the keys are not in the generated `Settings`, so the pane holds them as component state behind this one hook.
// TODO(#5699): replace `useLiqBarSettings` with the `Settings.deriv` read and `PATCH /settings`; the pane's props
// (`settings`, `onSettingsChange`) do not change.
import { useCallback, useState } from "react";

export type LiqMode = "bars" | "heatmap";

export interface LiqBarSettings {
  readonly mode: LiqMode;
  /** Decimal string, USDT; "0" = no filter. */
  readonly minNotionalUsd: string;
}

export const DEFAULT_LIQ_BAR_SETTINGS: LiqBarSettings = { mode: "bars", minNotionalUsd: "0" };

const DECIMAL = /^\d{1,15}(?:\.\d{1,8})?$/;

/** A valid threshold (a non-negative decimal string), trimmed; `null` for anything else. */
export function parseThreshold(text: string): string | null {
  const t = text.trim();
  return DECIMAL.test(t) ? t : null;
}

export function useLiqBarSettings(
  initial: LiqBarSettings = DEFAULT_LIQ_BAR_SETTINGS,
): readonly [LiqBarSettings, (patch: Partial<LiqBarSettings>) => void] {
  const [settings, set] = useState(initial);
  const change = useCallback((patch: Partial<LiqBarSettings>) => {
    set((s) => ({ ...s, ...patch }));
  }, []);
  return [settings, change];
}

/**
 * The feed's `min_notional_usd` for these settings: the same setting the bars state, so the legend's "feed ≥ X" is
 * true (BQ-1). "0" is no filter, `null` to #780's feed.
 */
export const feedMinNotional = (settings: LiqBarSettings): string | null =>
  /^0+(?:\.0+)?$/.test(settings.minNotionalUsd) ? null : settings.minNotionalUsd;
