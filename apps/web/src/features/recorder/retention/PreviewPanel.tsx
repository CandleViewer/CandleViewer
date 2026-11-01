/**
 * SCR-141's preview panel, "What becomes eligible for deletion" (E16-D03 §5 `SCR-141/preview`; BQ-3; E16-D06 SD-04,
 * frozen (iv)): rendered by "Preview changes" for the current diff, above region (e). It leads with the consequence
 * sentence (or, when nothing shrinks, that nothing becomes eligible), lists per symbol the range and the size the
 * change makes eligible and every exempt pinned symbol, then the total and, for the client-side estimate, its
 * caption: the figures are estimates until the server reports them (C-2.13, C-2.14). The heading takes focus when
 * the panel renders and is described by the total.
 */
import { useId, type JSX, type Ref } from "react";
import { Table, Text, type TableColumn } from "@candleviewer/ui";
import { RETENTION_DECK } from "./retentionCopy";
import type { Preview } from "./retentionEstimate";
import type { Classification, SymbolCode } from "./retentionModel";
import {
  RETENTION_TEXT,
  eligibilityText,
  previewCells,
  previewExemptCells,
  previewTotalText,
  type PreviewCells,
} from "./retentionText";

export interface PreviewPanelProps {
  readonly classification: Classification;
  /** The source's answer for this diff; null when nothing shrinks or there is no report to estimate from. */
  readonly preview: Preview | null;
  /** The symbols the change reaches that the storage report does not list: named, never sized. */
  readonly unlisted?: readonly SymbolCode[] | undefined;
  readonly headingRef: Ref<HTMLHeadingElement>;
}

interface Row extends PreviewCells {
  readonly key: string;
}

const COLUMNS: readonly TableColumn<Row>[] = (
  ["symbol", "stream", "from", "to", "size"] as const
).map((id, i) => ({
  id,
  header: RETENTION_TEXT.preview[i] ?? id,
  cell: (row: Row) => row[id],
}));

export function PreviewPanel({
  classification,
  preview,
  unlisted = [],
  headingRef,
}: PreviewPanelProps): JSX.Element {
  const id = useId();
  const [title] = RETENTION_DECK["retention.preview.title"];
  const rows: Row[] =
    classification.kind === "reduction" && preview !== null
      ? [
          ...preview.rows.map((row) => ({ key: row.symbol, ...previewCells(row) })),
          ...preview.exempt.map((row) => ({
            key: `exempt-${row.symbol}`,
            ...previewExemptCells(row),
          })),
        ]
      : [];
  // With every symbol unsized there is no total to give: the line names them instead.
  const total =
    classification.kind === "reduction" &&
    preview !== null &&
    (preview.rows.length > 0 || unlisted.length === 0)
      ? previewTotalText(preview)
      : null;
  return (
    <section
      aria-labelledby={`${id}-title`}
      style={{
        display: "grid",
        gap: "var(--space-stack-sm)",
        padding: "var(--space-inset-sm)",
        background: "var(--color-surface-raised)",
        border: "1px solid var(--color-border-default)",
        borderRadius: "var(--radius-card)",
      }}
    >
      <h3
        ref={headingRef}
        id={`${id}-title`}
        tabIndex={-1}
        aria-describedby={total === null ? undefined : `${id}-total`}
        style={{
          margin: 0,
          font: "var(--type-ui-heading-sm-font-weight) var(--type-ui-heading-sm-font-size) / var(--type-ui-heading-sm-line-height) var(--type-ui-heading-sm-font-family)",
        }}
      >
        {title}
      </h3>
      {eligibilityText(classification, preview, unlisted).map((line) => (
        <Text key={line} as="p">
          {line}
        </Text>
      ))}
      {rows.length === 0 ? null : (
        <Table
          columns={COLUMNS}
          rows={rows}
          rowKey={(row) => row.key}
          caption={title}
          captionHidden
        />
      )}
      {total === null ? null : (
        <Text id={`${id}-total`} variant="body-strong" as="p">
          {total}
        </Text>
      )}
      {preview?.source === "estimate" && rows.length > 0 ? (
        <Text variant="caption" tone="secondary" as="p">
          {RETENTION_DECK["retention.preview.caption"][0]}
        </Text>
      ) : null}
    </section>
  );
}
