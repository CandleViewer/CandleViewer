/**
 * Named regions every screen must expose (E47-S05, `05-accessibility-standard.md` §3.4 rule 1), as lines of Playwright's
 * ARIA snapshot. A public screen (no session, no shell) renders its own `main`; a signed-in screen renders the shell's
 * five landmarks, the two repeated kinds carrying a name so a reader can tell them apart.
 */
export const PUBLIC_REGIONS: readonly string[] = ["- main:"];
export const SHELL_REGIONS: readonly string[] = [
  "- banner:",
  '- navigation "Primary":',
  "- main:",
  '- complementary "Side panels":',
  "- contentinfo:",
];

/** The shell's landmarks in the order `Ctrl+\` visits them (DOM order). */
export const SHELL_RING: readonly string[] = [
  "banner",
  "navigation",
  "main",
  "complementary",
  "contentinfo",
];

/** Region lines a snapshot lacks (a line is matched at top level, two-space indent excluded). */
export function missingRegions(tree: string, expected: readonly string[]): string[] {
  const top = new Set(tree.split("\n").filter((l) => l.startsWith("- ")));
  return expected.filter((r) => !top.has(r));
}
