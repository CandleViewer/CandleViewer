import type { JSX } from "react";
import { Button } from "./Button.js";

/** A format CMP-099 exports (`15` CMP-099 Props). */
export type ExportFormat = "csv" | "pdf";

/**
 * Each format's button, named by its words: "Export CSV" is E29-D03's `fills.export.button` (D03:297); "Export PDF"
 * is PROPOSED, since no design names the second format's button yet.
 */
const LABELS: Readonly<Record<ExportFormat, string>> = { csv: "Export CSV", pdf: "Export PDF" };

export interface PrintExportBarProps {
  /** The formats offered, one button each in this order; SCR-078 offers CSV alone (E29-D04 §2.8.9). */
  readonly formats: readonly [ExportFormat, ...ExportFormat[]];
  /** Starts an export of `format`; never called while `loading`. */
  readonly onExport: (format: ExportFormat) => void;
  /**
   * An export is running (E29-D03:200): each button keeps its label in CMP-038's busy form, `aria-busy` with a
   * CMP-014 arc leading the label, and a press does nothing. Busy is never T2 (E29-D04:391).
   */
  readonly loading?: boolean;
  /** Emits `data-density` on the bar and its buttons; absent = inherit. */
  readonly density?: "comfortable" | "compact";
}

/**
 * CMP-099 PrintExportBar (E29-D04 §2.8.9; E29-S04 builds the interim D04H:265 asks of E05's owner): one CMP-001
 * secondary button per format, each a distinct labelled native button, so Tab reaches it and `Enter` and `Space` start
 * the export. Running keeps the label (CMP-038's busy form); the export's progress, done and failed lines and the
 * file's watermark are the host's (E29-D03:200, the footer and CMP-027), so the bar has no live region of its own.
 * A read that is never gated: no T2 and no disabled state (E29-D04 §2.8.9; E29-D03 §3.7 keeps Export enabled offline).
 */
export function PrintExportBar({
  formats,
  onExport,
  loading = false,
  density,
}: PrintExportBarProps): JSX.Element {
  // One button per format, in the host's order; a repeated format would be a second button for the same file.
  const offered = formats.filter((format, index) => formats.indexOf(format) === index);
  return (
    <div className="cv-print-export-bar" data-cmp="CMP-099" data-density={density}>
      {offered.map((format) => (
        <Button
          key={format}
          loading={loading}
          {...(density === undefined ? {} : { density })}
          onClick={() => onExport(format)}
        >
          {LABELS[format]}
        </Button>
      ))}
    </div>
  );
}
