// E10-Q03 (#302) shell axe matrix, driver A. E47-T01 swept the shell rows at one density and one motion
// state and counted only what it flagged; this drives the REAL routes of the built web app (`vite
// preview`, loopback only) through ~16 shell states x 3 themes x 2 densities x 2 motion states
// (reduced-motion no-preference / reduce), counts EVERY axe impact (critical, serious, moderate, minor)
// with the AXE_GATE_TAGS plus best-practice, colour-contrast on, and no rule disabled. A must-trip
// negative control runs first (project `control`; the run fails as A11Y-INFRA if it does not trip).
// The LIVE session is a driver-local /api/v1/me stub (session.environment = "live"); no fixture change.
//
// Electron leg (BQ-5): A11Y_TARGET=electron launches the built desktop shell through `_electron` against
// the same `vite preview` (CV_DEV_SERVER_URL), a reduced matrix (3 themes x 2 densities, no motion axis:
// the OS media query cannot be set on an Electron window) over the states marked `electron`. axe runs
// through @axe-core/playwright first; if that throws on Electron, axe-core's source is evaluated into the page over CDP (addScriptTag is refused by the app's CSP)
// and the cell records `axeVia: "inject"` (the deviation is listed in the report).
//
// Build, then run from apps/web (its Playwright and axe are the runners; the tsconfig here maps them, no
// new dependency):
//   pnpm turbo run build --filter=@candleviewer/web && pnpm --filter @candleviewer/desktop build
//   cd apps/web && A11Y_SHA=$(git rev-parse HEAD) A11Y_OUT=<dir> \
//     npx playwright test -c ../../docs/plan/a11y/_tools/e10-q03-shell.config.ts
//   cd apps/web && A11Y_TARGET=electron A11Y_OUT=<dir> xvfb-run -a \
//     npx playwright test -c ../../docs/plan/a11y/_tools/e10-q03-shell.config.ts
//   node docs/plan/a11y/_tools/e10-q03-shell-merge.mjs <dir>   # states/*.json -> results.json.gz + summary.md
// Environment: A11Y_TARGET (web | electron), A11Y_SHA, A11Y_OUT, A11Y_PORT (default 4186), A11Y_ONLY
// (comma-separated state ids), A11Y_THEMES, A11Y_DENSITIES, A11Y_WORKERS. Network: every request to a
// host other than loopback is aborted and counted; a state with one fails.
import { mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import AxeBuilder from "@axe-core/playwright";
import {
  _electron as electron,
  expect,
  test,
  type Browser,
  type BrowserContext,
  type ElectronApplication,
  type Page,
} from "@playwright/test";
import type * as ApiModule from "../../../../apps/web/e2e/support/api";
import type * as WsModule from "../../../../apps/web/e2e/support/wsHarness";
import type * as TagsModule from "../../../../apps/web/e2e/a11y/tags";
import type { GatewayOptions, WsHarness } from "../../../../apps/web/e2e/support/wsHarness";

// apps/web's e2e support is ESM and this directory is CommonJS: load it dynamically (as e47-sweep does).
let json: (typeof ApiModule)["json"];
let stubSession: (typeof ApiModule)["stubSession"];
let installWsHarness: (typeof WsModule)["installWsHarness"];
let AXE_GATE_TAGS: (typeof TagsModule)["AXE_GATE_TAGS"];
test.beforeAll(async () => {
  const api = await import("../../../../apps/web/e2e/support/api");
  const ws = await import("../../../../apps/web/e2e/support/wsHarness");
  const tags = await import("../../../../apps/web/e2e/a11y/tags");
  ({ json, stubSession } = api);
  ({ installWsHarness } = ws);
  ({ AXE_GATE_TAGS } = tags);
});

const ENV = process.env;
const TARGET = ENV["A11Y_TARGET"] === "electron" ? "electron" : "web";
const PORT = ENV["A11Y_PORT"] ?? "4186";
const ORIGIN = `http://127.0.0.1:${PORT}`;
const REPO = resolve(__dirname, "../../../..");
const OUT = resolve(ENV["A11Y_OUT"] ?? join(tmpdir(), "e10-q03-shell"), TARGET);
const W = 10_000; // one step of one state: a state that never settles fails by name, not at the test timeout
const IMPACTS = ["critical", "serious", "moderate", "minor"] as const;
type Impact = (typeof IMPACTS)[number];

type Role = "owner" | "manager" | "viewer";
const THEMES = [
  { name: "dark", appearance: { theme: "dark", high_contrast: false } },
  { name: "light", appearance: { theme: "light", high_contrast: false } },
  { name: "high-contrast", appearance: { theme: "dark", high_contrast: true } },
] as const;
const DENSITIES = ["compact", "comfortable"] as const;
const MOTIONS = ["no-preference", "reduce"] as const;
const pick = <T extends { name: string } | string>(all: readonly T[], env: string | undefined) => {
  const asked = (env ?? "").split(",").filter((x) => x !== "");
  return asked.length === 0
    ? all
    : all.filter((x) => asked.includes(typeof x === "string" ? x : x.name));
};
const themes = pick(THEMES, ENV["A11Y_THEMES"]);
const densities = pick(DENSITIES, ENV["A11Y_DENSITIES"]);
const motions = TARGET === "electron" ? (["no-preference"] as const) : MOTIONS;

// Same frame as e2e/system-states/break-glass-notice.spec.ts (stub data, one SCR-153 row).
const NOTICE = {
  kind: "notice",
  severity: "critical",
  message: "Break-glass recovery was used on this server; the Owner must review it.",
  reason: "auth.break_glass_used",
};

interface State {
  readonly id: string;
  readonly scr: string;
  readonly path: string;
  readonly role?: Role;
  readonly live?: true; // /me answers session.environment = "live"
  readonly ws?: GatewayOptions | true;
  readonly welcome?: { readonly server_version?: string; readonly protocol?: string };
  readonly viewport?: { readonly width: number; readonly height: number };
  readonly stubs?: (page: Page) => Promise<void>;
  /** Reach the state; returns checks recorded next to the axe result. */
  readonly open: (page: Page, ws: WsHarness | undefined) => Promise<Record<string, unknown>>;
  readonly electron?: true;
}

const h1 = (p: Page) => p.getByRole("heading", { level: 1 }).first().waitFor({ timeout: W });
const main = (p: Page) => p.getByRole("main").first().waitFor({ timeout: W });
const rail = (p: Page) => p.getByRole("navigation", { name: "Primary" });
const toggle = (p: Page) => rail(p).getByRole("button", { name: /navigation rail$/u });
const polite = (p: Page) =>
  p.evaluate(() => {
    const el = document.querySelector('[aria-live="polite"][aria-atomic="true"] > p[data-seq]');
    return el === null ? null : { seq: Number(el.getAttribute("data-seq")), text: el.textContent };
  });

const plain = async (p: Page): Promise<Record<string, unknown>> => {
  await h1(p);
  return {};
};

/** A rail link focused after a key press, so the focus is :focus-visible and the echo shows at once. */
async function collapsedRail(p: Page): Promise<Record<string, unknown>> {
  await h1(p);
  const t = toggle(p);
  if ((await t.getAttribute("aria-expanded")) === "true") await t.click();
  await expect(t).toHaveAttribute("aria-expanded", "false", { timeout: W });
  await p.keyboard.press("Shift");
  await rail(p).getByRole("link").first().focus();
  const tip = p.locator('[role="tooltip"]:not([hidden])');
  await expect(tip).toHaveCount(1, { timeout: W });
  return {
    tooltipText: await tip.textContent(),
    tooltipAriaHidden: await tip.getAttribute("aria-hidden"),
    linkHasTitle: await rail(p).getByRole("link").first().getAttribute("title"),
  };
}

const STATES: readonly State[] = [
  {
    id: "chrome-owner",
    scr: "SCR-010",
    path: "/journal",
    role: "owner",
    ws: true,
    open: plain,
    electron: true,
  },
  { id: "chrome-viewer", scr: "SCR-010", path: "/journal", role: "viewer", ws: true, open: plain },
  {
    // LIVE session: the badge names it and the route change announces it once (polite, data-seq).
    id: "chrome-live",
    scr: "SCR-010",
    path: "/journal",
    role: "owner",
    live: true,
    ws: true,
    electron: true,
    open: async (p) => {
      await h1(p);
      const before = (await polite(p))?.seq ?? 0;
      await rail(p).getByRole("link", { name: "Replay", exact: true }).click();
      await expect(p).toHaveURL(/\/replay$/u);
      await expect
        .poll(async () => (await polite(p))?.seq ?? 0, { timeout: W })
        .toBeGreaterThan(before);
      const badge = p.getByRole("banner").getByRole("img", { name: "Trading environment: Live" });
      await expect(badge).toBeVisible({ timeout: W });
      return { announce: (await polite(p))?.text ?? null, badgeCount: await badge.count() };
    },
  },
  {
    id: "rail-expanded",
    scr: "SCR-011",
    path: "/journal",
    role: "owner",
    ws: true,
    open: async (p) => {
      await h1(p);
      await expect(toggle(p)).toHaveAttribute("aria-expanded", "true", { timeout: W });
      return {};
    },
  },
  {
    id: "rail-collapsed",
    scr: "SCR-011",
    path: "/journal",
    role: "owner",
    ws: true,
    open: collapsedRail,
    electron: true,
  },
  {
    id: "rail-overlay-320",
    scr: "SCR-011",
    path: "/journal",
    role: "owner",
    ws: true,
    viewport: { width: 320, height: 640 },
    open: async (p) => {
      await h1(p);
      await toggle(p).click();
      await expect(toggle(p)).toHaveAttribute("aria-expanded", "true", { timeout: W });
      return {
        scrollsX: await p.evaluate(
          () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
        ),
      };
    },
  },
  {
    id: "drawer",
    scr: "SCR-014",
    path: "/journal",
    role: "owner",
    ws: true,
    electron: true,
    open: async (p) => {
      await h1(p);
      await p.getByRole("button", { name: "Notifications" }).click();
      await p.getByRole("group", { name: "Notifications" }).waitFor({ timeout: W });
      return {};
    },
  },
  {
    id: "cheatsheet",
    scr: "SCR-013",
    path: "/journal",
    role: "owner",
    ws: true,
    electron: true,
    open: async (p) => {
      await h1(p);
      await p.keyboard.press("Control+/");
      await p.getByRole("dialog", { name: "Keyboard shortcuts" }).waitFor({ timeout: W });
      return {};
    },
  },
  {
    id: "toast",
    scr: "SCR-015",
    path: "/journal",
    role: "owner",
    ws: true,
    electron: true,
    open: async (p) => {
      await h1(p);
      await p.getByTestId("toast-host").waitFor({ state: "attached", timeout: W });
      // An inert destructive binding explains itself with one toast (hotkeys.spec.ts); press until it shows.
      await expect(async () => {
        await p.keyboard.press("Control+Shift+X");
        await expect(
          p.getByRole("region", { name: "Notifications" }).getByRole("group").first(),
        ).toBeVisible({
          timeout: 250,
        });
      }).toPass({ timeout: W });
      return {};
    },
  },
  {
    id: "connection-down",
    scr: "SCR-152",
    path: "/journal",
    role: "owner",
    ws: true,
    electron: true,
    open: async (p, ws) => {
      await h1(p);
      if (ws) await expect.poll(() => ws.authenticated(), { timeout: W }).toBeGreaterThanOrEqual(1);
      ws?.kill();
      await p.getByRole("region", { name: "Connection" }).waitFor({ timeout: W });
      return {};
    },
  },
  {
    id: "degraded-banner",
    scr: "SCR-153",
    path: "/journal",
    role: "manager",
    ws: { firstAuthSystem: [NOTICE] },
    open: async (p) => {
      await h1(p);
      await p.getByRole("button", { name: `Dismiss ${NOTICE.message}` }).waitFor({ timeout: W });
      return {};
    },
  },
  {
    id: "version-banner",
    scr: "SCR-157",
    path: "/journal",
    role: "owner",
    ws: true,
    welcome: { server_version: "99.0.0" },
    open: async (p) => {
      await h1(p);
      await p.locator("[data-version-banner]").waitFor({ timeout: W });
      return {};
    },
  },
  {
    id: "version-dialog",
    scr: "SCR-157",
    path: "/journal",
    role: "owner",
    ws: true,
    welcome: { protocol: "cv.v0" }, // another protocol: `incompatible`, the blocking dialog
    open: async (p) => {
      await p.getByRole("alertdialog").or(p.getByRole("dialog")).first().waitFor({ timeout: W });
      return {};
    },
  },
  {
    id: "forbidden-403",
    scr: "SCR-154",
    path: "/403",
    role: "owner",
    ws: true,
    open: async (p) => (await main(p), {}),
  },
  {
    id: "not-found-404",
    scr: "SCR-155",
    path: "/404",
    role: "owner",
    ws: true,
    open: async (p) => (await main(p), {}),
    electron: true,
  },
  { id: "offline-page", scr: "SCR-159", path: "/offline", open: async (p) => (await main(p), {}) },
  {
    // Route level: an invites body with items = null makes AdminInviteScreen throw at render.
    id: "route-crash",
    scr: "SCR-156",
    path: "/admin/users/new",
    role: "owner",
    ws: true,
    stubs: async (p) => {
      await p.route("**/api/v1/users/invites", (r) => r.fulfill(json({ items: null })));
    },
    open: async (p) => {
      await p.getByRole("button", { name: /Reload page/ }).waitFor({ timeout: W });
      return {};
    },
  },
];

interface Cell {
  readonly state: string;
  readonly theme: string;
  readonly density: string;
  readonly motion: string;
  readonly applied: Record<string, string | null>;
  readonly axeVia: "playwright" | "inject";
  readonly counts: Record<Impact, number>;
  readonly violations: readonly { id: string; impact: string; nodes: number; targets: string[] }[];
  readonly incomplete: readonly { id: string; nodes: number; targets: string[] }[];
  readonly checks: Record<string, unknown>;
  readonly error?: string;
}

const firstLine = (e: unknown): string =>
  e instanceof Error ? (e.message.split("\n")[0] ?? "error") : String(e);

/** Letters of the stub names only: a stable, deterministic run needs every animation settled first. */
async function settle(page: Page): Promise<void> {
  // Bounded by the step bound W: an animation that never finishes fails the cell by name, not at the test timeout.
  await page.evaluate(async (ms) => {
    const settled = (async () => {
      await document.fonts.ready;
      await Promise.all(document.getAnimations().map((a) => a.finished.catch(() => undefined)));
    })();
    let timer: ReturnType<typeof setTimeout> | undefined;
    const deadline = new Promise<never>((_, reject) => {
      timer = setTimeout(
        () => reject(new Error(`settle: animations not finished within ${ms / 1000} s`)),
        ms,
      );
    });
    try {
      await Promise.race([settled, deadline]);
    } finally {
      clearTimeout(timer);
    }
  }, W);
  // The connection chip cross-fades its content on a status change (CMP-076, BQ-10) and the status can
  // change after the animations above were read: axe reads a half-faded word as low contrast. Wait for
  // every fading part to be fully opaque (bounded; a chip that never settles fails the cell).
  await page.waitForFunction(
    () =>
      [...document.querySelectorAll("[data-fade]")].every(
        (e) => getComputedStyle(e).opacity === "1",
      ),
    undefined,
    { timeout: W },
  );
}

type AxeResult = {
  violations: { id: string; impact?: string | null; nodes: { target: unknown[] }[] }[];
  incomplete: { id: string; nodes: { target: unknown[] }[] }[];
};
let injectNoted = false; // the deviation is logged once per worker

/** axe through @axe-core/playwright; on Electron, if that throws, axe-core injected into the page. */
async function runAxe(
  page: Page,
  tags: readonly string[],
): Promise<{ result: AxeResult; via: Cell["axeVia"] }> {
  try {
    return {
      result: await new AxeBuilder({ page }).withTags([...tags]).analyze(),
      via: "playwright",
    };
  } catch (error) {
    if (TARGET !== "electron") throw error;
    if (!injectNoted)
      console.log(`axe-via-playwright failed on Electron, injecting: ${firstLine(error)}`);
    injectNoted = true;
    const path = createRequire(
      createRequire(join(REPO, "apps/web/package.json")).resolve("@axe-core/playwright"),
    ).resolve("axe-core/axe.min.js");
    // addScriptTag is blocked by the app's strict CSP (script-src 'self'); evaluating the source over CDP is not.
    await page.evaluate(readFileSync(path, "utf8"));
    const result = await page.evaluate(
      (t) =>
        (window as unknown as { axe: { run: (c: object, o: object) => Promise<unknown> } }).axe.run(
          document,
          {
            runOnly: { type: "tag", values: t },
          },
        ),
      [...tags],
    );
    return { result: result as AxeResult, via: "inject" };
  }
}

const axeTags = (): string[] => [...AXE_GATE_TAGS, "best-practice"]; // read after beforeAll loaded it

async function readApplied(page: Page): Promise<Record<string, string | null>> {
  return page.evaluate(() => ({
    theme: document.documentElement.getAttribute("data-theme"),
    density: document.documentElement.getAttribute("data-density"),
    contrast: document.documentElement.getAttribute("data-contrast"),
    motion: document.documentElement.getAttribute("data-motion"),
    prefersReduced: matchMedia("(prefers-reduced-motion: reduce)").matches
      ? "reduce"
      : "no-preference",
  }));
}

/** CMP-076 chip (A11Y-F-0023, SC 1.4.11): border and fill contrast against the surface behind it. */
async function chipContrast(page: Page): Promise<Record<string, unknown>> {
  return page.evaluate(() => {
    const chip = document.querySelector<HTMLElement>("button[data-status]");
    if (chip === null) return { found: false };
    // Computed colours only (rgb() / rgba() / color(srgb ...)): no probe element, so no transition can skew it.
    const rgb = (css: string): [number, number, number, number] => {
      const n = (css.match(/-?[\d.]+/g) ?? []).map(Number);
      const k = css.startsWith("color(") ? 255 : 1;
      return [(n[0] ?? 0) * k, (n[1] ?? 0) * k, (n[2] ?? 0) * k, n[3] ?? 1];
    };
    const lum = ([r, g, b]: number[]): number => {
      const f = (v: number): number =>
        (v /= 255) <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
      return 0.2126 * f(r!) + 0.7152 * f(g!) + 0.0722 * f(b!);
    };
    const ratio = (a: number[], b: number[]): number => {
      const [x, y] = [lum(a), lum(b)];
      return Math.round(((Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05)) * 100) / 100;
    };
    let behind: HTMLElement | null = chip.parentElement;
    while (behind !== null && rgb(getComputedStyle(behind).backgroundColor)[3] === 0)
      behind = behind.parentElement;
    const bg = rgb(
      behind === null ? "rgb(255, 255, 255)" : getComputedStyle(behind).backgroundColor,
    );
    const cs = getComputedStyle(chip);
    const out = {
      found: true,
      border: `${cs.borderTopWidth} ${cs.borderTopStyle} ${cs.borderTopColor}`,
      surface: behind === null ? "none" : getComputedStyle(behind).backgroundColor,
      borderVsSurface: ratio(rgb(cs.borderTopColor), bg),
      fillVsSurface: ratio(rgb(cs.backgroundColor), bg),
    };
    return out;
  });
}

interface Opened {
  readonly page: Page;
  readonly ws: WsHarness | undefined;
  readonly close: () => Promise<void>;
  readonly offsite: string[];
}

/** Everything but the first load: stubs, harness, welcome rewrite, theme. */
async function prepare(
  page: Page,
  s: State,
  theme: (typeof THEMES)[number],
  density: string,
): Promise<WsHarness | undefined> {
  await page.unrouteAll({ behavior: "ignoreErrors" });
  if (s.role) {
    await stubSession(page, { role: s.role });
    if (s.live) {
      await page.route("**/api/v1/me", (r) =>
        r.fulfill(
          json({
            role: s.role,
            permissions: [],
            session: { environment: "live", elevated_until: null },
          }),
        ),
      );
    }
    await page.route("**/api/v1/me/preferences", (r) =>
      r.fulfill(json({ appearance: { ...theme.appearance, density } })),
    );
  } else {
    await page.route("**/api/v1/auth/refresh", (r) =>
      r.fulfill({
        status: 401,
        contentType: "application/problem+json",
        body: JSON.stringify({ title: "Unauthorized", status: 401 }),
      }),
    );
  }
  await s.stubs?.(page);
  if (s.welcome) {
    const welcome = s.welcome;
    const orig = page.routeWebSocket.bind(page);
    (page as unknown as { routeWebSocket: unknown }).routeWebSocket = (
      url: Parameters<Page["routeWebSocket"]>[0],
      handler: Parameters<Page["routeWebSocket"]>[1],
    ) =>
      orig(url, (ws) => {
        const send = ws.send.bind(ws);
        ws.send = (m: string | Buffer) => {
          if (typeof m === "string" && m.includes('"welcome"')) {
            const f = JSON.parse(m) as { t: string; p: Record<string, unknown> };
            if (f.t === "welcome") Object.assign(f.p, welcome);
            return send(JSON.stringify(f));
          }
          return send(m);
        };
        return handler(ws);
      });
  }
  return s.role && s.ws ? installWsHarness(page, undefined, s.ws === true ? {} : s.ws) : undefined;
}

const LOOPBACK = new Set(["127.0.0.1", "localhost"]);
const themeKey = (t: (typeof THEMES)[number], density: string): string =>
  JSON.stringify({
    baseTheme: t.appearance.theme,
    matchSystem: false,
    highContrast: t.appearance.high_contrast,
    density,
  });

async function webOpen(
  browser: Browser,
  s: State,
  t: (typeof THEMES)[number],
  density: string,
  motion: string,
): Promise<Opened> {
  const context: BrowserContext = await browser.newContext({
    serviceWorkers: "block",
    viewport: s.viewport ?? { width: 1280, height: 800 },
    reducedMotion: motion as "reduce" | "no-preference",
  });
  const offsite: string[] = [];
  await context.route("**/*", (r) => {
    if (LOOPBACK.has(new URL(r.request().url()).hostname)) return r.fallback();
    offsite.push(r.request().url());
    return r.abort();
  });
  await context.addInitScript(
    (v) => {
      try {
        localStorage.setItem("cv.theme.v1", v);
      } catch {
        /* storage unavailable */
      }
    },
    themeKey(t, density),
  );
  const page = await context.newPage();
  const ws = await prepare(page, s, t, density);
  await page.goto(s.path);
  return { page, ws, offsite, close: () => context.close() };
}

async function inCell(
  open: Opened,
  s: State,
  t: (typeof THEMES)[number],
  density: string,
  motion: string,
): Promise<Cell> {
  const base = { state: s.id, theme: t.name, density, motion };
  const empty = { critical: 0, serious: 0, moderate: 0, minor: 0 };
  try {
    const checks = await s.open(open.page, open.ws);
    await settle(open.page);
    const applied = await readApplied(open.page);
    // The cell must really be the cell it names: a theme or density that did not apply fails it.
    if (applied["theme"] !== t.name || applied["density"] !== density)
      throw new Error(`cell not applied: theme ${applied["theme"]}, density ${applied["density"]}`);
    if (motion === "reduce" && applied["prefersReduced"] !== "reduce")
      throw new Error("reduced motion not applied");
    if (s.id === "chrome-owner") checks["chipContrast"] = await chipContrast(open.page);
    if (s.id === "chrome-owner")
      checks["notBuilt"] = {
        // `shipped:false` (05 §8; plan 5): trips the moment a part lands
        panicCMP211: await open.page.locator('[data-cmp="CMP-211"]').count(),
        paletteCMP059: await open.page.locator('[data-cmp="CMP-059"]').count(),
      };
    const { result, via } = await runAxe(open.page, axeTags());
    const counts = { ...empty };
    for (const v of result.violations) {
      // A null or unknown impact would be dropped from the counts: fail the cell instead.
      if (!IMPACTS.includes(v.impact as Impact))
        throw new Error(`violation ${v.id} has impact ${String(v.impact)}`);
      counts[v.impact as Impact] += 1;
    }
    return {
      ...base,
      applied,
      axeVia: via,
      counts,
      // "needs review" nodes: recorded with targets, as violations are, so a human can find them (FU-4)
      incomplete: result.incomplete.map((i) => ({
        id: i.id,
        nodes: i.nodes.length,
        targets: i.nodes.slice(0, 5).map((n) => n.target.join(" ")),
      })),
      violations: result.violations.map((v) => ({
        id: v.id,
        impact: v.impact ?? "unknown",
        nodes: v.nodes.length,
        targets: v.nodes.slice(0, 5).map((n) => n.target.join(" ")),
      })),
      checks,
    };
  } catch (error) {
    return {
      ...base,
      applied: {},
      axeVia: "playwright",
      counts: empty,
      violations: [],
      incomplete: [],
      checks: {},
      error: firstLine(error),
    };
  }
}

/** Must-trip negative control: injected defects of every impact level have to be counted. */
async function control(page: Page, offsite: string[]): Promise<string[]> {
  await page.evaluate(() => {
    document.body.insertAdjacentHTML(
      "beforeend",
      '<img src="data:,"><button></button><h6>x</h6><h2></h2><div style="color:#777;background:#888">low contrast</div>',
    );
  });
  const { result } = await runAxe(page, axeTags());
  const hit = new Set(result.violations.map((v) => v.id));
  const impacts = new Set(result.violations.map((v) => v.impact));
  const missing = ["image-alt", "button-name", "color-contrast"].filter((id) => !hit.has(id));
  const levels = ["critical", "serious", "moderate", "minor"].filter((i) => !impacts.has(i));
  if (missing.length > 0 || levels.length > 0)
    throw new Error(
      `A11Y-INFRA: negative control did not trip (missing ${[...missing, ...levels].join(", ")})`,
    );
  // The off-site guard must be able to count: one navigation to a non-loopback host (TEST-NET-1, never
  // routable) has to reach the guard, which aborts it. A navigation, not a fetch: the app's strict CSP
  // (connect-src, img-src 'self') refuses a renderer fetch or image before the request leaves, so the
  // guard never sees one; a navigation is not governed by it. This runs last, so leaving the page is fine.
  const before = offsite.length;
  await page.goto("http://192.0.2.1:9/e10-q03-control").catch(() => undefined);
  await expect
    .poll(() => offsite.length, {
      message: "the off-site guard did not count the control request",
      timeout: W,
    })
    .toBeGreaterThan(before);
  offsite.length = 0; // the control's own request is not a finding
  return [...hit].sort();
}

const only = (ENV["A11Y_ONLY"] ?? "").split(",").filter((x) => x !== "");
const states = STATES.filter(
  (s) => (only.length === 0 || only.includes(s.id)) && (TARGET === "web" || s.electron === true),
);

// Only what the shell and its display need, not the whole environment (no tokens or credentials reach it).
const ELECTRON_ENV = ["PATH", "HOME", "LANG", "TMPDIR", "DISPLAY", "XAUTHORITY", "XDG_RUNTIME_DIR"];

/** The app, with a context-level guard that aborts and counts every request to a non-loopback host. */
async function launchElectron(offsite: string[]): Promise<ElectronApplication> {
  const env: Record<string, string> = { CV_DEV_SERVER_URL: ORIGIN };
  for (const k of ELECTRON_ENV) if (ENV[k] !== undefined) env[k] = ENV[k];
  const app = await electron.launch({
    args: [join(REPO, "apps/desktop/dist/main/index.js")],
    chromiumSandbox: true, // as apps/desktop/e2e: the renderer stays OS-sandboxed
    env,
  });
  await app.context().route("**/*", (r) => {
    if (LOOPBACK.has(new URL(r.request().url()).hostname)) return r.fallback();
    offsite.push(r.request().url());
    return r.abort();
  });
  return app;
}

test("negative control", async ({ browser }) => {
  rmSync(join(OUT, "states"), { recursive: true, force: true });
  mkdirSync(join(OUT, "states"), { recursive: true });
  const s = STATES[0] as State;
  const t = THEMES[0];
  let rules: string[];
  if (TARGET === "electron") {
    const guard: string[] = [];
    const app = await launchElectron(guard);
    const page = await app.firstWindow();
    await prepare(page, s, t, "compact");
    await page.goto(ORIGIN + s.path);
    await h1(page);
    rules = await control(page, guard);
    await app.close();
  } else {
    const open = await webOpen(browser, s, t, "compact", "no-preference");
    await h1(open.page);
    rules = await control(open.page, open.offsite);
    await open.close();
  }
  writeFileSync(
    join(OUT, "manifest.json"),
    JSON.stringify(
      {
        target: TARGET,
        sha: ENV["A11Y_SHA"] ?? "unset",
        states: states.map((x) => x.id),
        themes: themes.map((x) => x.name),
        densities,
        motions,
        tags: axeTags(),
        disabledRules: [],
        negativeControl: { tripped: true, rules },
      },
      null,
      2,
    ),
  );
});

for (const s of states) {
  test(`state ${s.id}`, async ({ browser }) => {
    const cells: Cell[] = [];
    const offsite: string[] = [];
    if (TARGET === "electron") {
      for (const t of themes)
        for (const density of densities) {
          const app = await launchElectron(offsite);
          const page = await app.firstWindow();
          try {
            await page.evaluate(
              (v) => localStorage.setItem("cv.theme.v1", v),
              themeKey(t, density),
            );
            const ws = await prepare(page, s, t, density);
            await page.goto(ORIGIN + s.path);
            await page
              .setViewportSize(s.viewport ?? { width: 1280, height: 800 })
              .catch(() => undefined);
            cells.push(
              await inCell(
                { page, ws, offsite, close: () => app.close() },
                s,
                t,
                density,
                "no-preference",
              ),
            );
          } finally {
            await app.close();
          }
        }
    } else {
      for (const t of themes)
        for (const density of densities)
          for (const motion of motions) {
            const open = await webOpen(browser, s, t, density, motion);
            try {
              cells.push(await inCell(open, s, t, density, motion));
            } finally {
              offsite.push(...open.offsite);
              await open.close();
            }
          }
    }
    mkdirSync(join(OUT, "states"), { recursive: true });
    writeFileSync(
      join(OUT, "states", `${s.id}.json`),
      JSON.stringify({ id: s.id, scr: s.scr, offsite, cells }, null, 2),
    );
    expect(offsite, "off-site requests were aborted").toEqual([]);
    expect(
      cells
        .filter((c) => c.error !== undefined)
        .map((c) => `${c.theme}/${c.density}/${c.motion}: ${c.error}`),
    ).toEqual([]);
  });
}
