import type { JSX } from "react";
import { Callout } from "./Callout.js";

/** The lead sentence: E36-D05 FS-1 (`rules.editor.notice.native_stop_1`), E32-D06 §4 S-1, the lead of every host. */
const CANONICAL_LEAD = "Every position keeps a native stop — you can move it, not delete it.";

/** The rule editors' clause: E36-D05 FS-2 (`rules.editor.notice.native_stop_2`), E32-D06 §4 S-4. */
const CANONICAL_CLAUSE =
  "Rules can tighten it, never remove it — the stop is held by the exchange, not by this app.";

/** Between the two sentences. It is the component's, so a host passes its clause without a leading space. */
const SEPARATOR = " ";

export interface SafetyInvariantNoticeProps {
  /**
   * The lead sentence, the host's key: the rule editors' `rules.editor.notice.native_stop_1` (E36-D05 FS-1).
   * A missing, empty or whitespace-only value renders the canonical sentence, never a blank title.
   */
  readonly lead?: string | undefined;
  /**
   * The host's context clause, passed without a leading space (the component adds the separator): the rule
   * editors' `rules.editor.notice.native_stop_2` (E36-D05 FS-2). A missing, empty or whitespace-only value
   * renders the canonical clause, never a partial statement.
   */
  readonly clause?: string | undefined;
}

/** The host's sentence without its outer whitespace, or the canonical one when it is missing, empty or blank. */
function sentence(host: string | undefined, canonical: string): string {
  const text = host?.trim();
  return text === undefined || text === "" ? canonical : text;
}

/**
 * CMP-158 SafetyInvariantNotice, the rule editors' variant (E36-D03; E37-D05 §3.9): the native-stop reminder above
 * the action bar, a CMP-028 `info` callout whose two sentences read as one statement. It is a `note`, never a live
 * region and never a Tab stop; it has no dismiss control and no state, and it appears and leaves in one frame in
 * both motion modes (E32-D06 §8). The two sentences default to the canonical rule-editor copy (E36-D05 FS-1 and
 * FS-2), and a missing, empty or whitespace-only override falls back to it, so the safety statement (C-2.6) never
 * renders blank or partial. The ticket, arming-dialog, held-position and draft-builder variants are their owners'
 * (E30, E35-S08, E32): each passes its own strings through these two props.
 */
export function SafetyInvariantNotice({ lead, clause }: SafetyInvariantNoticeProps): JSX.Element {
  return (
    <div className="cv-safety-notice" data-cmp="CMP-158" role="note">
      <Callout tone="info" live="off" title={sentence(lead, CANONICAL_LEAD)}>
        {/* A space, so the two sentences flow as one line where it fits (compact) and stay apart as text. */}
        {`${SEPARATOR}${sentence(clause, CANONICAL_CLAUSE)}`}
      </Callout>
    </div>
  );
}
