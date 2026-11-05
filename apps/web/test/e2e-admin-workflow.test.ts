// @vitest-environment node
import { readFileSync, readdirSync } from "node:fs";
import { join, resolve } from "node:path";
import { describe, expect, it } from "vitest";

/**
 * E42-Q02 (#1215) part 1: the admin lane's workflow, pinned where its review rests (C-10.2): it
 * starts on the nightly or a dispatch, never on a pull request; it reads no repository secret and
 * runs on a GitHub-hosted runner; its test job holds `contents: read` alone and only the report job
 * can write issues; its stack is testnet on loopback; each seed is masked; and no file leaves the
 * run before the scrub check has passed. The repo-wide workflow tests pin the rest (in
 * `scripts/tests`: the action pins, the web build guard, the report job in test_nightly_issue.py).
 */
const text = readFileSync(
  resolve(import.meta.dirname, "../../../.github/workflows/e2e-admin-real.yml"),
  "utf8",
);
/** The one job's steps, each as its own text. */
const steps = text
  .slice(text.indexOf("\n    steps:\n"))
  .split(/^ {6}- /mu)
  .slice(1);
const step = (name: string): string => {
  const found = steps.filter((s) => s.includes(`name: ${name}\n`));
  expect(found, name).toHaveLength(1);
  return found[0] ?? "";
};

describe("the admin lane's workflow", () => {
  it("starts on the nightly or a dispatch, never on a pull request or a label", () => {
    const on = text.slice(text.indexOf("\non:\n") + 1, text.indexOf("\npermissions:"));
    expect(on.trim().split("\n")).toEqual([
      "on:",
      "  schedule:",
      '    - cron: "39 3 * * *"',
      "  workflow_dispatch: {}",
    ]);
    expect(text).not.toMatch(/pull_request|run-admin-real|github\.event\.label/u);
  });

  it("holds contents: read, and issues: write on the report job alone", () => {
    const held = [...text.matchAll(/^ *([a-z-]+): (read|write)$/gmu)].map((m) => m[0].trim());
    expect(held).toEqual(["contents: read", "contents: read", "issues: write"]);
    const report = text.slice(text.indexOf("\n  report:\n"));
    expect(report).toContain("\n    permissions:\n      issues: write\n");
    expect(report).toContain("\n    uses: ./.github/workflows/_nightly-issue.yml\n");
  });

  it("reads no repository secret and runs on a GitHub-hosted runner alone", () => {
    expect(text).not.toMatch(/\$\{\{\s*secrets\./u);
    expect([...text.matchAll(/^ *runs-on: *(.*)$/gmu)].map((m) => m[1])).toEqual(["ubuntu-latest"]);
  });

  it("builds a testnet stack on loopback and runs the admin config against it", () => {
    expect([...text.matchAll(/CV_ENVIRONMENT: (\w+)/gu)].map((m) => m[1])).toEqual([
      "testnet",
      "testnet",
    ]);
    expect(text).toContain("CV_E2E_REAL_API: http://127.0.0.1:8000");
    expect(step("The admin lane (playwright.admin-stack.config.ts)")).toContain(
      "run: npx playwright test -c e2e/playwright.admin-stack.config.ts",
    );
  });

  it("seeds each user by role with a TOTP method of its own, and masks every seed", () => {
    const seed = step(
      "Migrate, then seed the fixture users by role, each with a TOTP method of its own (testnet)",
    );
    expect(seed).toContain('--role "$role"');
    expect(seed).toContain('--totp-secret-out "$RUNNER_TEMP/cv/e2e-$role-$i.totp"');
    expect(seed).toContain('echo "::add-mask::$(cat "$RUNNER_TEMP/cv/e2e-$role-$i.totp")"');
  });

  it("uploads nothing until the scrub check of the artefacts has passed", () => {
    const uploads = steps.filter((s) => s.includes("uses: actions/upload-artifact@"));
    expect(uploads).toHaveLength(2);
    for (const upload of uploads) {
      expect(upload).toMatch(
        /if: \$\{\{ (?:failure|always)\(\) && steps\.scrub\.outcome == 'success' \}\}/u,
      );
    }
    const scrub = step(
      "Scrub check, no credential of this run in the artefacts (else nothing is uploaded)",
    );
    expect(scrub).toContain("id: scrub");
    expect(scrub).toContain("python3 -I security/zap/check_artefact_secrets.py");
  });

  it("seeds at least as many users of each role as the admin specs claim in a run", () => {
    // A user is claimed once per run (`support/real/stack.ts`), so the specs' claims add up. A
    // claim is an actor opened, or a user taken, with the role written out: `(lane, "manager"`
    // or `lane.user("viewer")`. One in a loop would be counted once: the specs keep none.
    const e2e = resolve(import.meta.dirname, "../e2e");
    const all = (dir: string): string[] =>
      readdirSync(dir, { withFileTypes: true }).flatMap((e) =>
        e.isDirectory() ? all(join(dir, e.name)) : [join(dir, e.name)],
      );
    const claims = { owner: 0, manager: 0, viewer: 0 };
    const CLAIM = /\(lane, "(owner|manager|viewer)"|\blane\.user\("(owner|manager|viewer)"\)/gu;
    for (const spec of all(e2e).filter((f) => f.endsWith(".stack.ts"))) {
      for (const m of readFileSync(spec, "utf8").matchAll(CLAIM)) {
        claims[(m[1] ?? m[2]) as keyof typeof claims] += 1;
      }
    }
    const seeded = Object.fromEntries(
      [...text.matchAll(/^ +FIXTURE_(OWNER|MANAGER|VIEWER)S: "(\d+)"$/gmu)].map((m) => [
        (m[1] ?? "").toLowerCase(),
        Number(m[2]),
      ]),
    );
    expect(Object.keys(seeded).sort()).toEqual(["manager", "owner", "viewer"]);
    expect(claims.owner).toBeGreaterThan(0);
    for (const role of ["owner", "manager", "viewer"] as const) {
      expect(claims[role], `${role}s claimed against seeded`).toBeLessThanOrEqual(
        seeded[role] ?? 0,
      );
    }
  });
});
