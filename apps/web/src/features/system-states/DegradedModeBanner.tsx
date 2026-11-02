import { useRef, type CSSProperties, type JSX } from "react";
import { Icon, IconButton, type IconName } from "@candleviewer/ui";
import { SEARCH_TRIGGER_ID } from "../app-shell/TopBar";
import type { DegradedSeverity } from "./copy";
import type { DegradedIssue } from "./degradedIssues";

/** Severity is glyph + word + colour (E17-D02 §8; `05` §4 item 4): colour is never the only signal. */
const SEVERITY = {
  blocking: { word: "Blocking", icon: "danger", tone: "danger" },
  warning: { word: "Warning", icon: "warning", tone: "warning" },
  info: { word: "Info", icon: "info", tone: "info" },
} as const satisfies Record<DegradedSeverity, { word: string; icon: IconName; tone: string }>;

const LIST: CSSProperties = { display: "grid", gap: "var(--space-stack-sm)" };

const row = (tone: string): CSSProperties => ({
  display: "flex",
  alignItems: "center",
  gap: "var(--space-inset-sm)",
  minHeight: "var(--size-target-min)",
  padding: "0 var(--space-inset-sm)",
  background: `var(--color-status-${tone}-subtle)`,
  border: "1px solid transparent", // forced-colors draws it (§13.2)
});

const TABBABLE =
  "a[href], button:not([disabled]), input:not([disabled]), select, textarea, [tabindex]";

/** The next stop after `el` in document order (§13's "the slot's next stop"). */
export function nextStopAfter(el: HTMLElement): HTMLElement | undefined {
  return [...document.querySelectorAll<HTMLElement>(TABBABLE)].find(
    (c) =>
      c.tabIndex >= 0 &&
      !el.contains(c) &&
      (el.compareDocumentPosition(c) & Node.DOCUMENT_POSITION_FOLLOWING) !== 0,
  );
}

/**
 * E10-D04 T-19 (PROPOSED), as SCR-157's Later (#4979): after a dismissal focus goes to the next
 * row's control, else to the next banner's first control, else to the TopBar's search trigger,
 * never into the canvas, where a held key could act.
 */
function afterDismissTarget(list: HTMLElement, index: number): HTMLElement | null {
  const nextRow = list.querySelectorAll<HTMLElement>("[data-dismiss]")[index + 1];
  if (nextRow !== undefined) return nextRow;
  const next = nextStopAfter(list);
  const slot = list.closest('[data-shell-slot="banner"]');
  return next !== undefined && slot?.contains(next) === true
    ? next
    : document.getElementById(SEARCH_TRIGGER_ID);
}

export interface DegradedModeBannerProps {
  /** The rows to show, in the §6 routing order (blocking, warning, info). */
  readonly issues: readonly DegradedIssue[];
  readonly onDismiss: (id: DegradedIssue["id"]) => void;
}

/**
 * CMP-092 DegradedModeBanner (E10-S04 slice 3, #306), an E10 shell organism (#306): apps/web is its
 * home. Still to come: the CMP-210 chip, `scope`, `href` and the PROPOSED "Show details".
 * Per row (E17-D02 §8): glyph + word in `.strong` on `.subtle`, message, stillWorks, then the
 * dismiss control (never gated); focus then moves as E10-D04 T-19 says (`afterDismissTarget`).
 */
export function DegradedModeBanner({ issues, onDismiss }: DegradedModeBannerProps): JSX.Element {
  const listRef = useRef<HTMLDivElement>(null);
  const dismiss = (id: DegradedIssue["id"], index: number): void => {
    const target = listRef.current === null ? null : afterDismissTarget(listRef.current, index);
    onDismiss(id);
    target?.focus();
  };
  return (
    <div ref={listRef} role="region" aria-label="System notices" style={LIST}>
      {issues.map((issue, index) => {
        const s = SEVERITY[issue.severity];
        return (
          <div key={issue.id} data-severity={issue.severity} style={row(s.tone)}>
            <span
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: "var(--space-2)",
                color: `var(--color-status-${s.tone}-strong)`,
                fontWeight: "var(--font-weight-semibold)",
              }}
            >
              <Icon name={s.icon} size="sm" />
              {s.word}
            </span>
            <span style={{ flex: 1, minWidth: 0 }}>
              <span style={{ color: "var(--color-text-primary)" }}>{issue.message}</span>
              {issue.stillWorks === null ? null : (
                <span style={{ color: "var(--color-text-secondary)" }}> {issue.stillWorks}</span>
              )}
            </span>
            <IconButton
              data-dismiss=""
              icon="close"
              label={`Dismiss ${issue.message}`}
              variant="ghost"
              size="sm"
              onClick={() => dismiss(issue.id, index)}
            />
          </div>
        );
      })}
    </div>
  );
}
