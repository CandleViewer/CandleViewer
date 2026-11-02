import { ROUTE_MANIFEST, type ManifestEntry } from "../../src/routes/manifest";
import type { MeOptions } from "../support/api";

/**
 * Screen set for the accessibility collectors (E47-T02, 05-accessibility-standard.md s9).
 * PR set = routes that render without a session. A guarded route visited bare is bounced to /login,
 * whose own <main> satisfies the collectors' wait, so the login page would be audited under that
 * route's id (#3470). A screen that needs a session goes in SIGNED_IN with its h1 instead: the axe
 * and tree collectors enter it through the shell's own bootstrap with /api/v1/me answered at the
 * network layer (open.ts). The nightly full sweep (A11Y_SWEEP=full) adds every other manifest route
 * with params filled in, still visited bare.
 */
export interface A11yScreen {
  readonly id: string;
  readonly path: string;
  /** A guarded screen: the role the /me stub answers with, and the h1 the screen must render. */
  readonly signedIn?: { readonly role: MeOptions["role"]; readonly heading: string } | undefined;
}

export const PR_IDS: ReadonlySet<string> = new Set(["R-001", "R-901", "R-902", "R-903"]);

const SIGNED_IN = new Map<string, NonNullable<A11yScreen["signedIn"]>>([
  ["R-201", { role: "owner", heading: "Security settings" }],
  ["R-202", { role: "owner", heading: "Hotkeys" }],
  ["R-203", { role: "owner", heading: "Appearance" }],
  ["R-300", { role: "owner", heading: "Overview" }], // SCR-120 (E42-S01), its reads stubbed
]);

export const FULL = process.env["A11Y_SWEEP"] === "full";

const screenOf = (e: ManifestEntry): A11yScreen => ({
  id: e.id,
  path: e.path.replace(/:[A-Za-z]+/g, "x"),
});

// A signed-in id is never in this list, in either mode: visited bare it would audit /login.
export const SCREENS: readonly A11yScreen[] = ROUTE_MANIFEST.filter(
  (e) => !SIGNED_IN.has(e.id) && (FULL || PR_IDS.has(e.id)),
).map(screenOf);

export const SIGNED_IN_SCREENS: readonly A11yScreen[] = ROUTE_MANIFEST.flatMap((e) => {
  const signedIn = SIGNED_IN.get(e.id);
  return signedIn ? [{ ...screenOf(e), signedIn }] : [];
});

export const REPORT_DIR = process.env["A11Y_REPORT_DIR"] ?? "../../reports/a11y";
