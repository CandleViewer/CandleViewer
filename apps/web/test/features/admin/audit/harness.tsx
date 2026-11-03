/**
 * E42-S04 (#1135): the screens' harness. SCR-135 mounts at R-360's path in a memory router, inside
 * the shell's provider and its one announcer, against a stubbed `fetch` that records every request
 * as sent (no network, C-13.5). The shell's announcer is wrapped so a test reads exactly the lines
 * said, once each, and its gated announcement is the shell's no-op (`ShellLayout`), so a T2 press
 * says only what the page routes (G-T2.3). Fake timers drive every cadence; a test flushes them
 * through `act`.
 */
import type { ReactNode } from "react";
import { act, render } from "@testing-library/react";
import { createMemoryRouter } from "react-router";
import { RouterProvider } from "react-router/dom";
import { vi } from "vitest";
import { GatedAnnounceProvider } from "@candleviewer/ui";
import { AuditLogPage } from "../../../../src/features/admin/audit/AuditLogPage";
import type { AuditView } from "../../../../src/features/admin/audit/auditReads";
import { ShellAnnouncer } from "../../../../src/features/app-shell/announcer";
import { InShellProvider } from "../../../../src/features/app-shell/ScreenRoot";
import { setShellState, type Me } from "../../../../src/shell/bootstrap/store";
import { OWNER_ID, json, pageBody, stubFetch, type Entry, type Sent } from "./fixtures";

export const AUDIT = "/api/v1/admin/audit";
/** The shell's gated announcement (`ShellLayout`): the surfaces own it (ruling on #5135). */
const ignoreGatedAnnouncement = (): void => undefined;
export const INCIDENTS = "/api/v1/admin/incidents";
export const VERIFY = "/api/v1/admin/audit/verify";

/** The session as the bootstrap leaves it: the shell's `me`. */
export function sessionAs(
  role: "owner" | "manager" | "viewer",
  id: string = OWNER_ID,
  username = "basiltt",
): void {
  const me = { role, permissions: [], accounts: [], user: { id, username } };
  setShellState({ me: me as unknown as Me, environment: "live" });
}

/** The server, by path: each handler answers the requests on its path, in order. */
export interface Routes {
  readonly audit?: (url: URL, n: number) => Response | Promise<Response>;
  readonly incidents?: (n: number) => Response | Promise<Response>;
  readonly verify?: (n: number) => Response | Promise<Response>;
  readonly other?: (sent: Sent) => Response | Promise<Response>;
}

const NO_INCIDENTS = { items: [], meta: { next_cursor: null, has_more: false, count: 0 } };

/** One audit page per read: `pages[n]`, the last repeated. */
export const pagesOf =
  (...pages: readonly (readonly Entry[] | Response)[]) =>
  (_url: URL, n: number): Response => {
    const page = pages[Math.min(n, pages.length - 1)] ?? [];
    return page instanceof Response ? page : json(200, pageBody(page));
  };

export interface Mounted {
  readonly router: ReturnType<typeof createMemoryRouter>;
  readonly sent: Sent[];
  /** The `GET /admin/audit` reads sent, as URLs. */
  readonly reads: () => URL[];
  readonly flush: (ms?: number) => Promise<void>;
  readonly unmount: () => void;
}

export async function flush(ms = 0): Promise<void> {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

export async function mountAuditPage(options: {
  readonly routes: Routes;
  readonly view?: AuditView;
  readonly search?: string;
  readonly onWithdrawn?: (refId: string | undefined) => void;
  /** R-360's element in place of SCR-135's raw view (My activity's page). */
  readonly element?: ReactNode;
}): Promise<Mounted> {
  const counts = { audit: 0, incidents: 0, verify: 0 };
  const { routes } = options;
  const sent = stubFetch((call) => {
    const url = new URL(call.url, "http://cv.test");
    if (url.pathname === AUDIT && call.method === "GET") {
      return (routes.audit ?? pagesOf([]))(url, counts.audit++);
    }
    if (url.pathname === INCIDENTS) {
      return routes.incidents?.(counts.incidents++) ?? json(200, NO_INCIDENTS);
    }
    if (url.pathname === VERIFY) {
      const answer = routes.verify?.(counts.verify++);
      if (answer !== undefined) return answer;
    }
    return routes.other?.(call) ?? json(404, { code: "not_found" });
  });
  const view = options.view ?? "raw";
  const page = options.element ?? (
    <AuditLogPage
      view={view}
      {...(options.onWithdrawn === undefined ? {} : { onWithdrawn: options.onWithdrawn })}
    />
  );
  const router = createMemoryRouter(
    [
      { path: "/admin/audit", element: page },
      { path: "*", element: <h1>Elsewhere</h1> },
    ],
    { initialEntries: [`/admin/audit${options.search ?? ""}`] },
  );
  const view_ = render(
    <GatedAnnounceProvider announce={ignoreGatedAnnouncement}>
      <InShellProvider>
        <ShellAnnouncer />
        <main>
          <RouterProvider router={router} />
        </main>
      </InShellProvider>
    </GatedAnnounceProvider>,
  );
  await flush();
  return {
    router,
    sent,
    reads: () =>
      sent
        .map((call) => new URL(call.url, "http://cv.test"))
        .filter((url) => url.pathname === AUDIT),
    flush,
    unmount: () => {
      view_.unmount();
      router.dispose();
    },
  };
}
