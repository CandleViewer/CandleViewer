import type { JSX } from "react";
import { isRouteErrorResponse, useRouteError } from "react-router";
import { ForbiddenError } from "./guards";
import { ForbiddenState, NotFoundState } from "./ErrorStates";
import { ScreenRoot } from "../features/app-shell/ScreenRoot";

/**
 * Route-level `errorElement`. Guard loaders throw typed errors (never plain
 * `Error`s for the expected denial cases) so this stays a dispatcher, not a
 * generic crash screen — the generic crash screen is E10-S04's error
 * boundary, which this wraps for anything unexpected.
 */
export function RouteErrorElement(): JSX.Element {
  const error = useRouteError();

  if (error instanceof ForbiddenError) {
    return error.as === "404" ? <NotFoundState /> : <ForbiddenState />;
  }
  if (isRouteErrorResponse(error)) {
    return error.status === 404 ? <NotFoundState /> : <ForbiddenState />;
  }
  // Anything else is an unexpected crash; E10-S04 owns the full-page
  // error boundary UI. This minimal fallback keeps the route tree
  // testable standalone before that ticket lands.
  return (
    <ScreenRoot>
      <h1>Something went wrong</h1>
      <p>An unexpected error occurred while loading this route.</p>
    </ScreenRoot>
  );
}
