/**
 * The CMP-091 route-level fallback (E10-S04 #306, slice 6), rendered by `RouteErrorElement` for an
 * unexpected route error. Reload page re-navigates to the same location, which re-runs the route.
 */
import { useEffect, useRef, useState, type JSX } from "react";
import { useLocation, useMatches, useNavigate } from "react-router";
import { GlobalErrorAnnouncement, GlobalErrorBoundaryFallback } from "@candleviewer/ui";
import { ScreenRoot } from "../app-shell/ScreenRoot";
import { copyCrashDiagnostics, recordCrash, type CrashRecord } from "./crashGuard";

export function RouteCrashFallback({ error }: { readonly error: unknown }): JSX.Element {
  const matches = useMatches();
  const routeId = matches[matches.length - 1]?.id ?? "route";
  // Recorded on commit, once per mount and error value: React's synchronous retry renders this with
  // a second error that is never committed, and StrictMode's double effect keeps the ref, so a
  // thrown primitive is not counted twice.
  const recorded = useRef<{ readonly error: unknown; readonly crash: CrashRecord } | null>(null);
  const [crash, setCrash] = useState<CrashRecord | null>(null);
  useEffect(() => {
    if (recorded.current === null || !Object.is(recorded.current.error, error)) {
      recorded.current = { error, crash: recordCrash(error, "route", routeId) };
    }
    setCrash(recorded.current.crash);
  }, [error, routeId]);
  const navigate = useNavigate();
  const location = useLocation();
  // The one wrapper is `ScreenRoot` (E10-S01 #304): a child route's error renders inside the shell's
  // `main` (a `div` then), the layout route's outside it (its own `main`), so the page keeps exactly
  // one `main`. The alert region is pre-rendered empty (the first commit, before the effect); only the
  // crash's sentence is injected into it, and the fallback renders beside it.
  return (
    <ScreenRoot>
      <div role="alert">
        {crash === null ? null : (
          <GlobalErrorAnnouncement scope="route" repeated={crash.repeated} />
        )}
      </div>
      {crash === null ? null : (
        <GlobalErrorBoundaryFallback
          scope="route"
          correlationId={crash.correlationId}
          repeated={crash.repeated}
          details={crash.details}
          onReload={() => void navigate(location, { replace: true })}
          onReloadApp={() => window.location.reload()}
          onCopyDiagnostics={copyCrashDiagnostics}
        />
      )}
    </ScreenRoot>
  );
}
