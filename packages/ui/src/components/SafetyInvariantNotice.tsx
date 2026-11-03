import type { JSX } from "react";
import { Callout } from "./Callout.js";

export interface SafetyInvariantNoticeProps {
  /** The lead sentence, the host's key: the rule editors' `rules.editor.notice.native_stop_1` (E36-D05 FS-1). */
  readonly lead: string;
  /** The host's context clause: the rule editors' `rules.editor.notice.native_stop_2` (E36-D05 FS-2). */
  readonly clause: string;
}

/**
 * CMP-158 SafetyInvariantNotice, the rule editors' variant (E36-D03; E37-D05 §3.9): the native-stop reminder above
 * the action bar, a CMP-028 `info` callout whose two sentences read as one statement. It is a `note`, never a live
 * region and never a Tab stop; it has no dismiss control and no state, and it appears and leaves in one frame in
 * both motion modes (E32-D06 §8). The ticket, arming-dialog, held-position and draft-builder variants are their
 * owners' (E30, E35-S08, E32).
 */
export function SafetyInvariantNotice({ lead, clause }: SafetyInvariantNoticeProps): JSX.Element {
  return (
    <div className="cv-safety-notice" data-cmp="CMP-158" role="note">
      <Callout tone="info" live="off" title={lead}>
        {/* A space, so the two sentences flow as one line where it fits (compact) and stay apart as text. */}
        {` ${clause}`}
      </Callout>
    </div>
  );
}
