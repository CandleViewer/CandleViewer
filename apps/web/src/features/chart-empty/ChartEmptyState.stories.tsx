import type { JSX } from "react";
import { ChartEmptyState, type LiveState } from "./ChartEmptyState";
import {
  FAILED as COVERAGE_FAILED,
  NEVER_COVERAGE,
  OWNER,
  RETENTION_COVERAGE,
  VIEWER,
  VIEWING_AS,
  at,
  input,
  read,
} from "./fixtures";
import { selectChartState, type Access, type ChartStateInput } from "./model";

// E16-S05: one story per built E16-D05 §4 / §5 frame id (the story's name), on the §3 fixture; the `autorecord-*`
// frames wait for E16-S02 #566's feed. DOM only: every story's play asserts there is no <canvas> (AC 7). Plain CSF.
export default { title: "Patterns/RecorderEmptyStates", component: ChartEmptyState };

const noop = (): void => undefined;
function noCanvas({ canvasElement }: { readonly canvasElement: HTMLElement }): void {
  if (canvasElement.querySelector("canvas") !== null)
    throw new Error("the empty state drew a canvas");
}

type Row = Partial<ChartStateInput>;
function Frame(p: { row: Row; access?: Access; live?: LiveState; surface?: string }): JSX.Element {
  return (
    <div style={{ maxWidth: 640 }}>
      <ChartEmptyState
        state={selectChartState(input({ ...p.row, access: p.access ?? OWNER }))}
        live={p.live ?? "live"}
        onAction={noop}
        onRetry={noop}
        report={noop}
        {...(p.surface === undefined ? {} : { surface: p.surface })}
      />
    </div>
  );
}
const frame = (name: string, row: Row, access?: Access, surface?: string) => ({
  name,
  render: () => (
    <Frame row={row} {...(access ? { access } : {})} {...(surface ? { surface } : {})} />
  ),
  play: noCanvas,
});

const NEVER: Row = {
  bars: { kind: "no_data_recorded", recordingStartedAtMs: null },
  coverage: read(NEVER_COVERAGE),
};
const BEFORE: Row = {
  bars: { kind: "no_data_recorded", recordingStartedAtMs: at("2026-09-01T00:00:00Z") },
};
const RETENTION: Row = {
  window: { fromMs: at("2026-09-05T00:00:00Z"), toMs: at("2026-09-06T00:00:00Z") },
  coverage: read(RETENTION_COVERAGE),
};
const QUIET: Row = {
  window: { fromMs: at("2026-09-08T00:00:00Z"), toMs: at("2026-09-08T01:00:00Z") },
};
const PANEL = "history-panel";
// Driven by the served `role_restricted` flag (BQ-07); the coverage fixture stays as served.
const RESTRICTED: Row = { roleRestricted: true };
const FAILED: Row = { coverage: COVERAGE_FAILED };

export const NeverRecordedOwner = frame("SCR-047/never-recorded-owner", NEVER);
export const BeforeStart = frame("SCR-047/before-start", BEFORE);
export const GapWsDisconnect = frame("SCR-047/gap-ws-disconnect", {});
export const GapRetentionPurge = frame("SCR-047/gap-retention-purge", RETENTION);
export const NoTradesInWindow = frame("SCR-047/no-trades-in-window", QUIET);
export const NotTrading = frame("SCR-047/not-trading", { instrumentStatus: "Closed" });
export const NeverRecordedViewAs = frame("SCR-047/never-recorded-view-as", NEVER, VIEWING_AS);
export const NeverRecordedSentence = frame("SCR-047/never-recorded-sentence", NEVER, VIEWER);
export const RoleRestricted = frame("SCR-047/role-restricted", RESTRICTED);
export const Loading = frame("SCR-047 loading (CMP-029)", { bars: { kind: "loading" } });
export const CoverageError = frame("SCR-047 coverage failed (AC 6)", FAILED);
export const PanelNotStarted = frame("SCR-151/recording-not-started", BEFORE, OWNER, PANEL);
export const PanelRoleRestricted = frame("SCR-151/role-restricted", RESTRICTED, OWNER, PANEL);
