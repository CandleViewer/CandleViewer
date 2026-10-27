import { useRef, type CSSProperties, type JSX } from "react";
import { Icon, IconButton, type IconName } from "@candleviewer/ui";
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

/** The slot's next stop after `el` in document order (§13: the dismiss lands there after the last row). */
function nextStopAfter(el: HTMLElement): HTMLElement | undefined {
  return [...document.querySelectorAll<HTMLElement>(TABBABLE)].find(
    (c) =>
      c.tabIndex >= 0 &&
      !el.contains(c) &&
      (el.compareDocumentPosition(c) & Node.DOCUMENT_POSITION_FOLLOWING) !== 0,
  );
}

export interface DegradedModeBannerProps {
  /** The rows to show, in the §6 routing order (blocking, warning, info). */
  readonly issues: readonly DegradedIssue[];
  readonly onDismiss: (id: DegradedIssue["id"]) => void;
}

/**
 * TEMPORARY CMP-092 DegradedModeBanner (E10-S04 slice 3, #306): E05's `packages/ui` component (#267
 * / #265) replaces it, bringing the CMP-210 chip, `scope`, `href` and the PROPOSED "Show details".
 * Per row (E17-D02 §8): glyph + word in `.strong` on `.subtle`, message, stillWorks, then the
 * dismiss control (never gated); focus then moves to the next row's control or the slot's next stop.
 */
export function DegradedModeBanner({ issues, onDismiss }: DegradedModeBannerProps): JSX.Element {
  const listRef = useRef<HTMLDivElement>(null);
  const dismiss = (id: DegradedIssue["id"], index: number): void => {
    const list = listRef.current;
    const target =
      list?.querySelectorAll<HTMLElement>("[data-dismiss]")[index + 1] ??
      (list ? nextStopAfter(list) : undefined);
    onDismiss(id);
    target?.focus();
  };
  return (
    <div ref={listRef} style={LIST}>
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
