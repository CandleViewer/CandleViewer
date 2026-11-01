// E10-Q03 (#302) driver B: the agent-run "manual" passes on the shell, in the e05-q02-manual.qa.ts style, on the
// REAL built web app (`vite preview`, loopback only, a loopback route guard that aborts and counts anything else).
// Same Playwright from apps/web, no new dependency. Each check writes records to <A11Y_OUT>/checks/<name>.json;
// the run fails if any record is a failure. Passes:
//   keyboard    - a real-key Tab walk (page.keyboard) per role and banner state: the skip link first, the E10-D04
//                 13.1 region order (SkipLink, TopBar, NavRail, banner slot, canvas, RightRail, StatusBar), every
//                 tabbable reached, no fixed point and no cycle before the walk wraps, Shift+Tab the exact reverse;
//                 focus visible at every stop (outline, >= 2 px, >= 3:1 against the surface behind it, not
//                 obscured: SC 2.4.7 / 2.4.11 / 2.4.13); each overlay's Esc and where focus goes (E10-D04 13.2).
//   zoom        - 320 x 256 CSS px (WCAG 1.4.10, 400 % of 1280 x 1024) and a 125 % text scale: no page-level
//                 horizontal scroll, nothing past the viewport edge, no clipped text without a full-text twin, no
//                 control lost against the 1280 px render.
//   greyscale   - filter:grayscale(1) captures (verified grey) and a DOM check that the env badge, the connection
//                 chip and region, a severity band and the active nav item each carry a word, an icon or a shape.
//   names       - computed accessible names (CDP accessibility tree) against docs/design/E10/E10-D04-names.json:
//                 the agent-run screen-reader proxy, NOT a human screen-reader pass.
//   announce    - the connection chip ticks at 1 Hz while disconnected; on a fake clock (page.clock) the live
//                 regions must announce once per episode, not once per tick.
//   control     - negative controls, run first: an injected focus trap (fixed point and cycle), an injected clip
//                 and overflow, an injected hue-only cue, an injected outline-less focus. Each must be detected,
//                 or the run fails as A11Y-INFRA.
// Every step is raced against a step bound (`step`), nothing sleeps, and the per-test timeouts below come from
// measured runs (A11Y_OUT/checks/*.json carry the milliseconds).
// Build, then run from apps/web:
//   pnpm turbo run build --filter=@candleviewer/web
//   cd apps/web && A11Y_SHA=$(git rev-parse HEAD) A11Y_OUT=<dir> \
//     npx playwright test -c ../../docs/plan/a11y/_tools/e10-q03-manual.config.ts
//   node docs/plan/a11y/_tools/e10-q03-manual-merge.mjs <dir>   # checks/*.json -> results.json.gz + summary.md
// Environment: A11Y_SHA, A11Y_OUT, A11Y_PORT (default 4197), A11Y_THEMES, A11Y_DENSITIES, A11Y_WORKERS.
import { mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { createHash } from "node:crypto";
import { expect, test, type Browser, type BrowserContext, type Page } from "@playwright/test";
import type * as ApiModule from "../../../../apps/web/e2e/support/api";
import type * as WsModule from "../../../../apps/web/e2e/support/wsHarness";
import type { GatewayOptions, WsHarness } from "../../../../apps/web/e2e/support/wsHarness";

let json: (typeof ApiModule)["json"];
let stubSession: (typeof ApiModule)["stubSession"];
let installWsHarness: (typeof WsModule)["installWsHarness"];
test.beforeAll(async () => {
  const api = await import("../../../../apps/web/e2e/support/api");
  const ws = await import("../../../../apps/web/e2e/support/wsHarness");
  ({ json, stubSession } = api);
  ({ installWsHarness } = ws);
});

const ENV = process.env;
const REPO = resolve(__dirname, "../../../..");
const OUT = resolve(ENV["A11Y_OUT"] ?? join(tmpdir(), "e10-q03-manual"), "checks");
const STEP_MS = 10_000; // one step (a key press, a read, a wait) that does not finish in this fails by name
const MAX_TABS = 60;
/** Per-test timeouts (ms). Set from measured runs (the `ms` of each checks/*.json, 3 workers: walk 49 s, esc 15 s, overlay focus 17 s, zoom 72 s, greyscale 19 s, names 4 s, announce 1 s, controls < 1 s): about 3-4x the measured time. */
const TIMEOUT = {
  walk: 200_000,
  esc: 90_000,
  zoom: 300_000,
  grey: 90_000,
  names: 30_000,
  announce: 30_000,
  control: 30_000,
};
const sha256 = (b: Buffer | string): string => createHash("sha256").update(b).digest("hex");

const pick = <T extends { name: string } | string>(all: readonly T[], env: string | undefined) => {
  const asked = (env ?? "").split(",").filter((x) => x !== "");
  return asked.length === 0
    ? all
    : all.filter((x) => asked.includes(typeof x === "string" ? x : x.name));
};
const THEMES = [
  { name: "dark", appearance: { theme: "dark", high_contrast: false } },
  { name: "light", appearance: { theme: "light", high_contrast: false } },
  { name: "high-contrast", appearance: { theme: "dark", high_contrast: true } },
] as const;
type Theme = (typeof THEMES)[number];
const themes = pick(THEMES, ENV["A11Y_THEMES"]);
const densities = pick(["compact", "comfortable"] as const, ENV["A11Y_DENSITIES"]);

interface Rec {
  readonly check: string;
  readonly state: string;
  readonly theme: string;
  readonly density: string;
  readonly sc: string;
  readonly pass: boolean;
  /** Not applicable or not built: recorded, never counted as asserted. */
  readonly skip?: boolean;
  readonly detail: string;
  readonly data?: unknown;
}
const records: Rec[] = [];
const rec = (
  check: string,
  state: string,
  c: { theme: string; density: string },
  sc: string,
  pass: boolean,
  detail: string,
  data?: unknown,
  skip = false,
): Rec => ({
  check,
  state,
  theme: c.theme,
  density: c.density,
  sc,
  pass,
  ...(skip ? { skip } : {}),
  detail,
  ...(data === undefined ? {} : { data }),
});
const failures = (rows: readonly Rec[]): string[] =>
  rows
    .filter((r) => !r.pass && r.skip !== true)
    .map((r) => `${r.check} [${r.state}/${r.theme}/${r.density}]: ${r.detail}`);
/** Writes one check file (with its wall-clock ms, for the measured timeouts) and fails on any failed record. */
async function finish(
  name: string,
  rows: Rec[],
  started: number,
  offsite: string[],
): Promise<void> {
  mkdirSync(OUT, { recursive: true });
  const body = JSON.stringify({ name, ms: Date.now() - started, offsite, rows }, null, 2);
  writeFileSync(join(OUT, `${name}.json`), body);
  records.push(...rows);
  expect(offsite, "off-site requests were aborted").toEqual([]);
  expect(failures(rows)).toEqual([]);
}

/** Every awaited step is raced against its bound, so a hang fails by name long before the test timeout. */
async function step<T>(label: string, p: Promise<T>, ms = STEP_MS): Promise<T> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  const bound = new Promise<never>((_, reject) => {
    timer = setTimeout(() => reject(new Error(`STEP-TIMEOUT: ${label} > ${ms} ms`)), ms);
  });
  try {
    return await Promise.race([p, bound]);
  } finally {
    clearTimeout(timer);
  }
}

// ------------------------------------------------------------------------------------------ in-page helpers
interface Ring {
  readonly style: string;
  readonly width: number;
  readonly offset: number;
  readonly ratio: number;
  readonly surface: string;
  readonly obscured: boolean;
  readonly visibleInViewport: boolean;
}
interface Stop {
  readonly id: number;
  readonly label: string;
  readonly region: string;
  readonly rank: number;
  readonly ring: Ring;
}
interface Cue {
  readonly word: boolean;
  readonly icon: boolean;
  readonly shape: boolean;
  readonly text: string;
}
interface Q {
  focused(): Stop | null;
  tabbables(): { id: number; label: string }[];
  resetFocus(): void;
  focusLast(): Stop | null;
  cue(sel: string): Cue | null;
  navCue(): { diff: string[] } | null;
  clipped(): string[];
  overflowing(): string[];
  hscroll(): boolean;
  controls(): string[];
}
declare global {
  interface Window {
    __cvq: Q;
  }
}

