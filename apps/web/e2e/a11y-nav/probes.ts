import type { Locator, Page } from "@playwright/test";

/**
 * One probe per unmounted surface (BQ-05 (a)): the keys and the role/name the plan's expected result needs. Each
 * asserts the surface is absent (`not.toBeVisible`), so the day it lands the probe goes red with its ticket's
 * name and the case moves to a real journey. Keys are Playwright chords; Ctrl+Tab is never driven (reserved for
 * the browser, reserved-keys.json) and no F6 row exists in the keymap yet. Every `find` is a role plus an
 * accessible name, never CSS or a test id (checked in test/e2e-a11y-coverage.test.ts).
 */
export interface Probe {
  readonly cases: readonly number[];
  /** The remediation ticket; equals `where` in cases.json. */
  readonly ticket: string;
  readonly path: string;
  readonly keys?: readonly string[];
  readonly find: (page: Page) => Locator;
}

export const PROBES: readonly Probe[] = [
  {
    cases: [101],
    ticket: "E47-S05",
    path: "/terminal",
    find: (p) => p.getByRole("link", { name: "Skip to chart" }),
  },
  {
    cases: [103],
    ticket: "#5280",
    path: "/terminal",
    keys: ["Control+k"],
    find: (p) => p.getByRole("combobox", { name: /command/i }),
  },
  {
    cases: [105],
    ticket: "E15 story",
    path: "/terminal",
    keys: ["Control+Backslash"],
    find: (p) => p.getByRole("region", { name: /chart/i }),
  },
  {
    cases: [106, 202],
    ticket: "E47-S01",
    path: "/terminal",
    find: (p) => p.getByRole("img", { name: /chart, \d+ bars visible/ }),
  },
  {
    cases: [107],
    ticket: "E47-S05",
    path: "/terminal",
    find: (p) => p.getByRole("toolbar", { name: /drawing/i }),
  },
  {
    cases: [108],
    ticket: "E47-S02",
    path: "/terminal",
    find: (p) => p.getByRole("grid", { name: /ladder/i }),
  },
  {
    cases: [109],
    ticket: "E10-S05",
    path: "/terminal",
    find: (p) => p.getByRole("form", { name: /order ticket/i }),
  },
  {
    cases: [111],
    ticket: "E47-S03",
    path: "/rules/new",
    find: (p) => p.getByRole("form", { name: /rule/i }),
  },
  {
    cases: [112],
    ticket: "E47-S03",
    path: "/rules/x/graph",
    find: (p) => p.getByRole("application", { name: /rule graph/i }),
  },
  {
    cases: [113],
    ticket: "E47-S08",
    path: "/admin/users",
    find: (p) => p.getByRole("grid", { name: /users/i }),
  },
  {
    cases: [116],
    ticket: "E47-S08",
    path: "/terminal",
    keys: ["Control+Shift+K"],
    find: (p) => p.getByRole("alertdialog", { name: /freeze/i }),
  },
  {
    cases: [301, 302, 303, 304, 305],
    ticket: "E47-S01",
    path: "/terminal",
    keys: ["Alt+T"],
    find: (p) => p.getByRole("table", { name: /bar/i }),
  },
  {
    cases: [307, 308],
    ticket: "E47-S02",
    path: "/terminal",
    keys: ["Alt+T"],
    find: (p) => p.getByRole("table", { name: /profile|ladder/i }),
  },
  {
    cases: [309],
    ticket: "E47-S01",
    path: "/terminal",
    find: (p) => p.getByRole("button", { name: /table/i }),
  },
  {
    cases: [507],
    ticket: "E47-S04",
    path: "/replay/x",
    find: (p) => p.getByRole("button", { name: /pause/i }),
  },
];
