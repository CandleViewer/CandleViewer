/**
 * The CMP-091 route-level fallback (E10-S04 #306, slice 6), rendered by `RouteErrorElement` for an
 * unexpected route error. Its root is `ScreenRoot` (E10-S01 #304): a `div` inside the shell's `main`,
 * its own `main` outside it, so the page keeps exactly one `main`. Reload page re-navigates to the
 * same location, which re-runs the route.
 */
import { useEffect, useState, type JSX } from "react";
import { useLocation, useMatches, useNavigate } from "react-router";
import { ScreenRoot } from "../app-shell/ScreenRoot";
import { CrashFallback } from "./CrashFallback";
import { defaultCrashGuard, recordCrash, type CrashGuard, type CrashRecord } from "./crashGuard";

export interface RouteCrashFallbackProps {
  readonly error: unknown;
  readonly guard?: CrashGuard | undefined;
}

export function RouteCrashFallback({
  error,
  guard = defaultCrashGuard,
}: RouteCrashFallbackProps): JSX.Element {
  const matches = useMatches();
  const routeId = matches[matches.length - 1]?.id ?? "route";
  // recorded on commit: React's synchronous retry renders this element with a second error object,
  // which is never committed; recordCrash is idempotent per object (StrictMode's double effect)
  const [crash, setCrash] = useState<CrashRecord | null>(null);
  useEffect(() => {
    setCrash(recordCrash(error, "route", routeId, guard));
  }, [error, routeId, guard]);
  const navigate = useNavigate();
  const location = useLocation();
  return (
    <ScreenRoot>
      {crash === null ? null : (
        <CrashFallback
          scope="route"
          crash={crash}
          onReload={() => void navigate(location, { replace: true })}
        />
      )}
    </ScreenRoot>
  );
}