/** Installed in every page before its scripts (an init script is not subject to the page's CSP). */
function installHelpers(): void {
  const cv = document.createElement("canvas");
  cv.width = cv.height = 1;
  const g = cv.getContext("2d", { willReadFrequently: true });
  if (g === null) throw new Error("no 2d context");
  const rgba = (css: string): number[] => {
    g.clearRect(0, 0, 1, 1);
    g.fillStyle = "#000";
    g.fillStyle = css; // a computed style is always a valid colour: the canvas resolves color-mix, oklch, ...
    g.fillRect(0, 0, 1, 1);
    const d = g.getImageData(0, 0, 1, 1).data;
    return [d[0] ?? 0, d[1] ?? 0, d[2] ?? 0, (d[3] ?? 0) / 255];
  };
  const over = (top: number[], under: number[]): number[] => {
    const a = top[3] ?? 1;
    return [0, 1, 2].map((i) => (top[i] ?? 0) * a + (under[i] ?? 0) * (1 - a)).concat([1]);
  };
  const surfaceOf = (el: Element | null): number[] => {
    const layers: number[][] = [];
    for (let n = el; n !== null; n = n.parentElement) {
      const c = rgba(getComputedStyle(n).backgroundColor);
      if ((c[3] ?? 0) > 0) {
        layers.push(c);
        if ((c[3] ?? 0) >= 1) break;
      }
    }
    return layers.reduceRight((acc, c) => over(c, acc), [255, 255, 255, 1]);
  };
  const lum = (c: number[]): number => {
    const f = (v: number): number =>
      (v /= 255) <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
    return 0.2126 * f(c[0] ?? 0) + 0.7152 * f(c[1] ?? 0) + 0.0722 * f(c[2] ?? 0);
  };
  const ratio = (a: number[], b: number[]): number => {
    const [x, y] = [lum(a), lum(b)];
    return Math.round(((Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05)) * 100) / 100;
  };
  const ids = new WeakMap<Element, number>();
  let nextId = 0;
  const idOf = (el: Element): number => {
    if (!ids.has(el)) ids.set(el, (nextId += 1));
    return ids.get(el) ?? 0;
  };
  const label = (el: Element): string =>
    (el.getAttribute("aria-label") ?? (el as HTMLElement).innerText ?? el.textContent ?? "")
      .trim()
      .replace(/\s+/g, " ")
      .slice(0, 48);
  // E10-D04 13.1's order: SkipLink, TopBar, NavRail, banner slot, canvas, RightRail, StatusBar (+ overlays).
  const REGIONS: [string, string][] = [
    ["skip", '[data-cmp="CMP-085"]'],
    ["overlay", '[role="dialog"],[role="alertdialog"]'],
    ["topbar", '[data-cmp="CMP-072"]'],
    ["navrail", 'nav[aria-label="Primary"]'],
    [
      "banner",
      '[aria-label="Connection"],[aria-label="System notices"],[aria-label="Software update"],[data-version-banner]',
    ],
    ["canvas", "main"],
    ["rightrail", 'aside[aria-label="Side panels"]'],
    ["statusbar", '[role="status"][aria-label="System status"],footer'],
  ];
  const RANK = [
    "skip",
    "topbar",
    "navrail",
    "banner",
    "canvas",
    "rightrail",
    "statusbar",
    "overlay",
  ];
  const regionOf = (el: Element): string =>
    REGIONS.find(([, sel]) => el.closest(sel) !== null)?.[0] ?? "other";
  const visible = (el: Element): boolean =>
    (el as HTMLElement).checkVisibility({ visibilityProperty: true });
  const isTabbable = (el: HTMLElement): boolean =>
    el.tabIndex >= 0 &&
    !el.matches(":disabled") &&
    visible(el) &&
    el.closest('[inert],[aria-hidden="true"]') === null;
  const TABBABLE =
    'a[href],button,input,select,textarea,summary,[tabindex],[contenteditable="true"]';
  const ring = (el: HTMLElement): Ring => {
    const cs = getComputedStyle(el);
    const offset = parseFloat(cs.outlineOffset) || 0;
    const behind = surfaceOf(offset >= 0 ? el.parentElement : el);
    const rc = rgba(cs.outlineColor);
    const r = el.getBoundingClientRect();
    const top = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
    return {
      style: cs.outlineStyle,
      width: parseFloat(cs.outlineWidth) || 0,
      offset,
      ratio: ratio(over(rc, behind), behind),
      surface: `rgb(${behind.slice(0, 3).map(Math.round).join(",")})`,
      obscured: top === null || !(el.contains(top) || top.contains(el)),
      visibleInViewport:
        r.width > 0 && r.bottom > 0 && r.right > 0 && r.top < innerHeight && r.left < innerWidth,
    };
  };
  const hasAscii = /[A-Za-z]{2,}/;
  const cue = (el: Element): Cue => {
    const text = ((el as HTMLElement).innerText ?? "").trim();
    const cs = getComputedStyle(el);
    const dashed = ["dashed", "dotted", "double"].includes(cs.borderTopStyle);
    return {
      word: hasAscii.test(text),
      icon: el.querySelector("svg,img") !== null || /[^\p{L}\p{N}\s.,:;()/-]/u.test(text),
      shape: dashed,
      text,
    };
  };
  const NON_HUE = [
    "fontWeight",
    "textDecorationLine",
    "borderLeftWidth",
    "borderLeftStyle",
    "borderTopWidth",
    "outlineStyle",
  ] as const;
  const clippedBy = (el: HTMLElement, cs: CSSStyleDeclaration): boolean =>
    (["hidden", "clip"].includes(cs.overflowX) && el.scrollWidth > el.clientWidth + 1) ||
    (["hidden", "clip"].includes(cs.overflowY) && el.scrollHeight > el.clientHeight + 1);
  const where = (el: Element): string =>
    `${el.tagName.toLowerCase()}${el.getAttribute("data-cmp") ? `[${el.getAttribute("data-cmp")}]` : ""} "${label(el).slice(0, 30)}"`;
  const q: Q = {
    focused() {
      const el = document.activeElement as HTMLElement | null;
      if (el === null || el === document.body || el === document.documentElement) return null;
      const region = regionOf(el);
      return { id: idOf(el), label: label(el), region, rank: RANK.indexOf(region), ring: ring(el) };
    },
    tabbables() {
      return [...document.querySelectorAll<HTMLElement>(TABBABLE)]
        .filter(isTabbable)
        .map((el) => ({ id: idOf(el), label: label(el) }));
    },
    resetFocus() {
      (document.activeElement as HTMLElement | null)?.blur();
      document.body.tabIndex = -1;
      document.body.focus();
      document.body.removeAttribute("tabindex");
      getSelection()?.removeAllRanges();
    },
    focusLast() {
      const last = [...document.querySelectorAll<HTMLElement>(TABBABLE)].filter(isTabbable).pop();
      last?.focus();
      return q.focused();
    },
    cue(sel) {
      const el = document.querySelector(sel);
      return el === null ? null : cue(el);
    },
    navCue() {
      const on = document.querySelector<HTMLElement>(
        'nav[aria-label="Primary"] [aria-current="page"]',
      );
      const off = document.querySelector<HTMLElement>(
        'nav[aria-label="Primary"] a:not([aria-current])',
      );
      if (on === null || off === null) return null;
      const [a, b] = [getComputedStyle(on), getComputedStyle(off)];
      const diff: string[] = NON_HUE.filter((k) => a[k] !== b[k]).map(
        (k) => `${k} ${b[k]} -> ${a[k]}`,
      );
      if (cue(on).icon !== cue(off).icon) diff.push("glyph");
      return { diff };
    },
    clipped() {
      const out: string[] = [];
      for (const el of document.querySelectorAll<HTMLElement>("body *")) {
        if (!visible(el)) continue;
        const cs = getComputedStyle(el);
        const r = el.getBoundingClientRect();
        if ((r.width <= 2 && r.height <= 2) || !clippedBy(el, cs)) continue;
        const text = (el.innerText ?? "").trim().replace(/\s+/g, " ");
        if (text === "") continue;
        const twin = [el.getAttribute("title"), el.getAttribute("aria-label")].some(
          (t) => t !== null && t.replace(/\s+/g, " ").includes(text),
        );
        // F-7: CMP-045's title is one ellipsised line by design (toast.css); the full title is the group's name.
        const known = el.matches(".cv-toast__title") ? "[F-7] " : "";
        if (!twin)
          out.push(
            `${known}${where(el)} (${el.scrollWidth}x${el.scrollHeight} in ${el.clientWidth}x${el.clientHeight})`,
          );
      }
      return out;
    },
    overflowing() {
      const out: string[] = [];
      for (const el of document.querySelectorAll<HTMLElement>("body *")) {
        if (!visible(el) || el.closest('[inert],[aria-hidden="true"]') !== null) continue;
        const r = el.getBoundingClientRect();
        if (r.width <= 2 || r.height <= 2 || (r.right <= innerWidth + 1 && r.left >= -1)) continue;
        let scrolls = false;
        for (let n = el.parentElement; n !== null && n !== document.body; n = n.parentElement) {
          const o = getComputedStyle(n).overflowX;
          if (["auto", "scroll", "hidden", "clip"].includes(o)) scrolls = true;
        }
        if (!scrolls)
          out.push(`${where(el)} ${Math.round(r.left)}..${Math.round(r.right)} of ${innerWidth}`);
      }
      return out;
    },
    hscroll() {
      return document.documentElement.scrollWidth > document.documentElement.clientWidth + 1;
    },
    controls() {
      return [...document.querySelectorAll<HTMLElement>("a[href],button,[role=button]")]
        .filter((el) => visible(el) && el.closest('[inert],[aria-hidden="true"]') === null)
        .map((el) => label(el))
        .filter((t) => t !== "");
    },
  };
  window.__cvq = q;
}

