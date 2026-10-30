/**
 * The `vr:update` gate on the mode Playwright resolved (gate.ts): it runs once before any test, with the
 * config every CLI spelling of the update flag has already been applied to.
 */
import type { FullConfig } from "playwright/test";
import { assertModeAllowed } from "./gate.js";

export default function globalSetup(config: FullConfig): void {
  assertModeAllowed(config.updateSnapshots, process.env);
}
