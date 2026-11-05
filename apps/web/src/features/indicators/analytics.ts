/**
 * E13-S01 (#423) S2: the five `indicator.*` events (E13-D02 §8 D30; BQ-12) on the app's seam,
 * `cv:analytics` on `window`, as SCR-157, SCR-159 and the recorder report. Payloads are D30's fixed
 * shapes: no instance id or key, account, symbol, rule or parameter value; `key` is a parameter
 * NAME (D02 C-8). A blocked add, re-tune or removal emits none (D02:323). `indicator.removed` fires
 * when the removal toast's undo window closes (D02 :322), so the toast (S5b) reports it, not the
 * store. E13-D06 §8.2 records D12-G-7 (no transport); `cv:analytics` is the seam while D12-G-7
 * stays open (BQ-12, ruling 6652282467).
 *
 * Names: only `indicator.added` is named by `14` (SCR-034 Analytics). The other four are PROPOSED
 * (BQ-12 rider) until `14` or D12 names them; they are listed in `PROPOSED_EVENT_NAMES` and the PR.
 */
import { THEME_ANALYTICS_EVENT } from "../../shell/bootstrap/themeStore";
import type { Compute, PaneTarget } from "./model/types";

export type AddEntry =
  "library" | "palette" | "favourite" | "second_instance" | "builtin_preset" | "undo";
export type ToggleSource = "legend" | "tree" | "bulk";
export type SettingsTab = "inputs" | "style" | "visibility" | "scale";

export type IndicatorAnalytics =
  | {
      readonly name: "indicator.added";
      readonly type: string;
      readonly pane_target: PaneTarget;
      readonly entry: AddEntry;
      readonly compute: Compute;
    }
  | {
      readonly name: "indicator.settings_changed";
      readonly type: string;
      readonly key: string;
      readonly tab: SettingsTab;
      readonly outcome: "applied" | "new_instance";
    }
  | {
      readonly name: "indicator.reordered";
      readonly type: string;
      readonly group: "overlays" | "subpanes";
      readonly from: number;
      readonly to: number;
    }
  | {
      readonly name: "indicator.visibility_toggled";
      readonly type: string;
      readonly visible: boolean;
      readonly source: ToggleSource;
    }
  | { readonly name: "indicator.removed"; readonly type: string; readonly source: ToggleSource };

/** The event name `14` SCR-034 names. */
export const NAMED_EVENT_NAMES = ["indicator.added"] as const;
/** PROPOSED (BQ-12 rider): D02 D30's names, not yet in `14`. */
export const PROPOSED_EVENT_NAMES = [
  "indicator.settings_changed",
  "indicator.reordered",
  "indicator.visibility_toggled",
  "indicator.removed",
] as const;

export type IndicatorReporter = (event: IndicatorAnalytics) => void;

export const reportIndicator: IndicatorReporter = (event) => {
  window.dispatchEvent(
    new CustomEvent<IndicatorAnalytics>(THEME_ANALYTICS_EVENT, { detail: event }),
  );
};