// ------------------------------------------------------------------------------------------ states and cells
type Role = "owner" | "manager" | "viewer";
// Same frame as e2e/system-states/break-glass-notice.spec.ts (stub data, one SCR-153 row).
const NOTICE = {
  kind: "notice",
  severity: "critical",
  message: "Break-glass recovery was used on this server; the Owner must review it.",
  reason: "auth.break_glass_used",
};
interface State {
  readonly id: string;
  readonly path: string;
  readonly role?: Role;
  readonly live?: true; // /me answers session.environment = "live"
  readonly ws?: GatewayOptions | true;
  readonly welcome?: { readonly server_version?: string; readonly protocol?: string };
  readonly stubs?: (page: Page) => Promise<void>;
  readonly ready: (page: Page, ws: WsHarness | undefined) => Promise<void>;
}
const h1 = (p: Page) => p.getByRole("heading", { level: 1 }).first().waitFor({ timeout: STEP_MS });
const main = (p: Page) => p.getByRole("main").first().waitFor({ timeout: STEP_MS });
const rail = (p: Page) => p.getByRole("navigation", { name: "Primary" });
const toggle = (p: Page) => rail(p).getByRole("button", { name: /navigation rail$/u });
const S = (s: State): State => s;
const STATES = {
  owner: S({ id: "chrome-owner", path: "/journal", role: "owner", ws: true, ready: h1 }),
  viewer: S({ id: "chrome-viewer", path: "/journal", role: "viewer", ws: true, ready: h1 }),
  live: S({ id: "chrome-live", path: "/journal", role: "owner", live: true, ws: true, ready: h1 }),
  banner: S({
    id: "degraded-banner",
    path: "/journal",
    role: "manager",
    ws: { firstAuthSystem: [NOTICE] },
    ready: async (p) => {
      await h1(p);
      await p
        .getByRole("button", { name: `Dismiss ${NOTICE.message}` })
        .waitFor({ timeout: STEP_MS });
    },
  }),
  versionBanner: S({
    id: "version-banner",
    path: "/journal",
    role: "owner",
    ws: true,
    welcome: { server_version: "99.0.0" },
    ready: async (p) => {
      await h1(p);
      await p.locator("[data-version-banner]").waitFor({ timeout: STEP_MS });
    },
  }),
  versionDialog: S({
    id: "version-dialog",
    path: "/journal",
    role: "owner",
    ws: true,
    welcome: { protocol: "cv.v0" }, // another protocol: `incompatible`, the blocking alertdialog
    ready: (p) => p.getByRole("alertdialog").waitFor({ timeout: STEP_MS }),
  }),
  down: S({
    id: "connection-down",
    path: "/journal",
    role: "owner",
    ws: true,
    ready: async (p, ws) => {
      await h1(p);
      if (ws)
        await expect.poll(() => ws.authenticated(), { timeout: STEP_MS }).toBeGreaterThanOrEqual(1);
      ws?.kill();
      await p.getByRole("region", { name: "Connection" }).waitFor({ timeout: STEP_MS });
    },
  }),
  forbidden: S({ id: "forbidden-403", path: "/403", role: "owner", ws: true, ready: main }),
  notFound: S({ id: "not-found-404", path: "/404", role: "owner", ws: true, ready: main }),
  offline: S({ id: "offline-page", path: "/offline", ready: main }),
  panelCrash: S({
    id: "panel-crash",
    path: "/terminal/last",
    role: "owner",
    ws: true,
    // A checklist body with items = null makes SetupChecklistCard throw inside its PanelErrorBoundary (CMP-091).
    stubs: async (p) => {
      await p.route("**/api/v1/onboarding/checklist", (r) =>
        r.fulfill(json({ dismissed: false, complete: false, items: null })),
      );
    },
    ready: (p) =>
      p.getByRole("heading", { name: "This panel stopped working" }).waitFor({ timeout: STEP_MS }),
  }),
  crash: S({
    id: "route-crash",
    path: "/admin/users/new",
    role: "owner",
    ws: true,
    // An invites body with items = null makes AdminInviteScreen throw at render (as driver A).
    stubs: async (p) => {
      await p.route("**/api/v1/users/invites", (r) => r.fulfill(json({ items: null })));
    },
    ready: (p) => p.getByRole("button", { name: /Reload page/ }).waitFor({ timeout: STEP_MS }),
  }),
} as const;
const withOpen = (base: State, id: string, open: (p: Page) => Promise<void>): State => ({
  ...base,
  id,
  ready: async (p, ws) => {
    await base.ready(p, ws);
    await open(p);
  },
});
const OPEN = {
  drawer: withOpen(STATES.owner, "drawer", async (p) => {
    await p.getByRole("button", { name: "Notifications" }).click({ timeout: STEP_MS });
    await p.getByRole("group", { name: "Notifications" }).waitFor({ timeout: STEP_MS });
  }),
  cheatsheet: withOpen(STATES.owner, "cheatsheet", async (p) => {
    await p.keyboard.press("Control+/");
    await p.getByRole("dialog", { name: "Keyboard shortcuts" }).waitFor({ timeout: STEP_MS });
  }),
  toast: withOpen(STATES.owner, "toast", async (p) => {
    await p.getByTestId("toast-host").waitFor({ state: "attached", timeout: STEP_MS });
    // An inert destructive binding explains itself with one toast (hotkeys.spec.ts); press until it shows.
    await expect(async () => {
      await p.keyboard.press("Control+Shift+X");
      await expect(
        p.getByRole("region", { name: "Notifications" }).getByRole("group").first(),
      ).toBeVisible({
        timeout: 250,
      });
    }).toPass({ timeout: STEP_MS });
  }),
};

interface CellSpec {
  readonly theme: Theme;
  readonly density: string;
  readonly viewport?: { width: number; height: number };
  readonly textScale?: 100 | 125;
}
const cellOf = (c: CellSpec) => ({ theme: c.theme.name, density: c.density });
const themeKey = (c: CellSpec): string =>
  JSON.stringify({
    baseTheme: c.theme.appearance.theme,
    matchSystem: false,
    highContrast: c.theme.appearance.high_contrast,
    density: c.density,
    ...(c.textScale === undefined ? {} : { textScale: c.textScale }),
  });
const LOOPBACK = new Set(["127.0.0.1", "localhost"]);

interface Opened {
  readonly page: Page;
  readonly ws: WsHarness | undefined;
  readonly ctx: BrowserContext;
  readonly offsite: string[];
}

