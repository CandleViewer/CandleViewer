import type { JSX } from "react";
import { ScreenRoot } from "../features/app-shell/ScreenRoot";

/** R-900 `/403` — CMP-089 ForbiddenState (minimal placeholder pending E11 design). */
export function ForbiddenState(): JSX.Element {
  return (
    <ScreenRoot>
      <h1>Forbidden</h1>
      <p>You do not have access to this page.</p>
      <a href="/terminal">Return to the terminal</a>
    </ScreenRoot>
  );
}

/** R-901 `/404` — CMP-090 NotFoundState. Also used for `/admin/**` non-owner denials. */
export function NotFoundState(): JSX.Element {
  return (
    <ScreenRoot>
      <h1>Not found</h1>
      <p>Nothing lives at this address.</p>
      <a href="/terminal">Return to the terminal</a>
    </ScreenRoot>
  );
}
