// @vitest-environment node
import { describe, expect, it } from "vitest";
import { diffTrees, normaliseTree } from "../e2e/a11y-nav/normalise";

/** E47-Q03 BQ-08 (a): the masking normaliser, seeded with sensitive strings. */
const SEEDED = [
  '- heading "Welcome back, alice.manager@example.com"',
  "- text: Account: alice-main",
  '- status: "Balance 12,345.67 USDT"',
  '- cell "$1,234.50"',
  '- cell "64250.5"',
  "- text: Order 3f2b8c1e-9d4a-4e6f-8a21-5b7c9d0e1f23 filled",
  "- text: Updated 2026-01-01T12:00:01Z, 12:00:01",
  "- text: key AbCd1234EfGh5678IjKl",
  '- button "Sign in"',
].join("\n");

describe("normaliseTree", () => {
  const out = normaliseTree(SEEDED);

  it.each([
    "alice.manager@example.com",
    "alice-main",
    "12,345.67",
    "1,234.50",
    "64250.5",
    "3f2b8c1e",
    "2026-01-01",
    "12:00:01",
    "AbCd1234EfGh5678IjKl",
  ])("leaves no trace of %s", (secret) => {
    expect(out).not.toContain(secret);
  });

  it("keeps structure, roles and ordinary names", () => {
    expect(out).toContain('- button "Sign in"');
    expect(out).toContain("Account: <account>");
    expect(out.split("\n")).toHaveLength(SEEDED.split("\n").length);
  });

  it("is idempotent", () => {
    expect(normaliseTree(out)).toBe(out);
  });

  it.each([
    '- heading "Account settings"',
    '- button "Create account"',
    '- link "Account"',
    "- text: Meets WCAG 2.2 level AA, SC 1.4.11",
  ])("keeps UI text %s", (line) => {
    expect(normaliseTree(line)).toBe(line);
  });

  it("masks an account value only when it looks like an id", () => {
    expect(normaliseTree("- text: Account #4471")).toBe("- text: Account #<account>");
    expect(normaliseTree("- text: acct sub-77")).toBe("- text: acct <account>");
    expect(normaliseTree("- text: Account: Main")).toBe("- text: Account: <account>");
  });

  it("does not mask level markers or plain words", () => {
    const t = '- heading "Sign in to CandleViewer" [level=1]';
    expect(normaliseTree(t)).toBe(t);
  });
});

describe("diffTrees", () => {
  const base = ["- main:", '  - button "Save"', '  - link "Docs"'].join("\n");

  it("reports no change for equal trees", () => {
    expect(diffTrees(base, base)).toEqual({ changed: false, lines: [], nameLosses: [] });
  });

  it("flags the icon-only refactor as a name loss", () => {
    const next = ["- main:", "  - button", '  - link "Docs"'].join("\n");
    const d = diffTrees(base, next);
    expect(d.changed).toBe(true);
    expect(d.nameLosses).toEqual(['button "Save" lost its accessible name']);
    expect(d.lines).toContain("- " + '  - button "Save"');
    expect(d.lines.at(-1)).toContain("! NAME LOST");
  });

  it("shows an added node as a plus line without a name loss", () => {
    const d = diffTrees(base, `${base}\n  - button "New"`);
    expect(d.lines).toEqual(['+   - button "New"']);
    expect(d.nameLosses).toEqual([]);
  });
});
