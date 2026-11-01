/**
 * SCR-141's error summary (E16-D03 §7 `SCR-141/error-summary`; E16-D06 FM-11, SR-18, BG-03, F-10): at the top of the
 * form, a heading and, for fields in error, one link per field that moves focus to it. A press on Apply in the
 * validity look, or a server refusal, moves focus to the heading: that move is the one reading, so the summary is no
 * live region and never `role="alert"` (F-10). The words are the deck's; a refusal's are its route's (D06 §16.4).
 */
import type { JSX, Ref } from "react";
import { Icon, useFocusRing } from "@candleviewer/ui";

export interface SummaryLink {
  readonly label: string;
  /** The field the link focuses. */
  readonly targetId: string;
}

export interface ErrorSummaryProps {
  readonly title: string;
  readonly links: readonly SummaryLink[];
  readonly headingRef: Ref<HTMLHeadingElement>;
}

export function ErrorSummary({ title, links, headingRef }: ErrorSummaryProps): JSX.Element {
  const ring = useFocusRing();
  return (
    <div
      data-error-summary=""
      style={{
        display: "grid",
        gap: "var(--space-stack-xs)",
        padding: "var(--space-inset-sm)",
        borderInlineStart: "2px solid var(--color-status-danger-default)",
        background: "var(--color-status-danger-subtle)",
        color: "var(--color-text-primary)",
      }}
    >
      <h3
        ref={headingRef}
        tabIndex={-1}
        className={ring.className}
        style={{
          margin: 0,
          display: "flex",
          gap: "var(--space-inset-xs)",
          alignItems: "center",
          font: "var(--type-ui-body-strong-font-weight) var(--type-ui-body-strong-font-size) / var(--type-ui-body-strong-line-height) var(--type-ui-body-strong-font-family)",
        }}
      >
        <span style={{ color: "var(--color-status-danger-strong)", display: "inline-flex" }}>
          <Icon name="danger" />
        </span>
        {title}
      </h3>
      {links.length === 0 ? null : (
        <ul style={{ margin: 0, paddingInlineStart: "var(--space-inset-lg)" }}>
          {links.map((link) => (
            <li key={link.targetId}>
              <button
                type="button"
                className={`cv-link ${ring.className}`}
                style={{ padding: 0, border: 0, background: "none", textAlign: "start" }}
                onClick={() => document.getElementById(link.targetId)?.focus()}
              >
                {link.label}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
