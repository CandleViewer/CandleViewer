/**
 * The E42-S08 statechart inspector for R-357 `/admin/statecharts` (E42-D05 §11; BQ-1 as ruled): an
 * owner-only admin page inside CMP-087, reached by its URL once R-357 mounts it (this ticket's last
 * part; nothing links to it). This is its frame: CMP-088's `h1` "Statechart inspector" and the
 * "All times UTC" line.
 */
import type { JSX } from "react";
import { PageHeader } from "@candleviewer/ui";
import { ScreenRoot } from "../../app-shell/ScreenRoot";
import { INSPECTOR_COPY as COPY } from "./copy";

/**
 * The page's screen id: PROPOSED, the `14` owner's to assign (BQ-1). The admin band's two free
 * slots, SCR-138 and SCR-139, are held for security screens (`14` §0.2), so neither is taken here.
 * The ruling replaces this one value and `14`'s heading.
 */
export const INSPECTOR_SCREEN = "SCR-PROPOSED";

export function InspectorPage(): JSX.Element {
  return (
    <ScreenRoot>
      <div data-scr={INSPECTOR_SCREEN}>
        <PageHeader title={COPY.page.title} meta={COPY.page.utc} />
      </div>
    </ScreenRoot>
  );
}