/** One browser context per cell: stubs, ws harness, loopback guard, helpers, theme; then the state is reached. */
async function openCell(
  browser: Browser,
  s: State,
  c: CellSpec,
  offsite: string[],
): Promise<Opened> {
  const ctx = await step(
    "newContext",
    browser.newContext({
      serviceWorkers: "block",
      viewport: c.viewport ?? { width: 1280, height: 800 },
      reducedMotion: "no-preference",
    }),
  );
  try {
    return await openIn(ctx, s, c, offsite);
  } catch (e) {
    await ctx.close();
    throw e;
  }
}
async function openIn(
  ctx: BrowserContext,
  s: State,
  c: CellSpec,
  offsite: string[],
): Promise<Opened> {
  await ctx.route("**/*", (r) => {
    if (LOOPBACK.has(new URL(r.request().url()).hostname)) return r.fallback();
    offsite.push(r.request().url());
    return r.abort();
  });
  await ctx.addInitScript(installHelpers);
  await ctx.addInitScript((v) => {
    try {
      localStorage.setItem("cv.theme.v1", v);
    } catch {
      /* storage unavailable */
    }
  }, themeKey(c));
  const page = await ctx.newPage();
  if (s.role) {
    await stubSession(page, { role: s.role });
    if (s.live)
      await page.route("**/api/v1/me", (r) =>
        r.fulfill(
          json({
            role: s.role,
            permissions: [],
            session: { environment: "live", elevated_until: null },
          }),
        ),
      );
    await page.route("**/api/v1/me/preferences", (r) =>
      r.fulfill(
        json({
          appearance: {
            ...c.theme.appearance,
            density: c.density,
            ...(c.textScale === undefined ? {} : { font_scale: c.textScale / 100 }),
          },
        }),
      ),
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
  const ws =
    s.role && s.ws ? await installWsHarness(page, undefined, s.ws === true ? {} : s.ws) : undefined;
  await step(`goto ${s.path}`, page.goto(s.path));
  await step(`ready ${s.id}`, s.ready(page, ws));
  // Fonts loaded and every finite animation or transition done (an infinite one never finishes: skipped), so a
  // measure never reads a drawer half-way through its slide.
  await step(
    "settle",
    page.evaluate(async () => {
      await document.fonts.ready;
      await Promise.all(
        document
          .getAnimations()
          .filter((a) => a.effect?.getComputedTiming().iterations !== Infinity)
          .map((a) => a.finished.catch(() => undefined)),
      );
    }),
  );
  // The cell must really be the cell it names (as driver A): a theme, density or text scale that did not apply fails it.
  const applied = await page.evaluate(() => ({
    t: document.documentElement.getAttribute("data-theme"),
    d: document.documentElement.getAttribute("data-density"),
    c: document.documentElement.getAttribute("data-contrast"),
    s: document.documentElement.getAttribute("data-text-scale"),
  }));
  if (applied.t !== c.theme.name || applied.d !== c.density)
    throw new Error(`cell not applied: ${JSON.stringify(applied)}`);
  if (c.textScale === 125 && applied.s !== "125")
    throw new Error(`text scale not applied: ${applied.s}`);
  return { page, ws, ctx, offsite };
}
/** The cells of a state: every theme x density (the driver's matrix). */
const cells = (extra: Partial<CellSpec> = {}): CellSpec[] =>
  themes.flatMap((theme) => densities.map((density) => ({ theme, density, ...extra })));
const firstLine = (e: unknown): string =>
  e instanceof Error ? (e.message.split("\n")[0] ?? "error") : String(e);
/** Runs `fn` in every cell of a state; a cell that cannot be reached or measured is a failed record, not an abort. */
async function eachCell(
  browser: Browser,
  s: State,
  specs: readonly CellSpec[],
  offsite: string[],
  rows: Rec[],
  fn: (o: Opened, c: CellSpec) => Promise<Rec[]>,
): Promise<void> {
  for (const c of specs) {
    let o: Opened | undefined;
    try {
      o = await openCell(browser, s, c, offsite);
      rows.push(...(await step(`checks of ${s.id}`, fn(o, c), 6 * STEP_MS)));
    } catch (e) {
      rows.push(
        rec("the state is reached and measured", s.id, cellOf(c), "-", false, firstLine(e)),
      );
    } finally {
      await o?.ctx.close();
    }
  }
}

// ------------------------------------------------------------------------------------------ keyboard: Tab walk
interface Walk {
  readonly stops: Stop[];
  readonly end: "wrapped" | "fixed-point" | "cycle" | "limit";
  readonly presses: number;
}
/** Real Tab (or Shift+Tab) presses from the top of the document until focus wraps to the body or trips. */
async function walkTab(page: Page, key = "Tab"): Promise<Walk> {
  await step(
    "reset focus",
    page.evaluate(() => window.__cvq.resetFocus()),
  );
  const stops: Stop[] = [];
  const seen = new Set<number>();
  if (key === "Shift+Tab") {
    // Backwards from the body leaves the document at once: start on the last tabbable instead.
    await page.keyboard.press("Shift"); // key modality, so the focus is :focus-visible
    const last = await step(
      "focus last",
      page.evaluate(() => window.__cvq.focusLast()),
    );
    if (last === null) return { stops, end: "wrapped", presses: 0 };
    seen.add(last.id);
    stops.push(last);
  }
  for (let i = 1; i <= MAX_TABS; i += 1) {
    await step(`press ${key} #${i}`, page.keyboard.press(key));
    const s = await step(
      `read focus #${i}`,
      page.evaluate(() => window.__cvq.focused()),
    );
    if (s === null) return { stops, end: "wrapped", presses: i };
    if (stops[stops.length - 1]?.id === s.id) return { stops, end: "fixed-point", presses: i };
    if (seen.has(s.id)) return { stops, end: "cycle", presses: i };
    seen.add(s.id);
    stops.push(s);
  }
  return { stops, end: "limit", presses: MAX_TABS };
}

const RING_MIN_PX = 2; // SC 2.4.13: at least 2 CSS px; the token is --border-focus
const RING_MIN_RATIO = 3; // SC 2.4.13 / 1.4.11
/** SC 2.4.7 / 2.4.11 / 2.4.13 over a list of focused stops: the failing stops, and the surfaces seen. */
function ringProblems(stops: readonly Stop[]): { bad: string[]; surfaces: string[] } {
  const bad: string[] = [];
  for (const s of stops) {
    const r = s.ring;
    const why: string[] = [];
    if (r.style === "none") why.push("no outline");
    else if (r.style !== "solid") why.push(`outline-style ${r.style}`);
    if (r.width < RING_MIN_PX) why.push(`${r.width}px < ${RING_MIN_PX}px`);
    if (r.ratio < RING_MIN_RATIO) why.push(`${r.ratio}:1 < ${RING_MIN_RATIO}:1 on ${r.surface}`);
    if (r.obscured) why.push("obscured (2.4.11)");
    if (!r.visibleInViewport) why.push("off screen");
    if (why.length > 0) bad.push(`${s.region} "${s.label}": ${why.join(", ")}`);
  }
  return {
    bad,
    surfaces: [...new Set(stops.map((s) => `${s.region} ${s.ring.surface}`))],
  };
}

/** The walk's records: skip link first, region order, completeness, no trap, exact reverse, focus visible. */
async function walkRecords(page: Page, name: string, c: CellSpec): Promise<Rec[]> {
  const cell = cellOf(c);
  const fwd = await walkTab(page);
  const back = await walkTab(page, "Shift+Tab");
  const reach = await step(
    "tabbables",
    page.evaluate(() => window.__cvq.tabbables()),
  );
  const reached = new Set(fwd.stops.map((s) => s.id));
  const missing = reach.filter((t) => !reached.has(t.id)).map((t) => t.label);
  const ranks = fwd.stops.map((s) => s.rank);
  const outOfOrder = ranks.flatMap((r, i) =>
    i > 0 && r < (ranks[i - 1] ?? 0) ? [fwd.stops[i]?.label ?? "?"] : [],
  );
  const ring = ringProblems(fwd.stops);
  const reverse = back.stops.map((s) => s.id).reverse();
  const order = fwd.stops.map((s) => `${s.region}:${s.label}`);
  return [
    rec(
      "skip link is the first Tab stop",
      name,
      cell,
      "2.4.1",
      fwd.stops[0]?.region === "skip",
      `first stop: ${order[0]}`,
      order,
    ),
    rec(
      "regions in the E10-D04 13.1 order",
      name,
      cell,
      "2.4.3",
      outOfOrder.length === 0 && !ranks.includes(-1),
      outOfOrder.length === 0
        ? `${fwd.stops.length} stops`
        : `out of order: ${outOfOrder.join("; ")}`,
    ),
    rec(
      "every tabbable control is reached",
      name,
      cell,
      "2.1.1",
      missing.length === 0 && reach.length > 0,
      missing.length === 0
        ? `${reach.length} tabbable, all reached`
        : `not reached: ${missing.join("; ")}`,
    ),
    rec(
      "no trap: the walk wraps to the page start",
      name,
      cell,
      "2.1.2",
      fwd.end === "wrapped" && back.end === "wrapped",
      `forward ${fwd.end} after ${fwd.presses} presses, backward ${back.end} after ${back.presses}`,
    ),
    rec(
      "Shift+Tab is the exact reverse",
      name,
      cell,
      "2.4.3",
      fwd.end === "wrapped" &&
        JSON.stringify(reverse) === JSON.stringify(fwd.stops.map((s) => s.id)),
      `${back.stops.length} stops back, ${fwd.stops.length} forward`,
    ),
    rec(
      "focus visible at every stop",
      name,
      cell,
      "2.4.7 / 2.4.11 / 2.4.13",
      ring.bad.length === 0 && fwd.stops.length > 0,
      ring.bad.length === 0
        ? `${fwd.stops.length} stops, surfaces: ${ring.surfaces.join("; ")}`
        : ring.bad.join(" | "),
      { surfaces: ring.surfaces },
    ),
  ];
}

const WALK_STATES = [
  STATES.owner,
  STATES.viewer,
  STATES.banner,
  STATES.down,
  STATES.versionBanner,
  OPEN.drawer,
];
test("keyboard: Tab walk and focus visible", async ({ browser }) => {
  test.setTimeout(TIMEOUT.walk);
  const started = Date.now();
  const rows: Rec[] = [];
  const offsite: string[] = [];
  for (const s of WALK_STATES)
    await eachCell(browser, s, cells(), offsite, rows, async (o, c) => {
      const out = await walkRecords(o.page, s.id, c);
      if (s.id === "chrome-owner") {
        // The skip link moves focus to <main>, and the next Tab leaves the skip target for the canvas / RightRail.
        await step(
          "reset",
          o.page.evaluate(() => window.__cvq.resetFocus()),
        );
        await o.page.keyboard.press("Tab");
        await o.page.keyboard.press("Enter");
        const onMain = await o.page.evaluate(() => document.activeElement?.tagName === "MAIN");
        await o.page.keyboard.press("Tab");
        const next = await o.page.evaluate(() => window.__cvq.focused());
        out.push(
          rec(
            "skip link lands on main, Tab goes past the chrome",
            s.id,
            cellOf(c),
            "2.4.1",
            onMain && (next?.rank ?? 0) >= 4,
            `main focused ${onMain}; next stop ${next?.region}:${next?.label}`,
          ),
        );
      }
      return out;
    });
  // The same walk at 400 % (320 x 256) and 125 % text: the chrome must stay reachable and its focus visible.
  for (const s of [STATES.owner, STATES.viewer])
    for (const mode of ZOOM_MODES) {
      const specs = cells({
        viewport: mode.viewport,
        ...(mode.textScale === undefined ? {} : { textScale: mode.textScale }),
      });
      await eachCell(browser, s, specs, offsite, rows, (o, c) =>
        walkRecords(o.page, `${s.id}@${mode.id}`, c),
      );
    }
  await finish("keyboard-walk", rows, started, offsite);
});

// ------------------------------------------------------------------------------------------ keyboard: Esc per overlay
const active = (p: Page): Promise<string> =>
  p.evaluate(() => {
    const e = document.activeElement as HTMLElement | null;
    if (e === null || e === document.body) return "(body)";
    return `${e.tagName.toLowerCase()} "${(e.getAttribute("aria-label") ?? e.innerText ?? "").trim().slice(0, 30)}"`;
  });
/** Focus by keyboard modality (a key first), so the focus is :focus-visible as a Tab would leave it. */
async function keyFocus(page: Page, target: ReturnType<Page["locator"]>): Promise<void> {
  await step("modality key", page.keyboard.press("Shift"));
  await step("focus", target.focus({ timeout: STEP_MS }));
  const vis = await target.evaluate((e) => e.matches(":focus-visible"));
  if (!vis) throw new Error("focus is not :focus-visible after a key press");
}

type EscCase = (page: Page, c: CellSpec) => Promise<Rec[]>;
const rows1 = (page: Page, state: string, c: CellSpec) => ({
  ok: (check: string, sc: string, pass: boolean, detail: string): Rec =>
    rec(check, state, cellOf(c), sc, pass, detail),
  now: () => active(page),
});

const ESC_CASES: { state: State; run: EscCase }[] = [
  {
    // RightRail drawer (E10-D04 13.2): the launcher's CMP-016 tooltip takes the first Esc (WCAG 1.4.13), the second closes.
    state: STATES.owner,
    run: async (page, c) => {
      const r = rows1(page, "drawer", c);
      const launcher = page.getByRole("button", { name: "Notifications" });
      await keyFocus(page, launcher);
      await page.keyboard.press("Enter");
      const group = page.getByRole("group", { name: "Notifications" });
      await group.waitFor({ timeout: STEP_MS });
      let presses = 0;
      // The launcher's aria-expanded flips at once; the panel itself slides out, then turns hidden.
      while ((await launcher.getAttribute("aria-expanded")) === "true" && presses < 3) {
        await page.keyboard.press("Escape");
        presses += 1;
      }
      await group.waitFor({ state: "hidden", timeout: STEP_MS });
      const closed = !(await group.isVisible());
      const at = await r.now();
      return [
        r.ok(
          "Esc closes the drawer",
          "2.1.1",
          closed && presses <= 2,
          `closed ${closed} after ${presses} Esc`,
        ),
        r.ok(
          "focus returns to the launcher",
          "2.4.3",
          at.includes("Notifications"),
          `focus: ${at}`,
        ),
        r.ok(
          "the launcher reports collapsed",
          "4.1.2",
          (await launcher.getAttribute("aria-expanded")) === "false",
          "aria-expanded",
        ),
      ];
    },
  },
  {
    // SCR-013: Ctrl+/ from two different invokers; Esc returns to whichever held focus.
    state: STATES.owner,
    run: async (page, c) => {
      const r = rows1(page, "cheatsheet", c);
      const out: Rec[] = [];
      for (const [label, target] of [
        ["search trigger", page.getByRole("button", { name: /^Search commands/ })],
        ["rail link", rail(page).getByRole("link", { name: "Replay", exact: true })],
      ] as const) {
        await keyFocus(page, target);
        await page.keyboard.press("Control+/");
        const dialog = page.getByRole("dialog", { name: "Keyboard shortcuts" });
        await dialog.waitFor({ timeout: STEP_MS });
        const inside = await dialog.evaluate((d) => d.contains(document.activeElement));
        await page.keyboard.press("Escape");
        await dialog.waitFor({ state: "hidden", timeout: STEP_MS });
        const at = await r.now();
        const want = label === "rail link" ? "Replay" : "Search commands";
        out.push(
          r.ok(
            `cheatsheet from the ${label}: focus enters, Esc returns`,
            "2.4.3",
            inside && at.includes(want),
            `inside ${inside}; after Esc: ${at}`,
          ),
        );
      }
      return out;
    },
  },
  {
    // Collapsed rail: the echo tooltip dismisses on Esc and focus stays on the link (WCAG 1.4.13, E10-D04 13.2).
    state: STATES.owner,
    run: async (page, c) => {
      const r = rows1(page, "rail-collapsed", c);
      await keyFocus(page, toggle(page));
      await page.keyboard.press("Enter");
      await expect(toggle(page)).toHaveAttribute("aria-expanded", "false", { timeout: STEP_MS });
      await page.keyboard.press("Tab");
      const link = rail(page).getByRole("link").first();
      const tip = page.locator('[role="tooltip"]:not([hidden])').filter({ hasText: /Terminal/u });
      await link.focus();
      await tip
        .first()
        .waitFor({ timeout: STEP_MS })
        .catch(() => undefined);
      const shown = await tip.count();
      await page.keyboard.press("Escape");
      const after = await tip.count();
      const at = await r.now();
      return [
        r.ok(
          "the collapsed rail link shows its echo on keyboard focus",
          "1.4.13",
          shown > 0,
          `tooltips shown: ${shown}`,
        ),
        r.ok(
          "Esc dismisses it and focus stays on the link",
          "1.4.13",
          after === 0 && at.includes("Terminal"),
          `tooltips after Esc: ${after}; focus ${at}`,
        ),
      ];
    },
  },
  {
    // SCR-157 blocking alertdialog: focus inside, Tab stays inside, Esc (= Continue read-only) returns to the search trigger.
    state: STATES.versionDialog,
    run: async (page, c) => {
      const r = rows1(page, "version-dialog", c);
      const dlg = page.getByRole("alertdialog");
      const inside = (): Promise<boolean> =>
        dlg.evaluate((d) => d.contains(document.activeElement));
      const first = await inside();
      let stays = true;
      for (let i = 0; i < 6; i += 1) {
        await page.keyboard.press("Tab");
        stays = stays && (await inside());
      }
      await page.keyboard.press("Escape");
      await dlg.waitFor({ state: "hidden", timeout: STEP_MS });
      const at = await r.now();
      return [
        r.ok("focus starts inside the dialog", "2.4.3", first, "inside after open"),
        r.ok("Tab never leaves the dialog while it is open", "2.1.2", stays, "6 Tab presses"),
        r.ok(
          "Esc dismisses; focus goes to the search trigger",
          "2.4.3",
          at.includes("Search commands"),
          `focus: ${at}`,
        ),
      ];
    },
  },
  {
    // CMP-076 chip: its details popover is deferred (ConnectionStatus.tsx), so the chip is a button with no action.
    // The probe records that; the moment a popover opens (a new group or aria-haspopup), the Esc check runs.
    state: STATES.owner,
    run: async (page, c) => {
      const r = rows1(page, "connection-popover", c);
      const chip = page.getByRole("button", { name: /^Connection/ });
      const groups = page.locator('[role="group"]');
      const before = await groups.count();
      await keyFocus(page, chip);
      await page.keyboard.press("Enter");
      const popup =
        (await chip.getAttribute("aria-haspopup")) !== null || (await groups.count()) > before;
      if (!popup) {
        const at = await r.now();
        const ok = r.ok(
          "connection popover: not built (no aria-haspopup, Enter opens nothing); focus stays on the chip",
          "2.4.3",
          at.includes("Connection"),
          `focus: ${at}`,
        );
        return [ok.pass ? { ...ok, skip: true } : ok];
      }
      await page.keyboard.press("Escape");
      await expect(groups).toHaveCount(before, { timeout: STEP_MS });
      const at = await r.now();
      return [
        r.ok(
          "Esc closes the popover and focus stays on the chip",
          "2.4.3",
          at.includes("Connection"),
          `focus: ${at}`,
        ),
      ];
    },
  },
];

test("keyboard: Esc and focus return per overlay", async ({ browser }) => {
  test.setTimeout(TIMEOUT.esc);
  const started = Date.now();
  const rows: Rec[] = [];
  const offsite: string[] = [];
  for (const { state, run } of ESC_CASES)
    await eachCell(browser, state, cells(), offsite, rows, (o, c) => run(o.page, c));
  await finish("keyboard-esc", rows, started, offsite);
});

// Focus visible on every overlay surface (the drawer, the cheatsheet, the dialog, a banner band): Tab through each.
test("keyboard: focus visible on overlay surfaces", async ({ browser }) => {
  test.setTimeout(TIMEOUT.esc);
  const started = Date.now();
  const rows: Rec[] = [];
  const offsite: string[] = [];
  for (const s of [OPEN.drawer, OPEN.cheatsheet, STATES.versionDialog, STATES.banner, STATES.down])
    await eachCell(browser, s, cells(), offsite, rows, async (o, c) => {
      const stops: Stop[] = [];
      for (let i = 0; i < 12; i += 1) {
        await o.page.keyboard.press("Tab");
        const f = await o.page.evaluate(() => window.__cvq.focused());
        if (f !== null) stops.push(f);
      }
      const p = ringProblems(stops);
      return [
        rec(
          "focus visible on the surface's controls",
          s.id,
          cellOf(c),
          "2.4.7 / 2.4.11 / 2.4.13",
          p.bad.length === 0 && stops.length > 0,
          p.bad.length === 0
            ? `${stops.length} stops: ${p.surfaces.join("; ")}`
            : p.bad.join(" | "),
          { surfaces: p.surfaces },
        ),
      ];
    });
  await finish("keyboard-overlay-focus", rows, started, offsite);
});

// ------------------------------------------------------------------------------------------ zoom / reflow
// WCAG 1.4.10 reflow: 1280 x 1024 at 400 % is 320 x 256 CSS px. 1.4.4: a 125 % text scale (the product's own
// text-scale setting, data-text-scale on the root) at the normal viewport.
const ZOOM_MODES = [
  {
    id: "reflow-320x256",
    viewport: { width: 320, height: 256 },
    textScale: undefined,
    sc: "1.4.10",
  },
  { id: "text-125", viewport: { width: 1280, height: 800 }, textScale: 125 as const, sc: "1.4.4" },
] as const;
const ZOOM_STATES = [
  STATES.owner,
  STATES.viewer,
  OPEN.drawer,
  OPEN.cheatsheet,
  OPEN.toast,
  STATES.banner,
  STATES.versionBanner,
  STATES.versionDialog,
  STATES.down,
  STATES.forbidden,
  STATES.notFound,
  STATES.crash,
];
/** What may legitimately be absent at 320 px: the closed rail's links (the toggle that opens them stays). */
const MAY_COLLAPSE = (name: string): boolean =>
  ["Terminal", "Rules", "Journal", "Replay", "Alerts", "Settings", "Admin"].includes(name);

/** The reflow measures of the open page, against the control names of the same state at 1280 x 800. */
async function reflowRecords(
  page: Page,
  name: string,
  c: CellSpec,
  mode: (typeof ZOOM_MODES)[number],
  baseline: string[],
): Promise<Rec[]> {
  const cell = cellOf(c);
  const [hscroll, over, clip, names] = await step(
    "measure",
    Promise.all([
      page.evaluate(() => window.__cvq.hscroll()),
      page.evaluate(() => window.__cvq.overflowing()),
      page.evaluate(() => window.__cvq.clipped()),
      page.evaluate(() => window.__cvq.controls()),
    ]),
  );
  // A control is the same control whatever its counters say: the chip's name carries an attempt number, an age and a
  // time ("Reconnecting (1), last data 00:00 ago, 21:54:43 UTC"), and the rail toggle's name follows its state.
  const norm = (n: string): string =>
    n
      .replace(/^(Collapse|Expand) navigation rail$/u, "Navigation rail toggle")
      .replace(/\d+/gu, "#");
  const have = names.map(norm);
  const lost = [...new Set(baseline.map(norm))].filter(
    (n) => !have.includes(n) && !MAY_COLLAPSE(n),
  );
  const id = `${mode.id}`;
  const unknownClip = clip.filter((c) => !c.startsWith("[F-7]"));
  return [
    rec(
      `${id}: no page-level horizontal scroll`,
      name,
      cell,
      mode.sc,
      !hscroll,
      hscroll ? "document scrolls horizontally" : "none",
    ),
    rec(
      `${id}: nothing past the viewport edge`,
      name,
      cell,
      mode.sc,
      over.length === 0,
      over.length === 0 ? "none" : over.slice(0, 5).join("; "),
    ),
    rec(
      `${id}: no clipped text without a full-text twin`,
      name,
      cell,
      mode.sc,
      unknownClip.length === 0,
      unknownClip.length === 0
        ? clip.length === 0
          ? "none"
          : `only the known F-7 toast title: ${clip.length}`
        : unknownClip.slice(0, 5).join("; "),
    ),
    rec(
      `${id}: no control lost against 1280 x 800`,
      name,
      cell,
      mode.sc,
      lost.length === 0,
      lost.length === 0 ? `${new Set(names).size} controls` : `lost: ${lost.join("; ")}`,
    ),
  ];
}

test("zoom: 400 % reflow and 125 % text scale", async ({ browser }) => {
  test.setTimeout(TIMEOUT.zoom);
  const started = Date.now();
  const rows: Rec[] = [];
  const offsite: string[] = [];
  for (const s of ZOOM_STATES) {
    const first = cells()[0];
    if (first === undefined) continue;
    let baseline: string[] = [];
    await eachCell(browser, s, [first], offsite, [], async (o) => {
      baseline = await o.page.evaluate(() => window.__cvq.controls());
      return [];
    });
    for (const mode of ZOOM_MODES) {
      const specs = cells({
        viewport: mode.viewport,
        ...(mode.textScale === undefined ? {} : { textScale: mode.textScale }),
      });
      await eachCell(browser, s, specs, offsite, rows, (o, c) =>
        reflowRecords(o.page, s.id, c, mode, baseline),
      );
    }
  }
  await finish("zoom", rows, started, offsite);
});

// ------------------------------------------------------------------------------------------ greyscale
const GREY = {
  badge: '[data-cmp="CMP-075"]',
  chip: "button[data-status]",
  region: 'section[aria-label="Connection"]',
  severity: "[data-severity]",
  version: "[data-version-banner]",
} as const;
const nonHue = (c: Cue): string[] =>
  [c.word ? "word" : "", c.icon ? "icon/glyph" : "", c.shape ? "shape" : ""].filter(
    (x) => x !== "",
  );
const GREY_STATES: { state: State; cues: (keyof typeof GREY)[] }[] = [
  { state: STATES.owner, cues: ["badge", "chip"] },
  { state: STATES.live, cues: ["badge", "chip"] },
  { state: STATES.down, cues: ["badge", "chip", "region"] },
  { state: STATES.banner, cues: ["badge", "severity"] },
  { state: STATES.versionBanner, cues: ["badge", "version"] },
];

/** The largest channel spread of a screenshot (0 = every pixel grey), decoded in a blank page of the same context. */
async function spread(ctx: BrowserContext, png: Buffer): Promise<number> {
  const blank = await ctx.newPage();
  try {
    return await blank.evaluate(async (b64) => {
      const img = new Image();
      img.src = `data:image/png;base64,${b64}`;
      await img.decode();
      const cv = document.createElement("canvas");
      cv.width = img.width;
      cv.height = img.height;
      const g = cv.getContext("2d", { willReadFrequently: true });
      if (g === null) throw new Error("no 2d context");
      g.drawImage(img, 0, 0);
      const d = g.getImageData(0, 0, cv.width, cv.height).data;
      let max = 0;
      for (let i = 0; i < d.length; i += 4)
        max = Math.max(
          max,
          Math.abs((d[i] ?? 0) - (d[i + 1] ?? 0)),
          Math.abs((d[i + 1] ?? 0) - (d[i + 2] ?? 0)),
        );
      return max;
    }, png.toString("base64"));
  } finally {
    await blank.close();
  }
}

test("greyscale: captures and non-hue cues", async ({ browser }) => {
  test.setTimeout(TIMEOUT.grey);
  const started = Date.now();
  const rows: Rec[] = [];
  const offsite: string[] = [];
  mkdirSync(join(OUT, "greyscale"), { recursive: true });
  for (const { state, cues } of GREY_STATES)
    await eachCell(browser, state, cells(), offsite, rows, async (o, c) => {
      const cell = cellOf(c);
      const out: Rec[] = [];
      await o.page.evaluate(() => (document.documentElement.style.filter = "grayscale(1)"));
      const png = await step("screenshot", o.page.screenshot({ animations: "disabled" }));
      const file = `${state.id}-${c.theme.name}-${c.density}.png`;
      writeFileSync(join(OUT, "greyscale", file), png);
      const dev = await step("grey check", spread(o.ctx, png));
      const filter = await o.page.evaluate(() => getComputedStyle(document.documentElement).filter);
      out.push(
        rec(
          "capture is grey (filter applied, no colour left)",
          state.id,
          cell,
          "1.4.1",
          filter === "grayscale(1)" && dev <= 2,
          `filter ${filter}; max channel spread ${dev}`,
          { file, sha256: sha256(png) },
        ),
      );
      for (const k of cues) {
        const cue = await o.page.evaluate((sel) => window.__cvq.cue(sel), GREY[k]);
        const kinds = cue === null ? [] : nonHue(cue);
        out.push(
          rec(
            `${k} carries a word, icon or shape`,
            state.id,
            cell,
            "1.4.1",
            kinds.length > 0,
            cue === null ? "element not found" : `${kinds.join(" + ")}: "${cue.text.slice(0, 40)}"`,
          ),
        );
      }
      const nav = await o.page.evaluate(() => window.__cvq.navCue());
      out.push(
        rec(
          "the active nav item differs from an inactive one by more than colour",
          state.id,
          cell,
          "1.4.1",
          nav !== null && nav.diff.length > 0,
          nav === null ? "no active or inactive item" : nav.diff.join("; "),
        ),
      );
      return out;
    });
  // The env badge differs between environments by more than its token colour.
  for (const c of cells()) {
    const word: string[] = [];
    for (const s of [STATES.owner, STATES.live]) {
      const o = await openCell(browser, s, c, offsite);
      try {
        const info = await o.page.evaluate((sel) => {
          const el = document.querySelector<HTMLElement>(sel);
          return el === null
            ? null
            : {
                text: el.innerText.replace(/\s+/g, " ").trim(),
                weight: getComputedStyle(el).fontWeight,
              };
        }, GREY.badge);
        word.push(JSON.stringify(info));
      } finally {
        await o.ctx.close();
      }
    }
    const [demo, live] = word.map(
      (w) => JSON.parse(w) as { text: string; weight: string } | null,
    ) as [{ text: string; weight: string } | null, { text: string; weight: string } | null];
    rows.push(
      rec(
        "DEMO and LIVE badges differ in word, glyph and weight",
        "env-badge",
        cellOf(c),
        "1.4.1",
        demo !== null && live !== null && demo.text !== live.text && demo.weight !== live.weight,
        `${demo?.text} (${demo?.weight}) vs ${live?.text} (${live?.weight})`,
      ),
    );
  }
  await finish("greyscale", rows, started, offsite);
});

// ------------------------------------------------------------------------------------------ computed names
// The agent-run screen-reader proxy, NOT a human pass: the browser's own accessibility tree (CDP
// Accessibility.getFullAXTree) against docs/design/E10/E10-D04-names.json. Every one of the table's rows gets a
// disposition: exact (name equals the table), template (the table row carries data; the build's name must start
// with the fixed part), built-differently (the check fails: the build and the table disagree), not-built (an absence
// probe that trips when the part lands), open (the table itself has no name yet) or not-exercised (no state here
// reaches it; the reason is recorded).
interface AxNode {
  readonly role: string;
  readonly name: string;
}
interface NameRow {
  readonly id: string;
  readonly name: string | null;
}
const namesDoc = JSON.parse(
  readFileSync(join(REPO, "docs/design/E10/E10-D04-names.json"), "utf8"),
) as { names: NameRow[] };
const docName = (id: string): string | null => {
  const row = namesDoc.names.find((n) => n.id === id);
  if (row === undefined) throw new Error(`names.json has no row ${id}`);
  return row.name;
};
async function axTree(ctx: BrowserContext, page: Page): Promise<AxNode[]> {
  const cdp = await ctx.newCDPSession(page);
  const { nodes } = (await step("ax tree", cdp.send("Accessibility.getFullAXTree"))) as {
    nodes: { ignored?: boolean; role?: { value: string }; name?: { value: string } }[];
  };
  await cdp.detach();
  return nodes
    .filter((n) => n.ignored !== true && n.role !== undefined && n.name?.value)
    .map((n) => ({ role: n.role?.value ?? "", name: n.name?.value ?? "" }));
}
type Kind =
  | { k: "exact"; role: string; match?: (n: AxNode) => boolean }
  | { k: "template"; role: string; prefix: string }
  | { k: "absent"; probe: (n: AxNode) => boolean; why: string }
  | { k: "open" }
  | { k: "not-exercised"; why: string };
interface NameCheck {
  readonly id: string;
  readonly state: State;
  readonly kind: Kind;
}
const NAME_CHECKS: NameCheck[] = [
  { id: "shell.env.live", state: STATES.live, kind: { k: "exact", role: "image" } },
  { id: "shell.env.demo", state: STATES.owner, kind: { k: "exact", role: "image" } },
  {
    id: "shell.env.unconfirmed",
    state: STATES.owner,
    kind: {
      k: "not-exercised",
      why: "the unconfirmed-environment state (Q9) needs a live session whose confirmation is pending; no stub reaches it",
    },
  },
  {
    id: "shell.statusbar.feed",
    state: STATES.down,
    kind: { k: "template", role: "button", prefix: "Connection: " },
  },
  {
    id: "shell.healthchip",
    state: STATES.owner,
    kind: {
      k: "absent",
      probe: (n) => /^Exchange WS: /u.test(n.name),
      why: "CMP-210 HealthChip is not built",
    },
  },
  {
    id: "shell.statusbar.latency",
    state: STATES.owner,
    kind: { k: "template", role: "StaticText", prefix: "WS latency: " },
  },
  {
    id: "shell.statusbar.killswitch",
    state: STATES.owner,
    kind: {
      k: "absent",
      probe: (n) => /^Kill switch/u.test(n.name),
      why: "the kill-switch slot is not built (E39)",
    },
  },
  {
    id: "shell.cluster.engaged",
    state: STATES.owner,
    kind: {
      k: "absent",
      probe: (n) => /^Kill switch: engaged/u.test(n.name),
      why: "the FREEZE pill is not built (E39)",
    },
  },
  { id: "shell.skiplink", state: STATES.owner, kind: { k: "exact", role: "link" } },
  { id: "shell.topbar.search", state: STATES.owner, kind: { k: "exact", role: "button" } },
  { id: "shell.topbar.overflow", state: STATES.owner, kind: { k: "open" } },
  {
    id: "shell.navrail.item",
    state: STATES.owner,
    kind: { k: "template", role: "link", prefix: "Alerts" },
  },
  {
    id: "shell.navrail.item.collapsed",
    state: STATES.owner,
    kind: { k: "not-exercised", why: "checked in the collapsed-rail case below" },
  },
  {
    id: "shell.navrail.current",
    state: STATES.owner,
    kind: {
      k: "absent",
      probe: (n) => /unsaved changes/u.test(n.name),
      why: "the workspace list is not built (E15)",
    },
  },
  {
    id: "shell.navrail.toggle.collapse",
    state: STATES.owner,
    kind: { k: "exact", role: "button" },
  },
  {
    id: "shell.navrail.toggle.expand",
    state: STATES.owner,
    kind: { k: "not-exercised", why: "checked in the collapsed-rail case below" },
  },
  {
    id: "shell.rightrail.launcher",
    state: STATES.owner,
    kind: { k: "template", role: "button", prefix: "Notifications" },
  },
  { id: "shell.rightrail.launcher.other", state: STATES.owner, kind: { k: "open" } },
  {
    id: "shell.toast.dismiss",
    state: OPEN.toast,
    kind: { k: "template", role: "button", prefix: "Dismiss " },
  },
  {
    id: "shell.toast.overflow",
    state: OPEN.toast,
    kind: { k: "not-exercised", why: "needs four or more toasts at once; the shell shows one" },
  },
  {
    id: "shell.cheatsheet.conflict",
    state: OPEN.cheatsheet,
    kind: {
      k: "not-exercised",
      why: "needs a conflicting binding; none ships in the default keymap",
    },
  },
  {
    id: "shell.cheatsheet.remapped",
    state: OPEN.cheatsheet,
    kind: { k: "not-exercised", why: "needs a remapped binding; none ships in the default keymap" },
  },
  {
    id: "shell.palette.confirms",
    state: STATES.owner,
    kind: {
      k: "absent",
      probe: (n) => /^Search commands.*dialog/iu.test(n.name),
      why: "the command palette (SCR-012) is not built (#5236)",
    },
  },
  {
    id: "shell.t2.lock",
    state: STATES.owner,
    kind: {
      k: "not-exercised",
      why: "checked as an aria-describedby text on the gated Account button below",
    },
  },
  {
    id: "shell.panel.readonly",
    state: STATES.viewer,
    kind: {
      k: "not-exercised",
      why: "the read-only panel notice belongs to the panels (E11, E30); the /journal placeholder has none",
    },
  },
  {
    id: "window.titlebar.more",
    state: STATES.owner,
    kind: {
      k: "absent",
      probe: (n) => n.name === "More window actions",
      why: "the floating window (SCR-027) is not built",
    },
  },
  {
    id: "window.titlebar.close",
    state: STATES.owner,
    kind: {
      k: "absent",
      probe: (n) => /^Close window/u.test(n.name),
      why: "the floating window (SCR-027) is not built",
    },
  },
  {
    id: "window.titlebar.return",
    state: STATES.owner,
    kind: {
      k: "absent",
      probe: (n) => n.name === "Return to workspace",
      why: "the floating window (SCR-027) is not built",
    },
  },
  {
    id: "window.titlebar.pin",
    state: STATES.owner,
    kind: {
      k: "absent",
      probe: (n) => n.name === "Pin on top",
      why: "the floating window (SCR-027) is not built",
    },
  },
  { id: "shell.statusbar.region", state: STATES.owner, kind: { k: "exact", role: "status" } },
  {
    id: "shell.scr157.dialog",
    state: STATES.versionDialog,
    kind: { k: "exact", role: "alertdialog" },
  },
  { id: "shell.scr156.fallback", state: STATES.panelCrash, kind: { k: "exact", role: "heading" } },
];

test("names: computed accessible names against E10-D04-names.json", async ({ browser }) => {
  test.setTimeout(TIMEOUT.names);
  const started = Date.now();
  const rows: Rec[] = [];
  const offsite: string[] = [];
  const c: CellSpec = { theme: THEMES[0], density: "compact" };
  const trees = new Map<string, AxNode[]>();
  for (const state of [...NAME_CHECKS.map((n) => n.state), STATES.crash]) {
    if (trees.has(state.id)) continue;
    const o = await openCell(browser, state, c, offsite);
    try {
      trees.set(state.id, await axTree(o.ctx, o.page));
      if (state.id === "chrome-owner") {
        // Collapsed rail: the toggle's own name flips, and each link keeps its name (the visible label is gone).
        await toggle(o.page).click({ timeout: STEP_MS });
        await expect(toggle(o.page)).toHaveAttribute("aria-expanded", "false", {
          timeout: STEP_MS,
        });
        trees.set("rail-collapsed", await axTree(o.ctx, o.page));
        const gated = await o.page
          .getByRole("button", { name: "Account" })
          .evaluate(
            (b) =>
              document.getElementById(b.getAttribute("aria-describedby") ?? "")?.textContent ??
              null,
          );
        rows.push(
          rec(
            "shell.t2.lock: the gated control says why",
            state.id,
            cellOf(c),
            "4.1.2",
            gated !== null && gated.startsWith(docName("shell.t2.lock") ?? "?"),
            `documented "${docName("shell.t2.lock")}"; built description "${gated}"`,
          ),
        );
      }
    } finally {
      await o.ctx.close();
    }
  }
  const collapsed = trees.get("rail-collapsed") ?? [];
  rows.push(
    rec(
      "shell.navrail.toggle.expand: the collapsed toggle is named",
      "rail-collapsed",
      cellOf(c),
      "4.1.2",
      collapsed.some(
        (n) => n.role === "button" && n.name === docName("shell.navrail.toggle.expand"),
      ),
      `documented "${docName("shell.navrail.toggle.expand")}"`,
    ),
    rec(
      "shell.navrail.item.collapsed: links keep their names when collapsed",
      "rail-collapsed",
      cellOf(c),
      "4.1.2",
      ["Terminal", "Journal", "Alerts", "Admin"].every((l) =>
        collapsed.some((n) => n.role === "link" && n.name.startsWith(l)),
      ),
      `documented "${docName("shell.navrail.item.collapsed")}" (count and key are template data)`,
    ),
  );
  for (const { id, state, kind } of NAME_CHECKS) {
    const tree = trees.get(state.id) ?? [];
    const want = docName(id);
    const cell = cellOf(c);
    const sc = "4.1.2";
    if (kind.k === "open")
      rows.push(
        rec(
          id,
          state.id,
          cell,
          sc,
          true,
          "the table row is open (no name yet): nothing to compare",
          undefined,
          true,
        ),
      );
    else if (kind.k === "not-exercised")
      rows.push(rec(id, state.id, cell, sc, true, kind.why, undefined, true));
    else if (kind.k === "absent") {
      const hit = tree.filter(kind.probe).map((n) => n.name);
      rows.push(
        rec(
          id,
          state.id,
          cell,
          sc,
          hit.length === 0,
          hit.length === 0
            ? `not built (${kind.why}); absence probe clean`
            : `now built: ${hit.join("; ")}; add the exact-name check`,
          undefined,
          hit.length === 0,
        ),
      );
    } else if (kind.k === "exact") {
      const hit = tree.filter((n) => n.role === kind.role && n.name === want);
      const near = tree
        .filter(
          (n) =>
            n.role === kind.role &&
            n.name.toLowerCase().replace(/[^a-z]/gu, "") ===
              (want ?? "").toLowerCase().replace(/[^a-z]/gu, ""),
        )
        .map((n) => n.name);
      rows.push(
        rec(
          id,
          state.id,
          cell,
          sc,
          hit.length >= 1,
          hit.length >= 1
            ? `${kind.role} "${want}"`
            : `no ${kind.role} named "${want}"${
                near.length > 0
                  ? `; built name "${near.join("; ")}"`
                  : `; built ${kind.role}s: ${
                      tree
                        .filter((n) => n.role === kind.role)
                        .map((n) => `"${n.name}"`)
                        .slice(0, 6)
                        .join(", ") || "none"
                    }`
              }`,
        ),
      );
    } else {
      const hit = tree.filter((n) => n.role === kind.role && n.name.startsWith(kind.prefix));
      rows.push(
        rec(
          id,
          state.id,
          cell,
          sc,
          hit.length >= 1,
          hit.length >= 1
            ? `template "${want}" vs built "${hit[0]?.name}"`
            : `no ${kind.role} starts with "${kind.prefix}" (documented "${want}")`,
        ),
      );
    }
  }
  // SCR-156's route-level fallback is not in names.json (the table's row is the panel level); its copy is the board's.
  const routeCrash = (trees.get("route-crash") ?? [])
    .filter((n) => n.role === "heading")
    .map((n) => n.name);
  rows.push(
    rec(
      "SCR-156 route-level fallback is headed by the board's sentence",
      "route-crash",
      cellOf(c),
      "4.1.2",
      routeCrash.includes("Something went wrong"),
      `headings: ${routeCrash.join(", ")}`,
    ),
  );
  // Every rail link is named by its label alone (no count in the stub), so a name never repeats or hides its role.
  const links = (trees.get("chrome-owner") ?? [])
    .filter((n) => n.role === "link")
    .map((n) => n.name);
  rows.push(
    rec(
      "the rail's links are named by their labels",
      "chrome-owner",
      cellOf(c),
      "2.4.4",
      ["Terminal", "Rules", "Journal", "Replay", "Alerts", "Settings", "Admin"].every((l) =>
        links.includes(l),
      ),
      links.join(", "),
    ),
  );
  await finish("names", rows, started, offsite);
});

// BQ-6 (the safety-signal fidelity check, absorbed from E10-D05): CMP-075 may not carry a raw colour literal, so
// it cannot drift from the env tokens; the matrix captures of the badge go to the designer (OR-7).
test("names: CMP-075 token audit and designer captures", async ({ browser }) => {
  test.setTimeout(TIMEOUT.names);
  const started = Date.now();
  const rows: Rec[] = [];
  const offsite: string[] = [];
  const src = readFileSync(
    join(REPO, "apps/web/src/features/app-shell/TopBarEnvBadge.tsx"),
    "utf8",
  );
  const code = src.replace(/\/\*[\s\S]*?\*\/|(^|[^:])\/\/.*$/gmu, "$1");
  const literals = code.match(/#[0-9a-fA-F]{3,8}\b|\b(?:rgb|rgba|hsl|hsla|oklch|oklab)\(/gu) ?? [];
  rows.push(
    rec(
      "TopBarEnvBadge.tsx holds no raw colour literal",
      "env-badge",
      { theme: "all", density: "all" },
      "1.4.1",
      literals.length === 0,
      literals.length === 0 ? "only var(--color-*) tokens" : literals.join(" "),
    ),
  );
  mkdirSync(join(OUT, "designer"), { recursive: true });
  for (const s of [STATES.owner, STATES.live])
    for (const c of cells()) {
      const o = await openCell(browser, s, c, offsite);
      try {
        const png = await step(
          "badge capture",
          o.page.locator(GREY.badge).screenshot({ animations: "disabled" }),
        );
        writeFileSync(join(OUT, "designer", `badge-${s.id}-${c.theme.name}-${c.density}.png`), png);
        const colour = await o.page.evaluate(
          (sel) => getComputedStyle(document.querySelector(sel) as Element).borderTopColor,
          GREY.badge,
        );
        rows.push(
          rec(
            "badge border is the env token, captured for the designer",
            s.id,
            cellOf(c),
            "1.4.1",
            png.length > 0 && colour !== "",
            `border ${colour}`,
            { sha256: sha256(png) },
          ),
        );
      } finally {
        await o.ctx.close();
      }
    }
  await finish("token-audit", rows, started, offsite);
});

// ------------------------------------------------------------------------------------------ announcements
// The connection chip re-renders at 1 Hz while disconnected (its "last data mm:ss ago"). On a fake clock
// (page.clock) run 40 s of seconds: the chip must tick every second, while the shell's live regions announce once
// per episode, at most one message per 5 s per region (E17-D02 11), and the UTC clock is never inside a live region.
const EPISODE_S = 40;
test("announce: the 1 Hz chip is announced once per episode, not once per tick", async ({
  browser,
}) => {
  test.setTimeout(TIMEOUT.announce);
  const started = Date.now();
  const offsite: string[] = [];
  const c: CellSpec = { theme: THEMES[0], density: "compact" };
  const o = await openCell(browser, STATES.owner, c, offsite);
  const rows: Rec[] = [];
  try {
    await o.page.clock.install();
    await o.page.evaluate(() => {
      const w = window as unknown as { __ann: { region: string; text: string; t: number }[] };
      w.__ann = [];
      const last = new Map<string, string>();
      new MutationObserver(() => {
        for (const el of document.querySelectorAll<HTMLElement>(
          '[aria-live],[role="status"],[role="alert"]',
        )) {
          const key = `${el.getAttribute("aria-live") ?? el.getAttribute("role")}#${[...document.querySelectorAll('[aria-live],[role="status"],[role="alert"]')].indexOf(el)}`;
          const text = (el.textContent ?? "").trim();
          if (
            text !== "" &&
            last.get(key) !== text &&
            el.getAttribute("aria-label") !== "System status"
          )
            w.__ann.push({ region: key, text, t: Date.now() });
          last.set(key, text);
        }
      }).observe(document.body, { subtree: true, childList: true, characterData: true });
    });
    o.ws?.kill();
    await o.page.getByRole("region", { name: "Connection" }).waitFor({ timeout: STEP_MS });
    const chipTexts = new Set<string>();
    for (let i = 0; i < EPISODE_S; i += 1) {
      await step(`run clock ${i + 1} s`, o.page.clock.runFor(1000));
      chipTexts.add(await o.page.locator("button[data-status]").innerText());
    }
    const ann = await o.page.evaluate(
      () => (window as unknown as { __ann: { region: string; text: string; t: number }[] }).__ann,
    );
    const byRegion = new Map<string, number[]>();
    for (const a of ann) byRegion.set(a.region, [...(byRegion.get(a.region) ?? []), a.t]);
    const gaps = [...byRegion.values()].flatMap((ts) =>
      ts.slice(1).map((t, i) => t - (ts[i] ?? t)),
    );
    const clockInLive = await o.page.evaluate(() => {
      const clock = [...document.querySelectorAll<HTMLElement>("footer *, [role=status] *")].find(
        (e) =>
          e.children.length === 0 && /^\d\d:\d\d:\d\d UTC$/u.test((e.textContent ?? "").trim()),
      );
      return clock === undefined
        ? null
        : clock.closest('[aria-live],[role="status"],[role="alert"]') !== null;
    });
    const cell = cellOf(c);
    rows.push(
      rec(
        "the chip ticks every second (the 1 Hz path really ran)",
        "connection-down",
        cell,
        "4.1.3",
        chipTexts.size >= EPISODE_S - 2,
        `${chipTexts.size} distinct chip texts in ${EPISODE_S} fake seconds`,
      ),
      rec(
        "announced messages: once per episode, not per tick",
        "connection-down",
        cell,
        "4.1.3",
        ann.length >= 1 && ann.length <= 1 + Math.floor(EPISODE_S / 5),
        `${ann.length} announcements in ${EPISODE_S} s: ${ann.map((a) => `${a.region}@${Math.round((a.t - (ann[0]?.t ?? 0)) / 1000)}s`).join(", ")}`,
        ann,
      ),
      rec(
        "at most one message per 5 s per region",
        "connection-down",
        cell,
        "4.1.3",
        gaps.every((g) => g >= 4900),
        `smallest gap ${gaps.length === 0 ? "n/a (one message)" : `${Math.min(...gaps)} ms`}`,
      ),
      rec(
        "the UTC clock is outside every live region",
        "connection-down",
        cell,
        "4.1.3",
        clockInLive === false,
        clockInLive === null ? "clock not found" : `inside a live region: ${clockInLive}`,
      ),
    );
  } finally {
    await o.ctx.close();
  }
  await finish("announce", rows, started, offsite);
});

// ------------------------------------------------------------------------------------------ negative controls
// Each detector the passes above rely on must trip on an injected defect, or the run is A11Y-INFRA.
async function control(
  browser: Browser,
  name: string,
  run: (page: Page, c: CellSpec) => Promise<Rec[]>,
): Promise<void> {
  test.setTimeout(TIMEOUT.control);
  const started = Date.now();
  const offsite: string[] = [];
  const c: CellSpec = { theme: THEMES[0], density: "compact" };
  const o = await openCell(browser, STATES.owner, c, offsite);
  try {
    const rows = await run(o.page, c);
    const bad = rows.filter((r) => !r.pass);
    const body = JSON.stringify({ name, ms: Date.now() - started, rows }, null, 2);
    mkdirSync(OUT, { recursive: true });
    writeFileSync(join(OUT, `control-${name}.json`), body);
    expect(bad.map((r) => `A11Y-INFRA: ${r.detail}`)).toEqual([]);
  } finally {
    await o.ctx.close();
  }
}
const ctl = (c: CellSpec) => cellOf(c);

test("negative control: an injected focus trap (fixed point and cycle) is detected", async ({
  browser,
}) => {
  await control(browser, "trap", async (page, c) => {
    const trap = async (js: () => void): Promise<Walk> => {
      await page.evaluate(js);
      return walkTab(page);
    };
    const fixed = await trap(() => {
      addEventListener(
        "keydown",
        (e) => {
          if (e.key !== "Tab") return;
          e.preventDefault();
          document.querySelector<HTMLElement>("nav a")?.focus();
        },
        true,
      );
    });
    await page.reload();
    await page.getByRole("heading", { level: 1 }).first().waitFor({ timeout: STEP_MS });
    const cyc = await trap(() => {
      let n = 0;
      addEventListener(
        "keydown",
        (e) => {
          if (e.key !== "Tab") return;
          e.preventDefault();
          document.querySelectorAll<HTMLElement>("nav a")[n++ % 2]?.focus();
        },
        true,
      );
    });
    return [
      rec(
        "fixed-point trap detected",
        "control",
        ctl(c),
        "2.1.2",
        fixed.end === "fixed-point",
        `walk ended ${fixed.end}`,
      ),
      rec(
        "two-element cycle detected",
        "control",
        ctl(c),
        "2.1.2",
        cyc.end === "cycle",
        `walk ended ${cyc.end}`,
      ),
    ];
  });
});

test("negative control: an injected clip, overflow and hue-only cue are detected", async ({
  browser,
}) => {
  await control(browser, "clip-hue", async (page, c) => {
    await page.evaluate(() => {
      document.body.insertAdjacentHTML(
        "beforeend",
        '<div id="clip" style="width:60px;overflow:hidden;white-space:nowrap">A long label that cannot fit its box</div>' +
          '<div id="twin" title="A long label with a full-text twin" style="width:60px;overflow:hidden;white-space:nowrap">A long label with a full-text twin</div>' +
          '<div id="wide" style="width:4000px;height:6px"></div>' +
          '<span id="hue" data-cmp="CMP-075" style="display:inline-block;width:16px;height:16px;background:rgb(200,0,0)"></span>' +
          '<span id="word" style="display:inline-block;background:rgb(200,0,0)">LIVE</span>',
      );
      const on = document.querySelector<HTMLElement>('nav a[aria-current="page"]');
      for (const [k, v] of [
        ["border-left-width", "0"],
        ["border-left-style", "none"],
        ["font-weight", "400"],
        ["color", "rgb(200,0,0)"],
      ] as const)
        on?.style.setProperty(k, v);
    });
    const [clip, over, hscroll, hue, word, nav] = await Promise.all([
      page.evaluate(() => window.__cvq.clipped()),
      page.evaluate(() => window.__cvq.overflowing()),
      page.evaluate(() => window.__cvq.hscroll()),
      page.evaluate(() => window.__cvq.cue("#hue")),
      page.evaluate(() => window.__cvq.cue("#word")),
      page.evaluate(() => window.__cvq.navCue()),
    ]);
    return [
      rec(
        "clipped text without a twin is detected, one with a twin is not",
        "control",
        ctl(c),
        "1.4.4",
        clip.some((x) => x.includes("cannot fit")) && !clip.some((x) => x.includes("twin")),
        clip.join("; "),
      ),
      rec(
        "overflow past the viewport is detected",
        "control",
        ctl(c),
        "1.4.10",
        hscroll && over.some((x) => x.includes("div")),
        `hscroll ${hscroll}; ${over.slice(0, 2).join("; ")}`,
      ),
      rec(
        "a hue-only cue is detected (no word, icon or shape)",
        "control",
        ctl(c),
        "1.4.1",
        hue !== null && nonHue(hue).length === 0 && word !== null && nonHue(word).length > 0,
        `bare swatch: ${hue === null ? "missing" : nonHue(hue).join("+") || "none"}; word chip: ${word === null ? "missing" : nonHue(word).join("+")}`,
      ),
      rec(
        "a colour-only active nav item is detected",
        "control",
        ctl(c),
        "1.4.1",
        nav !== null && nav.diff.length === 0,
        `non-colour differences: ${nav === null ? "n/a" : nav.diff.join("; ") || "none"}`,
      ),
    ];
  });
});

test("negative control: an injected outline-less focus is detected", async ({ browser }) => {
  await control(browser, "focus", async (page, c) => {
    await page.evaluate(() => {
      document
        .querySelector("header")
        ?.insertAdjacentHTML(
          "beforeend",
          '<button id="bare" style="outline:none">x</button><button id="faint" style="outline:2px solid rgb(30,35,42)">y</button>',
        );
    });
    await page.keyboard.press("Shift");
    const read = async (sel: string): Promise<Stop | null> => {
      await page.locator(sel).focus();
      return page.evaluate(() => window.__cvq.focused());
    };
    const bare = await read("#bare");
    const faint = await read("#faint"); // a 2 px solid ring that is nearly the surface colour: the contrast branch
    const faintBad = faint === null ? [] : ringProblems([faint]).bad;
    const real = await page.evaluate(() => window.__cvq.tabbables().length);
    return [
      rec(
        "an outline-less focus is detected",
        "control",
        ctl(c),
        "2.4.7",
        bare !== null && ringProblems([bare]).bad.length > 0,
        bare === null ? "no focus" : ringProblems([bare]).bad.join("; "),
      ),
      rec(
        "a 2 px ring below 3:1 against its surface is detected (and is not an outline-style fault)",
        "control",
        ctl(c),
        "2.4.13",
        faintBad.length > 0 &&
          faintBad.every((b) => b.includes("< 3:1") && !b.includes("no outline")),
        faintBad.join("; ") || "not detected",
      ),
      rec(
        "the page still has tabbable controls (the control did not blank it)",
        "control",
        ctl(c),
        "2.1.1",
        real > 3,
        `${real} tabbable`,
      ),
    ];
  });
});
