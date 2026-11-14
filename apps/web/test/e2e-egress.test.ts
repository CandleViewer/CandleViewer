// @vitest-environment node
import { readFileSync, readdirSync } from "node:fs";
import { join, relative, resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { isLocal } from "@candleviewer/fixtures/e2e";

/**
 * E49-Q01 (#1335 BQ-6), the static half of the e2e egress rule (C-13.5; 03-testing-strategy §11.4).
 * The runtime guard aborts a non-loopback request while a spec runs; this check fails earlier, on
 * the source, and covers the specs the guard is not applied to. Error code CI-E2E-005.
 *
 * 1. No e2e source under `apps/web/e2e` or `apps/desktop/e2e` holds a URL literal whose host is not
 *    local by `isLocal`, the one pattern rule (`egress.ts`); there is no second host list. A host
 *    built by concatenation fails like a templated one. A URL the test never fetches may carry
 *    `// e2e-egress: <reason>` alone on the line above it, and the marker only passes a reserved
 *    name (RFC 2606 / RFC 6761, `RESERVED_HOST`): it is no second
 *    allowlist. `bybit.com` and `bytick.com` are refused in a URL or in a host-shaped string (a
 *    route glob), with or without a marker and whatever the allowlist holds.
 * 2. A pack spec (one whose source carries the pack's title tag, in any file a Playwright config
 *    matches) runs behind the guard: a web pack spec takes `test` from `e2e/support/pack.ts`; a
 *    desktop pack spec launches and closes through `support/shell.ts` (`launchShell` sets up the
 *    Electron half, `closeShell` asserts it saw nothing leave). Neither takes `test` or
 *    `_electron` from Playwright directly. Sockets opened inside a shared or service worker are
 *    outside both halves of the guard; that limit is a row in the pack's coverage map.
 */

/** Hosts a source may name besides the local pattern. Kept empty: an entry needs the security CODEOWNER. */
const ALLOWED_HOSTS: readonly string[] = [];
/** Never reachable from a test, whatever the allowlist or a marker says (C-13.5). */
const REFUSED_DOMAINS = ["bybit.com", "bytick.com"] as const;
const PACK_TAG = "@ga-regression";
/** A marker counts only on a line that holds nothing but the comment. */
const MARKER = /^\/\/\s*e2e-egress:\s*(\S.{9,})$/u;
/** Reserved names: the only hosts a marker may pass (RFC 2606, RFC 6761). */
const RESERVED_HOST =
  /(?:^|\.)(?:invalid|test|example|local|localhost|example\.(?:com|net|org))$/iu;

interface Suite {
  readonly name: string;
  readonly dir: string;
  /** What a pack spec in this suite must import, and what it must not. */
  readonly packMust: readonly ImportRule[];
  readonly packMustNot: ImportRule;
}

interface ImportRule {
  readonly name: string;
  readonly from: RegExp;
}

const PLAYWRIGHT = /^(?:@playwright\/test|playwright)$/u;
const SHELL = /(?:^|\/)support\/shell$/u;
const SUITES: readonly Suite[] = [
  {
    name: "web",
    dir: resolve(import.meta.dirname, "../e2e"),
    packMust: [{ name: "test", from: /(?:^|\/)support\/pack$/u }],
    packMustNot: { name: "test", from: PLAYWRIGHT },
  },
  {
    name: "desktop",
    dir: resolve(import.meta.dirname, "../../desktop/e2e"),
    packMust: [
      { name: "launchShell", from: SHELL },
      { name: "closeShell", from: SHELL },
    ],
    packMustNot: { name: "_electron", from: PLAYWRIGHT },
  },
];

const SKIP_DIRS = new Set(["node_modules", "playwright-report", "test-results"]);

function sources(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
    const path = join(dir, e.name);
    if (e.isDirectory()) return SKIP_DIRS.has(e.name) ? [] : sources(path);
    return /\.[cm]?[jt]sx?$/u.test(e.name) ? [path] : [];
  });
}

