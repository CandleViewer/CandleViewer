/**
 * The CSV export's file (E29-S01 #911; E29-D02 D-21, BQ-17): the text `csv.ts` builds, saved through
 * the browser's own download (a Blob URL on an `<a download>`), the URL revoked once the click has
 * gone. Client-side only: no request, no audit record and no analytics event (`grid.exported` is not
 * in `24` §15.5 and no export endpoint exists, D04-G5 and D04-G9; the gap stays recorded on #911).
 * The file name is PROPOSED, on D03's export pattern (`candleviewer-fills-order-…-<UTC>Z.csv`).
 */
import { PROPOSED_TEXT } from "./copy";

/** "candleviewer-positions-20261101T140509Z.csv": the UTC time of the export, to the second. */
export function exportFileName(at: Date): string {
  const stamp = at
    .toISOString()
    .replace(/\.\d{3}Z$/, "Z")
    .replace(/[-:]/g, "");
  return PROPOSED_TEXT.exportFileName.replace("{stamp}", stamp);
}

/** What saves a file: the browser download by default; a test passes its own. */
export type SaveFile = (name: string, text: string) => void;

/** Saves `text` as a CSV download in `doc` (the panel's own document, docked or popped out). */
export function saveCsv(name: string, text: string, doc: Document = document): void {
  const view = doc.defaultView ?? globalThis;
  const url = view.URL.createObjectURL(new Blob([text], { type: "text/csv;charset=utf-8" }));
  const link = doc.createElement("a");
  link.href = url;
  link.download = name;
  link.hidden = true;
  doc.body.append(link);
  link.click();
  link.remove();
  // after the click has handed the file to the download
  view.setTimeout(() => view.URL.revokeObjectURL(url), 0);
}
