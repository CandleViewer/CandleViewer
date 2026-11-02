import type { CSSProperties, JSX } from "react";
import { InlineSpinnerText } from "@candleviewer/ui";
import { ScreenRoot } from "./ScreenRoot";

/** Its own frame: the shell, which paints `color.surface.app`, is not mounted yet (#4927's shell-less page rule). */
const PAGE: CSSProperties = {
  position: "fixed",
  inset: 0,
  padding: "var(--space-inset-lg)",
  background: "var(--color-surface-app)",
  color: "var(--color-text-primary)",
};

/**
 * The shell route's `HydrateFallback` (A-5335-d06): what a first visit to a lazy screen (`LAZY_SCREENS` in
 * `routes/tree.tsx`) draws while its chunk loads, instead of nothing. CMP-038 with SCR-150's words (E10-D03 §9.3: the
 * label, and after 5 s the slow-boot line), one polite status, never a bare spinner. It is not the shell: the route
 * guard runs with the chunk's load, and the shell's chrome waits for it, so a signed-out visit never sees the shell.
 */
export function ShellLoading(): JSX.Element {
  return (
    <ScreenRoot style={PAGE}>
      <InlineSpinnerText label="Loading" slowLabel="Still loading… the server is slow to answer" />
    </ScreenRoot>
  );
}
