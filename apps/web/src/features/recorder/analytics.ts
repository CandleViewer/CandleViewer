/**
 * SCR-140's analytics (E16-D02 §12, C-z): the parents' names where a parent gives one, and
 * `recorder.screen_viewed` as the story's own, on the app's seam (`cv:analytics` on `window`, as
 * SCR-157 and SCR-159 report). Payloads name symbols and settings only: never a user, a size or a
 * server message. A T2 press emits none (D02 §10.5).
 */
import { THEME_ANALYTICS_EVENT } from "../../shell/bootstrap/themeStore";
import type { RecordReason } from "./model/types";

export type RecorderAnalytics =
  | { readonly name: "recorder.screen_viewed" }
  | {
      readonly name: "recorder.symbol_added";
      readonly symbol: string;
      readonly depth: number;
      readonly streams: readonly string[];
      readonly retentionDays: number | null;
      readonly pinned: boolean;
    }
  | {
      readonly name: "recorder.symbol_stopped";
      readonly symbol: string;
      readonly reason: RecordReason;
    }
  | { readonly name: "recorder.auto_review_opened"; readonly source: "summary" | "why" }
  | { readonly name: "recorder.pin_toggled"; readonly symbol: string; readonly pinned: boolean };

export function reportRecorder(event: RecorderAnalytics): void {
  window.dispatchEvent(
    new CustomEvent<RecorderAnalytics>(THEME_ANALYTICS_EVENT, { detail: event }),
  );
}
