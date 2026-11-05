/**
 * R-101 and R-102's elements (E15-S03 #476; BQ-02 as ruled) behind the served `ui.workspace_dock`
 * (`21` §10.7; removal #5672), read through the shell's one flag store (`useFlag`, #5669): unread
 * reads off. Off, each renders what it did before the flag; on, the workspace code loads as its
 * own chunk, so the flag-off shell carries none of it.
 */
import { lazy, Suspense, type JSX, type ReactNode } from "react";
import { useFlag } from "../../../shell/flags/useFlag";
import { opening } from "./states";

export const WORKSPACE_DOCK_FLAG = "ui.workspace_dock";

const routes = () => import("./WorkspaceRoutes");
const TerminalResolver = lazy(() => routes().then((m) => ({ default: m.TerminalResolver })));
const WorkspaceRoute = lazy(() => routes().then((m) => ({ default: m.WorkspaceRoute })));

function Gate({ off, on }: { readonly off: ReactNode; readonly on: JSX.Element }): JSX.Element {
  return useFlag(WORKSPACE_DOCK_FLAG) === true ? (
    <Suspense fallback={opening}>{on}</Suspense>
  ) : (
    <>{off}</>
  );
}

/** R-101 `/terminal/:layoutId`: resolves to `/w/:workspaceId` while the flag is on. */
export const TerminalEntry = ({ off }: { readonly off: ReactNode }): JSX.Element => (
  <Gate off={off} on={<TerminalResolver />} />
);

/** R-102 `/w/:workspaceId`: SCR-020 while the flag is on. */
export const WorkspaceEntry = ({ off }: { readonly off: ReactNode }): JSX.Element => (
  <Gate off={off} on={<WorkspaceRoute />} />
);
