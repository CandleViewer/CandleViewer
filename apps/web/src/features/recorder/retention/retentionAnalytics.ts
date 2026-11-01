/**
 * SCR-141's analytics (#485 Observability; E16-D06 C-z): the story's own three names, since no parent names one
 * (`14`'s `retention.default_changed` family is the server's audit vocabulary, D03-C6). On the app's seam
 * (`cv:analytics` on `window`, as SCR-140 reports). Payloads carry the change's kind only: never a user, a symbol, a
 * size or a server message. The server audits the change itself (`retention.change`).
 */
import { THEME_ANALYTICS_EVENT } from "../../../shell/bootstrap/themeStore";
import type { Classification, ReductionKind } from "./retentionModel";

/** What a preview was asked for: a reduction's kind, else the classification's. */
export type PreviewKind = ReductionKind | Exclude<Classification["kind"], "reduction">;

export type RetentionAnalytics =
  | { readonly name: "retention.editor_opened" }
  | { readonly name: "retention.preview_requested"; readonly kind: PreviewKind }
  /** A preview was seen and the dialog closed with no change applied (a high count means the defaults are wrong). */
  | { readonly name: "retention.change_cancelled_after_preview" };

export function reportRetention(event: RetentionAnalytics): void {
  window.dispatchEvent(
    new CustomEvent<RetentionAnalytics>(THEME_ANALYTICS_EVENT, { detail: event }),
  );
}

/** The kind a preview reports. */
export const previewKind = (classification: Classification): PreviewKind =>
  classification.kind === "reduction" ? classification.confirm.reductionKind : classification.kind;