const URL_LITERAL = /\b(?:https?|wss?):\/\/(?:\[[^\]\s]*\][^\s"'`/?#)<>\\]*|[^\s"'`/?#)<>\\]+)/giu;
/** A scheme whose host is concatenated in (`"https://" + host`), so no reader knows it. */
const CONCAT_HOST = /\b(?:https?|wss?):\/\/["'`]\s*\+/giu;
/** An exchange domain outside a URL literal but placed as a host: after `/` or `*`, before `/` or `:`. */
const BARE_REFUSED =
  /(?<=[/*])(?:[\w-]+\.)*(?:bybit|bytick)\.com\b|(?<![\w.-])(?:[\w-]+\.)*(?:bybit|bytick)\.com(?=[/:])/giu;
/**
 * Files a Playwright config matches (`testMatch` across both suites, Playwright's default `.spec.` and
 * `.test.`, and the exploratory `.explore.ts`): the ones a pack tag can enlist.
 */
const SPEC_FILE = /\.(?:spec|test|real|perf|collect|nightly|flagged|explore)\.[cm]?[jt]sx?$/u;

/** A literal as `isLocal` reads it: each `${...}` part becomes `0`, so a templated host fails. */
const untemplated = (literal: string): string => literal.replace(/\$\{[^}]*(?:\}|$)/gu, "0");

function hostOf(url: string): string {
  try {
    return new URL(url).hostname;
  } catch {
    return "<unparsable>";
  }
}

const refused = (host: string): boolean =>
  REFUSED_DOMAINS.some((d) => host.toLowerCase() === d || host.toLowerCase().endsWith(`.${d}`));

/** Each URL or host in `source` that the rule fails, as `line N: <scheme>//<host>`. */
function remoteUrls(source: string, allowed: readonly string[] = ALLOWED_HOSTS): string[] {
  const lines = source.split("\n");
  return lines.flatMap((line, i) => {
    const at = `line ${i + 1}:`;
    const marked = MARKER.test(lines[i - 1]?.trim() ?? "");
    const literals = [...line.matchAll(URL_LITERAL)].flatMap(([literal]) => {
      const url = untemplated(literal);
      const host = hostOf(url);
      if (refused(host)) return [`${at} ${literal} (refused domain)`];
      if (isLocal(url) || allowed.includes(host)) return [];
      if (marked && RESERVED_HOST.test(host)) return [];
      return [`${at} ${literal}`];
    });
    const concat = [...line.matchAll(CONCAT_HOST)].map(([m]) => `${at} ${m} (templated host)`);
    const bare = [...line.replace(URL_LITERAL, " ").matchAll(BARE_REFUSED)].map(
      ([host]) => `${at} ${host} (refused domain)`,
    );
    return [...literals, ...concat, ...bare];
  });
}

interface Binding {
  readonly name: string;
  readonly from: string;
}

/** The value bindings a module imports by name (`import type` and inline `type` specifiers left out). */
function namedImports(source: string): Binding[] {
  const out: Binding[] = [];
  for (const m of source.matchAll(/import\s+(type\s+)?([^;]*?)\s+from\s+["']([^"']+)["']/gu)) {
    const [, typeOnly, clause = "", from = ""] = m;
    if (typeOnly !== undefined) continue;
    if (/^\*\s+as\s/u.test(clause)) out.push({ name: "*", from });
    for (const spec of /\{([^}]*)\}/u.exec(clause)?.[1]?.split(",") ?? []) {
      const name = spec.trim().split(/\s+as\s+/u)[0] ?? "";
      if (name !== "" && !name.startsWith("type ")) out.push({ name, from });
    }
  }
  return out;
}

/** Why a pack spec in `suite` is not behind the guard, or nothing. Specs without the tag pass. */
function packImportFindings(source: string, suite: Suite): string[] {
  if (!source.includes(PACK_TAG)) return [];
  const imports = namedImports(source);
  const takes = (rule: ImportRule): boolean =>
    imports.some((b) => (b.name === rule.name || b.name === "*") && rule.from.test(b.from));
  const findings: string[] = [];
  if (takes(suite.packMustNot))
    findings.push(`imports ${suite.packMustNot.name} from ${suite.packMustNot.from.source}`);
  for (const rule of suite.packMust)
    if (!takes(rule)) findings.push(`does not import ${rule.name} from ${rule.from.source}`);
  return findings;
}

const [WEB, DESKTOP] = SUITES as [Suite, Suite];

describe("the e2e egress check (E49-Q01, CI-E2E-005)", () => {
  it("keeps the committed host allowlist empty", () => {
    expect(ALLOWED_HOSTS, "CI-E2E-005: a non-empty allowlist needs the security CODEOWNER").toEqual(
      [],
    );
  });

  it("finds no remote URL literal in any e2e source", () => {
    const findings = SUITES.flatMap((s) =>
      sources(s.dir).flatMap((file) =>
        remoteUrls(readFileSync(file, "utf8")).map((f) => `${relative(s.dir, file)} ${f}`),
      ),
    );
    expect(findings, "CI-E2E-005: an e2e source names a host past loopback").toEqual([]);
  });

  it("finds every pack spec behind the egress guard", () => {
    const findings = SUITES.flatMap((s) =>
      sources(s.dir)
        .filter((file) => SPEC_FILE.test(file))
        .flatMap((file) =>
          packImportFindings(readFileSync(file, "utf8"), s).map(
            (f) => `${s.name} ${relative(s.dir, file)}: ${f}`,
          ),
        ),
    );
    expect(findings, "CI-E2E-005: a pack spec runs outside the egress guard").toEqual([]);
  });

  it("scans both suites and sees the web pack export", () => {
    for (const s of SUITES) expect(sources(s.dir).length).toBeGreaterThan(5);
    const pack = readFileSync(join(WEB.dir, "support/pack.ts"), "utf8");
    expect(namedImports(pack.replace(/^export\s/mu, "import "))).toEqual([
      { name: "expect", from: "../shell/fixtures" },
      { name: "test", from: "../shell/fixtures" },
    ]);
  });
});

describe("remoteUrls", () => {
  it("passes loopback hosts, a templated port and schemes that never leave the process", () => {
    const src = [
      'const a = "http://127.0.0.1:4173/x";',
      "const b = `ws://localhost:${port}/ws`;",
      'const c = "https://[::1]:8443/";',
      'const d = "app://bundle/index.html";',
    ].join("\n");
    expect(remoteUrls(src)).toEqual([]);
  });

  it("fails a host that only starts like a loopback one", () => {
    expect(remoteUrls('const u = "http://[::1].example.org/";')).toEqual([
      "line 1: http://[::1].example.org",
    ]);
  });

  it("fails a remote host, a templated host and an unmarked problem type id", () => {
    const src = [
      'await page.goto("https://example.org/");',
      "const u = `http://${host}:80/`;",
      'type: "https://candleviewer.local/errors/x",',
    ].join("\n");
    expect(remoteUrls(src)).toEqual([
      "line 1: https://example.org",
      "line 2: http://${host}:80",
      "line 3: https://candleviewer.local",
    ]);
  });

  it("passes a marked reserved name, but only on the line right below the marker", () => {
    const src = [
      "// e2e-egress: an RFC 7807 problem type id, never fetched",
      'type: "https://candleviewer.local/errors/x",',
      'next: "https://candleviewer.local/errors/y",',
    ].join("\n");
    expect(remoteUrls(src)).toEqual(["line 3: https://candleviewer.local"]);
  });

  it("skips a scheme with no host, as in an error message", () => {
    expect(remoteUrls('throw new Error("must be an http:// loopback origin");')).toEqual([]);
  });

  it("fails a marked real host: the marker passes only reserved names", () => {
    const src = [
      "// e2e-egress: a stylesheet probe the CSP refuses",
      'link.href = "https://cdn.jsdelivr.net/x.css";',
      "// e2e-egress: a window.open probe the shell denies",
      'win.open("https://example.com", "_blank"); win.open("https://styles.invalid/");',
    ].join("\n");
    expect(remoteUrls(src)).toEqual(["line 2: https://cdn.jsdelivr.net"]);
  });

  it("does not take a marker that trails code on its line", () => {
    const src = [
      "go(); // e2e-egress: a problem type id, never fetched",
      'const u = "https://x.test/";',
    ];
    expect(remoteUrls(src.join("\n"))).toEqual(["line 2: https://x.test"]);
  });

  it("fails a host built by concatenation, marked or not", () => {
    const src = ["// e2e-egress: a problem type id, never fetched", 'const u = "https://" + host;'];
    expect(remoteUrls(src.join("\n"))).toEqual(['line 2: https://" + (templated host)']);
  });

  it("refuses an exchange domain placed as a host outside a URL, not a name in a list", () => {
    const src = [
      'await page.route("**/api.bybit.com/**", stub);',
      'const host = "stream.bytick.com:443";',
      'for (const h of ["api.bybit.com", "api.bytick.com"]) expect(csp).not.toContain(h);',
    ].join("\n");
    expect(remoteUrls(src)).toEqual([
      "line 1: api.bybit.com (refused domain)",
      "line 2: stream.bytick.com (refused domain)",
    ]);
  });

  it("does not take a marker with no reason", () => {
    const src = ["// e2e-egress:", 'const u = "https://example.org/";'].join("\n");
    expect(remoteUrls(src)).toEqual(["line 2: https://example.org"]);
  });

  it("refuses the exchange's domains with a marker, in the allowlist, in any case", () => {
    const src = [
      "// e2e-egress: a recorded fixture said this was fine",
      'const a = "https://api.BYBIT.com/v5/market";',
      'const b = "wss://stream.bytick.com/v5/public/linear";',
    ].join("\n");
    expect(remoteUrls(src, ["api.bybit.com", "stream.bytick.com"])).toEqual([
      "line 2: https://api.BYBIT.com (refused domain)",
      "line 3: wss://stream.bytick.com (refused domain)",
    ]);
  });

  it("passes an allowlisted host", () => {
    expect(remoteUrls('const u = "https://mirror.example/";', ["mirror.example"])).toEqual([]);
  });
});

describe("packImportFindings", () => {
  const TAGGED = 'test("@ga-regression @ga-area-shell the badge shows", async () => {});';

  it("passes an untagged spec whatever it imports", () => {
    expect(packImportFindings('import { test } from "@playwright/test";', WEB)).toEqual([]);
  });

  it("passes a web pack spec that takes test from the pack export", () => {
    const src = ['import { expect, test } from "../support/pack";', TAGGED].join("\n");
    expect(packImportFindings(src, WEB)).toEqual([]);
  });

  it("fails a web pack spec that takes test straight from @playwright/test", () => {
    const src = ['import { test, expect } from "@playwright/test";', TAGGED].join("\n");
    expect(packImportFindings(src, WEB)).toEqual([
      "imports test from ^(?:@playwright\\/test|playwright)$",
      "does not import test from (?:^|\\/)support\\/pack$",
    ]);
  });

  it("fails a renamed or namespace import from @playwright/test, and passes a type-only one", () => {
    const renamed = [
      'import { test as base } from "@playwright/test";',
      'import { test } from "../support/pack";',
      TAGGED,
    ].join("\n");
    expect(packImportFindings(renamed, WEB)).toEqual([
      "imports test from ^(?:@playwright\\/test|playwright)$",
    ]);
    const ns = [
      'import * as pw from "@playwright/test";',
      'import { test } from "./support/pack";',
    ];
    expect(packImportFindings([...ns, TAGGED].join("\n"), WEB)).toHaveLength(1);
    const types = [
      'import type { Page } from "@playwright/test";',
      'import { type Locator, test } from "../support/pack";',
      TAGGED,
    ].join("\n");
    expect(packImportFindings(types, WEB)).toEqual([]);
  });

  it("fails a desktop pack spec that launches Electron itself, from either package", () => {
    const src = [
      'import { _electron as electron, test } from "@playwright/test";',
      'import { closeShell, launchShell } from "./support/shell";',
      TAGGED,
    ].join("\n");
    expect(packImportFindings(src, DESKTOP)).toEqual([
      "imports _electron from ^(?:@playwright\\/test|playwright)$",
    ]);
    const perf = ['import { _electron } from "playwright";', TAGGED].join("\n");
    expect(packImportFindings(perf, DESKTOP)).toEqual([
      "imports _electron from ^(?:@playwright\\/test|playwright)$",
      "does not import launchShell from (?:^|\\/)support\\/shell$",
      "does not import closeShell from (?:^|\\/)support\\/shell$",
    ]);
  });

  it("fails a desktop pack spec that never closes through support/shell", () => {
    const src = ['import { launchShell } from "./support/shell";', TAGGED].join("\n");
    expect(packImportFindings(src, DESKTOP)).toEqual([
      "does not import closeShell from (?:^|\\/)support\\/shell$",
    ]);
  });

  it("reads every file a Playwright config matches, and no support module", () => {
    for (const f of [
      "a.spec.ts",
      "b.real.ts",
      "perf/cold-start.perf.ts",
      "a11y/x.collect.ts",
      "c.test.ts",
      "exploratory/run-1.explore.ts",
    ])
      expect(SPEC_FILE.test(f), f).toBe(true);
    for (const f of ["support/pack.ts", "support/shell.ts", "playwright.config.ts"])
      expect(SPEC_FILE.test(f), f).toBe(false);
  });

  it("passes a desktop pack spec that launches through support/shell", () => {
    const src = [
      'import { test, expect } from "@playwright/test";',
      'import { closeShell, launchShell } from "./support/shell";',
      TAGGED,
    ].join("\n");
    expect(packImportFindings(src, DESKTOP)).toEqual([]);
  });
});
