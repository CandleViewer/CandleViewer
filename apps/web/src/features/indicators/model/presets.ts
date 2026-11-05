// E13-S01 (#423) S1: preset shapes (`22` IndicatorPreset / IndicatorPresetInput; D02 D7, D14).
// Only `params` persist: `IndicatorPresetStyle` is empty until E13-D04, so `style` is always `{}`
// (D06 §3.2, BQ-3). A preset's params are re-validated against the live schema before they reach
// an instance (BQ-11): a preset is server data like any other.
import type { CatalogueEntry } from "./catalogue";
import { validateParams, type ParamsResult } from "./params";
import type { IndicatorPreset, IndicatorPresetInput, Params, PaneTarget } from "./types";

/** `22` `IndicatorPresetInput.name`: at most 80 characters as sent (the field's `maxLength`; never cut). */
export const PRESET_NAME_MAX = 80;

/** The writable body for a preset of `entry` with `params`, starred or not (D02 D7, D14). */
export function presetInput(
  entry: Pick<CatalogueEntry, "id">,
  name: string,
  params: Params,
  target: PaneTarget,
  favourite: boolean,
): IndicatorPresetInput {
  return {
    indicator_code: entry.id,
    name,
    params: { ...params },
    pane_target: target,
    is_favourite: favourite,
    style: {},
  };
}

/** The full-replacement body that re-stars or un-stars an existing preset (`updateIndicatorPreset`). */
export const starredInput = (
  preset: IndicatorPreset,
  favourite: boolean,
): IndicatorPresetInput => ({
  indicator_code: preset.indicator_code,
  name: preset.name,
  params: { ...preset.params },
  pane_target: preset.pane_target,
  is_favourite: favourite,
  style: {},
});

/**
 * The caller's live, user-owned preset with this code and name (case-insensitive, `22` `name_taken`),
 * which the star updates instead of creating a second one (D02 D7). Built-ins are never matched:
 * starring one saves a copy.
 */
export function findOwnPreset(
  presets: readonly IndicatorPreset[],
  code: string,
  name: string,
): IndicatorPreset | undefined {
  const folded = name.toLocaleLowerCase();
  return presets.find(
    (p) => !p.is_builtin && p.indicator_code === code && p.name.toLocaleLowerCase() === folded,
  );
}

/** The favourites the library lists: starred presets whose indicator the catalogue still lists. */
export function favouritesOf(
  presets: readonly IndicatorPreset[],
  entries: readonly CatalogueEntry[],
): readonly IndicatorPreset[] {
  const ids = new Set(entries.map((e) => e.id));
  return presets.filter((p) => p.is_favourite && ids.has(p.indicator_code));
}

/** A preset's params checked against its entry's live schema; a refused schema refuses the preset. */
export function presetParams(preset: IndicatorPreset, entry: CatalogueEntry): ParamsResult {
  if (!entry.schema.ok || preset.indicator_code !== entry.id) {
    return { ok: false, errors: [{ name: "", rule: "type" }] };
  }
  return validateParams(entry.schema.fields, preset.params);
}

/** The preset's target, kept only where the entry offers it (`22` `pane_target`; D06 §3.3). */
export function presetTarget(preset: IndicatorPreset, entry: CatalogueEntry): PaneTarget {
  if (entry.pane === "price") return "overlay";
  if (entry.pane === "sub") return "subpane";
  return preset.pane_target;
}
