/**
 * The nav rail's links per role, in rail order (`src/features/app-shell/navItems.ts`, filtered by
 * the route manifest's access). Shared by the shell e2e and the shell-mode matrix test.
 */
export const RAIL = {
  owner: ["Terminal", "Rules", "Journal", "Replay", "Alerts", "Settings", "Admin"],
  manager: ["Terminal", "Rules", "Journal", "Replay", "Alerts", "Settings"],
  viewer: ["Terminal", "Journal", "Replay", "Alerts", "Settings"],
} as const satisfies Readonly<Record<"owner" | "manager" | "viewer", readonly string[]>>;
