// E47-T01 (#1323) baseline WCAG 2.2 AA sweep: the committed Playwright driver (BQ-07 (b) of the #1323
// ruling of record). One file, the per-screen stubs as data, no new dependency, no apps/web change: it
// reuses apps/web's Playwright, axe and e2e support (stub API, WS harness, test-only TOTP seed).
//
// Modes (A11Y_MODE):
//   automated  axe (AXE_GATE_TAGS, color-contrast on, every impact) per reachable screen x state x theme
//   wcag22     the six WCAG 2.2 criteria aids (2.4.11, 2.5.7, 2.5.8, 3.2.6, 3.3.7, 3.3.8) at 1280x800
//              and 200 % zoom; every verdict is judged by hand from this output (BQ-09)
//   deep       05 §8.2 keyboard task scripts on SCR-001..006, SCR-152, SCR-156 x three themes (BQ-08 (b))
//   spot       spot check on SCR-113, SCR-116, SCR-117 x three themes (BQ-08 (b)), with a pixel check of
//              axe's color-contrast incomplete nodes (contrastSpot)
//   sanity     the instruments detect known violations on the public 404 page
//
// Environment: A11Y_SHA (the audited sha, recorded), A11Y_ONLY (comma-separated SCR ids),
// A11Y_THEMES (comma-separated subset of dark,light,high-contrast), A11Y_PORT (vite preview port,
// default 4174), A11Y_OUT (results directory; default <os temp>/e47-t01-sweep/<mode>; refused if it
// is inside the repository). Each mode writes <A11Y_OUT>/results.json with a per-screen wall-clock.
//
// BQ-10 (security), enforced here, not by convention:
// - no PNG of any authentication surface (shot() refuses AUTH screens); PNGs are only 2.5.8 failing
//   target clips and below-threshold contrast clips elsewhere, never of a target that holds value text;
// - on SCR-003 / SCR-005 / SCR-006 / SCR-149 and SCR-017's secret and codes steps only roles and
//   accessible names are kept: ariaSnapshot lines are cut to role + name, live-region text is kept only
//   when it equals fixed app copy, values are `<redacted>`;
// - every string written is scrubbed of secret-shaped runs, and the serialised output is refused if it
//   still holds the test seed, an issued code or a typed stub credential.
// Network: every request to a host other than loopback is aborted and counted per run.
import { mkdirSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve, sep } from "node:path";
import AxeBuilder from "@axe-core/playwright";
import {
  test,
  type Browser,
  type BrowserContext,
  type CDPSession,
  type Locator,
  type Page,
  type Route,
} from "@playwright/test";
import type * as ApiModule from "../../../../apps/web/e2e/support/api";
import type * as WsModule from "../../../../apps/web/e2e/support/wsHarness";
import type { GatewayOptions, WsHarness } from "../../../../apps/web/e2e/support/wsHarness";
import type * as TotpModule from "../../../../apps/web/e2e/support/totp";
import type * as TagsModule from "../../../../apps/web/e2e/a11y/tags";

// apps/web's e2e support is ESM (apps/web is "type": "module") and this directory is CommonJS (the repo
// root has no "type"), so the support modules are loaded with a dynamic import before the run starts.
let json: (typeof ApiModule)["json"];
let sessionInfo: (typeof ApiModule)["sessionInfo"];
let stubSession: (typeof ApiModule)["stubSession"];
let stubSessionsList: (typeof ApiModule)["stubSessionsList"];
let installWsHarness: (typeof WsModule)["installWsHarness"];
let OTP_SEED: (typeof TotpModule)["OTP_SEED"];
let totp: (typeof TotpModule)["totp"];
let AXE_GATE_TAGS: (typeof TagsModule)["AXE_GATE_TAGS"];
async function loadSupport(): Promise<void> {
  const api = await import("../../../../apps/web/e2e/support/api");
  const ws = await import("../../../../apps/web/e2e/support/wsHarness");
  const otp = await import("../../../../apps/web/e2e/support/totp");
  const tags = await import("../../../../apps/web/e2e/a11y/tags");
  ({ json, sessionInfo, stubSession, stubSessionsList } = api);
  ({ installWsHarness } = ws);
  ({ OTP_SEED, totp } = otp);
  ({ AXE_GATE_TAGS } = tags);
}

// ------------------------------------------------------------------------------------------ config

const ENV = process.env;
const MODES = ["automated", "wcag22", "deep", "spot", "sanity"] as const;
type Mode = (typeof MODES)[number];
const MODE = (ENV["A11Y_MODE"] ?? "automated") as Mode;
if (!MODES.includes(MODE)) throw new Error(`A11Y_MODE must be one of ${MODES.join(", ")}`);
const SHA = ENV["A11Y_SHA"] ?? "unknown";
const ONLY = ENV["A11Y_ONLY"] ? new Set(ENV["A11Y_ONLY"].split(",").map((s) => s.trim())) : null;
const PORT = ENV["A11Y_PORT"] ?? "4174";
const ORIGIN = `http://127.0.0.1:${PORT}`;
const REPO = resolve(__dirname, "../../../..");
const OUT = resolve(ENV["A11Y_OUT"] ?? join(tmpdir(), "e47-t01-sweep", MODE));
if (OUT === REPO || OUT.startsWith(REPO + sep))
  throw new Error("A11Y_OUT must be outside the repository (results are never committed raw)");
const LOOPBACK = new Set(["127.0.0.1", "localhost"]);
const W = 15_000;

type ThemeName = "dark" | "light" | "high-contrast";
interface Theme {
  readonly name: ThemeName;
  readonly appearance: { readonly theme: "dark" | "light"; readonly high_contrast: boolean };
  readonly local: {
    readonly baseTheme: "dark" | "light";
    readonly matchSystem: false;
    readonly highContrast: boolean;
  };
}
const ALL_THEMES: readonly Theme[] = [
  {
    name: "dark",
    appearance: { theme: "dark", high_contrast: false },
    local: { baseTheme: "dark", matchSystem: false, highContrast: false },
  },
  {
    name: "light",
    appearance: { theme: "light", high_contrast: false },
    local: { baseTheme: "light", matchSystem: false, highContrast: false },
  },
  {
    name: "high-contrast",
    appearance: { theme: "dark", high_contrast: true },
    local: { baseTheme: "dark", matchSystem: false, highContrast: true },
  },
];
const THEMES: readonly Theme[] = ENV["A11Y_THEMES"]
  ? ALL_THEMES.filter((t) => ENV["A11Y_THEMES"]?.split(",").includes(t.name))
  : ALL_THEMES;
const DARK = ALL_THEMES[0] as Theme; // index 0 is always present (literal above)

// ------------------------------------------------------------------------------ BQ-10 redaction

/** Authentication surfaces (BQ-10): no PNG, and value fields are never read back. */
const AUTH = new Set([
  "SCR-001",
  "SCR-002",
  "SCR-003",
  "SCR-004",
  "SCR-005",
  "SCR-006",
  "SCR-017",
  "SCR-149",
]);
/** Surfaces where only roles and accessible names may be captured (BQ-10). */
const NO_TEXT = new Set(["SCR-003", "SCR-005", "SCR-006", "SCR-149"]);
const noText = (scr: string, state: string): boolean =>
  NO_TEXT.has(scr) || (scr === "SCR-017" && /step 3|step 4|authenticator|codes/i.test(state));
/** Secret-shaped runs: 6+ digits, base32 runs, stub recovery codes, otpauth URIs, invite tokens, UUIDs. */
const SECRETISH =
  /\b\d{6,}\b|\b[A-Z2-7]{16,}\b|\brc-\d+\b|otpauth:\S*|\binv-[\w-]+|\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b/g;
/** Fixed app copy that may be quoted from live regions on NO_TEXT surfaces. */
const COPY = new Set([
  "Incorrect code.",
  "Not sent",
  "Cannot reach the server. Try again.",
  "Incorrect password. Try again.",
  "Verifying...",
  "Too many attempts. Wait a minute, then try again.",
  "Couldn't reach the server. Try again.",
  "That code did not work. Try again.",
  "That password does not meet the policy.",
]);
/** Stub credentials this driver types; the output is refused if any survives the scrub. */
const STUB = {
  user: "ann",
  password: "pw-a1",
  newPassword: "correct horse battery",
  stepUpPassword: "stub-pw",
  wrongPassword: "stub-wrong",
  rightPassword: "stub-right",
  anyPassword: "stub-any",
  oldPassword: "old-stub-pw",
  wrongOld: "wrong-stub-pw",
  policyPassword: "abcdefghijklmn",
  pasteText: "stub-paste-value",
  pasteCode: "246810",
  wrongCode: "000000",
} as const;
const issued = new Set<string>();
/** A TOTP code from the e2e test seed; remembered so the output guard can refuse it. */
const code = (): string => {
  const c = totp(OTP_SEED, Date.now());
  issued.add(c);
  return c;
};

const scrubText = (s: string): string => s.replace(SECRETISH, "<redacted>");
function scrub(v: unknown): unknown {
  if (typeof v === "string") return scrubText(v);
  if (Array.isArray(v)) return v.map(scrub);
  if (v && typeof v === "object")
    return Object.fromEntries(
      Object.entries(v as Record<string, unknown>).map(([k, x]) => [k, scrub(x)]),
    );
  return v;
}
/** ariaSnapshot redaction: auth screens lose textbox values and code text; NO_TEXT keeps role + name. */
function redactSnap(snap: string, scr: string, state: string): string {
  let s = scrubText(snap).replace(/(\/url:).*$/gm, "$1 <redacted>");
  if (AUTH.has(scr))
    s = s
      .split("\n")
      .map((l) => {
        if (/^\s*- (textbox|searchbox|spinbutton|combobox)\b/.test(l))
          return l.replace(/(".*?"(?: \[[^\]]*\])*)\s*:.*$/, "$1: <redacted>");
        if (/^\s*- code\b/.test(l) || /^\s*- listitem\b.*code/.test(l))
          return l.replace(/:.*$/, ": <redacted>");
        if (/^\s*- text: Key:/.test(l)) return l.replace(/Key:.*$/, "Key: <redacted>");
        return l;
      })
      .join("\n");
  if (noText(scr, state))
    s = s
      .split("\n")
      .map((l) => l.replace(/^(\s*- [\w-]+(?: "[^"]*")?(?: \[[^\]]*\])*):\s.*$/, "$1: <redacted>"))
      .map((l) => l.replace(/^(\s*- text):.*$/, "$1: <redacted>"))
      .join("\n");
  return s;
}
/** Writes <OUT>/<name> after the scrub; refuses output that still holds a seed, code or credential. */
function emit(name: string, data: unknown): void {
  const text = JSON.stringify(scrub(data), null, 2);
  const banned = [OTP_SEED, ...issued, ...Object.values(STUB).filter((x) => x.length >= 6)];
  for (const b of banned)
    if (text.includes(b))
      throw new Error(
        `BQ-10 guard: output would hold a secret-shaped stub value (${b.length} chars); not written`,
      );
  mkdirSync(OUT, { recursive: true });
  writeFileSync(join(OUT, name), text + "\n");
}
let shotCount = 0;
/** BQ-25 / BQ-10: a clip PNG for a finding, never of an auth surface, capped. */
async function shot(
  page: Page,
  scr: string,
  clip: { x: number; y: number; width: number; height: number },
): Promise<string | null> {
  if (AUTH.has(scr)) throw new Error(`BQ-10 guard: no PNG of ${scr}`);
  if (shotCount >= 40) return null;
  shotCount += 1;
  const file = `img/${scr}-${shotCount}.png`;
  mkdirSync(join(OUT, "img"), { recursive: true });
  await page.screenshot({ path: join(OUT, file), clip });
  return file;
}
const firstLine = (e: unknown): string =>
  scrubText((e instanceof Error ? e.message : String(e)).split("\n")[0] ?? "")
    .replace(/value="[^"]*"/g, 'value="<redacted>"')
    .slice(0, 220);

// ------------------------------------------------------------------------- per-screen stubs (data)

type Role = "owner" | "manager" | "viewer";
interface Ctx {
  readonly page: Page;
  readonly ws: WsHarness | undefined;
}
interface Step {
  readonly label: string;
  readonly go: (c: Ctx) => Promise<void>;
}
interface Screen {
  readonly scr: string;
  readonly path: string;
  /** Signed in as this role; absent = signed out. */
  readonly role?: Role;
  readonly ws?: GatewayOptions | true;
  /** Rewrite the harness's welcome.server_version (SCR-157). */
  readonly newerServer?: true;
  readonly stubs?: (page: Page) => Promise<void>;
  /** Reach the screen's default state (a built part for partial rows, never a StubRoute). */
  readonly open: (c: Ctx) => Promise<void>;
  readonly steps?: readonly Step[];
  /** Sets window.__qaScope to the elements the screen owns (wcag22); absent = whole page. */
  readonly scope?: (page: Page) => Promise<void>;
  /** axe include selectors (screens that are a part of the page); absent = whole page. */
  readonly axeInclude?: readonly string[];
}

const main = (p: Page) => p.getByRole("main").first().waitFor({ timeout: W });
const h1 = (p: Page) => p.getByRole("heading", { level: 1 }).first().waitFor({ timeout: W });
const dialog = (p: Page) =>
  p.locator('[role="dialog"], [role="alertdialog"], dialog[open]').first().waitFor({ timeout: W });
async function waitFor(f: () => boolean, ms = W): Promise<void> {
  const end = Date.now() + ms;
  while (!f()) {
    if (Date.now() > end) throw new Error("condition not met in time");
    await new Promise((r) => setTimeout(r, 100));
  }
}
async function until(f: () => Promise<boolean>, ms = W): Promise<void> {
  const end = Date.now() + ms;
  while (!(await f())) {
    if (Date.now() > end) throw new Error("condition not met in time");
    await new Promise((r) => setTimeout(r, 100));
  }
}
const scopeCss = (css: string) => async (page: Page) => {
  await page.evaluate((c) => {
    (window as unknown as QaWin).__qaScope = [...document.querySelectorAll(c)];
  }, css);
};
const scopeOf = (pick: (page: Page) => Locator, up?: string) => async (page: Page) => {
  await pick(page)
    .first()
    .evaluate((el, sel) => {
      (window as unknown as QaWin).__qaScope = [sel ? (el.closest(sel) ?? el) : el];
    }, up ?? null);
};

const CHECKLIST = {
  complete: false,
  dismissed: false,
  items: ["tailscale", "totp", "sub_account", "api_key", "profile_limits", "demo_session"].map(
    (key) => ({
      key,
      state: "pending",
      reason: null,
      unblock_at: null,
      action_route: "/settings",
    }),
  ),
};
const checklist = (body: unknown) => async (page: Page) => {
  await page.route("**/api/v1/onboarding/checklist", (r) => r.fulfill(json(body)));
};
// Same frame as e2e/system-states/break-glass-notice.spec.ts (stub data, one SCR-153 row).
const NOTICE = {
  kind: "notice",
  severity: "critical",
  message: "Break-glass recovery was used on this server; the Owner must review it.",
  reason: "auth.break_glass_used",
};
const CHALLENGE_ID = "0c9b8a7d-6e5f-4a3b-9c2d-1e0f9a8b7c6d"; // stepup.spec shape; scrubbed as a UUID
const challenge = (expiresInMs: number, target: string | null) => ({
  type: "https://candleviewer.local/errors/step_up_required",
  title: "A dangerous action needs a live step-up elevation for its action class",
  status: 403,
  code: "step_up_required",
  action_class: "users",
  challenge_id: CHALLENGE_ID,
  challenge_expires_at: new Date(Date.now() + expiresInMs).toISOString(),
  action_summary: "Invite user 'annie' as viewer",
  target,
});
const INVITE_CREATED = {
  id: "u1",
  username: "annie",
  invite_url: "/invite/e2e-link",
  invite_expires_at: "2026-12-04T10:00:00Z",
};
/** Wire counters for the SCR-006 flow (3.3.7): creates and step-ups seen (bodies never kept). */
const wire = { creates: 0, stepUps: 0 };
const stepUpStubs = async (page: Page) => {
  wire.creates = 0;
  wire.stepUps = 0;
  await page.route("**/api/v1/users/invites", (r) => r.fulfill(json({ items: [] })));
  await page.route("**/api/v1/users", (r) => {
    wire.creates += 1;
    return wire.creates === 1
      ? r.fulfill(json(challenge(5 * 60_000, null), 403))
      : r.fulfill(json(INVITE_CREATED, 201));
  });
  await page.route("**/api/v1/auth/step-up", (r) => {
    wire.stepUps += 1;
    return r.fulfill(
      json({
        elevated_until: new Date(Date.now() + 10 * 60_000).toISOString(),
        action_class: "users",
      }),
    );
  });
};
const INVITE = "inv-a11y";
const inviteStubs =
  (confirmFails = 0) =>
  async (page: Page) => {
    let fails = confirmFails;
    await page.route(`**/api/v1/invites/${INVITE}`, (r) =>
      r.request().method() === "GET"
        ? r.fulfill(
            json({ display_name: "Ann", role: "viewer", expires_at: "2026-12-01T00:00:00Z" }),
          )
        : r.fulfill(json({ method_id: "m1", otpauth_uri: "otpauth://x", secret_base32: OTP_SEED })),
    );
    await page.route(`**/api/v1/invites/${INVITE}/confirm`, (r) => {
      if (fails > 0) {
        fails -= 1;
        return r.fulfill(json({ title: "x" }, 422));
      }
      return r.fulfill(
        json({ status: "active", role: "viewer", recovery_codes: ["rc-1", "rc-2"] }),
      );
    });
  };
const toPassword = async ({ page }: Ctx) => {
  await page.getByRole("button", { name: "Accept invitation" }).click();
  await page.getByRole("heading", { name: "Choose a password" }).waitFor({ timeout: W });
};
const toTotp = async ({ page }: Ctx) => {
  await page.getByLabel("New password").fill(STUB.newPassword);
  await page.getByRole("button", { name: "Continue" }).click();
  await page.getByRole("heading", { name: "Set up your authenticator" }).waitFor({ timeout: W });
};
const toDone = async ({ page }: Ctx) => {
  await page.getByLabel("Authenticator code").fill(code());
  await page.getByRole("button", { name: "Activate account" }).click();
  await page.getByRole("heading", { name: "You are set up" }).waitFor({ timeout: W });
};
const loginStubs = async (page: Page) => {
  await page.route("**/api/v1/auth/login", (r) =>
    r.fulfill(json({ status: "mfa_required", mfa_token: "t-1", methods: ["totp"] })),
  );
};
const toMfaStep = async ({ page }: Ctx) => {
  await page.getByLabel("Username or email").fill(STUB.user);
  await page.getByLabel("Password", { exact: true }).fill(STUB.password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.getByRole("heading", { name: "Two-factor code" }).waitFor({ timeout: W });
};
const openStepUp = async ({ page }: Ctx) => {
  await h1(page);
  await page.getByLabel("Username").fill("annie"); // stub username
  await page.getByRole("button", { name: "Create invitation" }).click();
  await page.getByRole("alertdialog").first().waitFor({ timeout: W });
};
const lockedSession = async (page: Page) => {
  const s = sessionInfo("owner");
  await page.route(
    (u) => u.pathname === "/api/v1/auth/session",
    (r) =>
      r.request().method() === "GET"
        ? r.fulfill(json({ ...s, session: { ...s.session, locked: true } }))
        : r.fallback(),
  );
};
const journal = (c: Ctx) => h1(c.page);

/** The 27 reachable screens (BQ-02 as corrected by the addendum), each entered with stub data only. */
const SCREENS: readonly Screen[] = [
  { scr: "SCR-001", path: "/login", stubs: loginStubs, open: ({ page }) => main(page) },
  // Built part: LoginScreen's heading-only second step after mfa_required (R-002 renders StubRoute).
  {
    scr: "SCR-002",
    path: "/login",
    stubs: loginStubs,
    open: async (c) => {
      await main(c.page);
      await toMfaStep(c);
    },
  },
  // Built part: step 3 of the SCR-017 wizard (R-006 renders StubRoute).
  {
    scr: "SCR-003",
    path: `/invite/${INVITE}`,
    stubs: inviteStubs(),
    open: async (c) => {
      await c.page.getByRole("heading", { name: "Welcome, Ann" }).waitFor({ timeout: W });
      await toPassword(c);
      await toTotp(c);
    },
  },
  { scr: "SCR-004", path: "/login/change-password", open: ({ page }) => main(page) },
  {
    scr: "SCR-005",
    path: "/locked",
    role: "owner",
    ws: true,
    stubs: lockedSession,
    open: ({ page }) => page.getByRole("alertdialog").first().waitFor({ timeout: W }),
    scope: scopeCss('[role="alertdialog"]'),
    axeInclude: ['[role="alertdialog"]'],
  },
  {
    scr: "SCR-006",
    path: "/admin/users/new",
    role: "owner",
    ws: true,
    stubs: stepUpStubs,
    open: openStepUp,
    scope: scopeCss('[role="alertdialog"]'),
    axeInclude: ['[role="alertdialog"]'],
  },
  { scr: "SCR-010", path: "/journal", role: "owner", ws: true, open: journal },
  {
    scr: "SCR-011",
    path: "/journal",
    role: "owner",
    ws: true,
    open: journal,
    scope: scopeCss('nav[aria-label="Primary"]'),
    axeInclude: ['nav[aria-label="Primary"]'],
  },
  {
    scr: "SCR-013",
    path: "/journal",
    role: "owner",
    ws: true,
    open: async ({ page }) => {
      await h1(page);
      await page.keyboard.press("Control+/");
      await dialog(page);
    },
    scope: scopeCss('[role="dialog"]'),
    axeInclude: ['[role="dialog"]'],
  },
  {
    scr: "SCR-014",
    path: "/journal",
    role: "owner",
    ws: true,
    open: journal,
    scope: scopeCss("aside"),
    axeInclude: ["aside"],
    steps: [
      {
        label: "drawer open",
        go: async ({ page }) => {
          await page.getByRole("button", { name: "Notifications" }).click();
          await page.getByRole("group", { name: "Notifications" }).waitFor({ timeout: W });
        },
      },
    ],
  },
  {
    scr: "SCR-015",
    path: "/journal",
    role: "owner",
    ws: true,
    open: async ({ page }) => {
      await h1(page);
      await page.getByTestId("toast-host").waitFor({ state: "attached", timeout: W });
      await page.keyboard.press("Control+Shift+X"); // inert destructive binding -> one toast (hotkeys.spec.ts)
      await page.getByTestId("toast-host").locator("p").first().waitFor({ timeout: W });
    },
    scope: scopeCss('[data-testid="toast-host"]'),
    axeInclude: ['[data-testid="toast-host"]'],
  },
  {
    scr: "SCR-017",
    path: `/invite/${INVITE}`,
    stubs: inviteStubs(),
    open: ({ page }) => page.getByRole("heading", { name: "Welcome, Ann" }).waitFor({ timeout: W }),
    steps: [
      { label: "step 2 password", go: toPassword },
      { label: "step 3 authenticator", go: toTotp },
      { label: "step 4 done (codes)", go: toDone },
    ],
  },
  {
    scr: "SCR-018",
    path: "/terminal/last",
    role: "owner",
    ws: true,
    stubs: checklist(CHECKLIST),
    open: async ({ page }) => {
      if ((await page.locator('[role="dialog"]').count()) === 0)
        await page.getByRole("button", { name: "Take the tour" }).click({ timeout: W });
      await dialog(page);
    },
    scope: scopeCss('[role="dialog"]'),
    axeInclude: ['[role="dialog"]'],
  },
  {
    scr: "SCR-019",
    path: "/terminal/last",
    role: "owner",
    ws: true,
    stubs: checklist(CHECKLIST),
    open: ({ page }) =>
      page.getByRole("region", { name: "Setup checklist" }).waitFor({ timeout: W }),
    scope: scopeOf((p) => p.getByRole("region", { name: "Setup checklist" })),
  },
  {
    scr: "SCR-075",
    path: "/journal",
    role: "owner",
    ws: true,
    open: async ({ page }) => {
      await h1(page);
      await page
        .getByRole("img", { name: "Trading environment: Demo" })
        .first()
        .waitFor({ timeout: W });
    },
    scope: scopeOf((p) => p.getByRole("img", { name: "Trading environment: Demo" }), "[data-cmp]"),
    axeInclude: ["header"],
  },
  {
    scr: "SCR-112",
    path: "/settings/profile",
    role: "owner",
    ws: true,
    stubs: (page) => stubSessionsList(page),
    open: async ({ page }) => {
      await page
        .getByRole("heading", { level: 1, name: "Security settings", exact: true })
        .waitFor({ timeout: W });
      await page.getByRole("table").waitFor({ timeout: W });
    },
    scope: scopeCss("main"),
  },
  {
    scr: "SCR-113",
    path: "/settings/hotkeys",
    role: "owner",
    ws: true,
    // HotkeyEditor renders an h2 "Hotkeys" and no h1 (keymap/HotkeyEditor.tsx)
    open: ({ page }) =>
      page.getByRole("heading", { name: "Hotkeys", exact: true }).first().waitFor({ timeout: W }),
    scope: scopeCss('section[aria-labelledby="hk-h"]'),
  },
  {
    scr: "SCR-116",
    path: "/settings/appearance",
    role: "owner",
    ws: true,
    open: ({ page }) =>
      page
        .getByRole("heading", { level: 1, name: "Appearance", exact: true })
        .waitFor({ timeout: W }),
    scope: scopeOf(
      (p) => p.getByRole("heading", { level: 1, name: "Appearance", exact: true }),
      "div",
    ),
  },
  {
    scr: "SCR-117",
    path: "/settings/appearance",
    role: "owner",
    ws: true,
    open: ({ page }) =>
      page
        .getByRole("heading", { level: 1, name: "Appearance", exact: true })
        .waitFor({ timeout: W }),
    scope: scopeCss('section[aria-labelledby="a11y-h"]'),
    axeInclude: ['section[aria-labelledby="a11y-h"]'],
  },
  {
    scr: "SCR-123",
    path: "/admin/users/new",
    role: "owner",
    ws: true,
    stubs: async (page) => {
      await page.route("**/api/v1/users/invites", (r) => r.fulfill(json({ items: [] })));
    },
    open: journal,
    scope: scopeCss("main"),
  },
  {
    scr: "SCR-152",
    path: "/journal",
    role: "owner",
    ws: true,
    open: async (c) => {
      await h1(c.page);
      const ws = c.ws;
      if (ws) await waitFor(() => ws.authenticated() >= 1);
      ws?.kill(); // a lost transport: the region leaves its 0 px live state
      await c.page.getByRole("region", { name: "Connection" }).waitFor({ timeout: W });
    },
    scope: scopeOf((p) => p.getByRole("region", { name: "Connection" })),
    axeInclude: ['section[aria-label="Connection"]'],
  },
  {
    scr: "SCR-153",
    path: "/journal",
    role: "manager",
    ws: { firstAuthSystem: [NOTICE] },
    open: async ({ page }) => {
      await h1(page);
      await page.getByRole("button", { name: `Dismiss ${NOTICE.message}` }).waitFor({ timeout: W });
    },
    scope: scopeOf(
      (p) => p.getByRole("button", { name: `Dismiss ${NOTICE.message}` }),
      '[role="alert"],[role="status"],[role="region"],section,[data-cmp]',
    ),
  },
  {
    scr: "SCR-154",
    path: "/403",
    role: "owner",
    ws: true,
    open: (c) => main(c.page),
    scope: scopeCss("main"),
  },
  { scr: "SCR-155", path: "/404", open: ({ page }) => main(page) },
  {
    // Fault injected with stub data only: a checklist body whose `items` is null makes SetupChecklistCard
    // throw inside its PanelErrorBoundary (R-101). Panel scope; the route-level fallback is in deep mode.
    scr: "SCR-156",
    path: "/terminal/last",
    role: "owner",
    ws: true,
    stubs: checklist({ complete: false, dismissed: false, items: null }),
    open: ({ page }) => page.getByRole("button", { name: /Reload panel/ }).waitFor({ timeout: W }),
    scope: scopeOf((p) => p.getByRole("button", { name: /Reload panel/ }), '[data-cmp="CMP-091"]'),
    axeInclude: ['[data-cmp="CMP-091"]'],
  },
  {
    scr: "SCR-157",
    path: "/journal",
    role: "owner",
    ws: true,
    newerServer: true,
    open: async ({ page }) => {
      await h1(page);
      await page.locator("[data-version-banner]").waitFor({ timeout: W });
    },
    scope: scopeCss("[data-version-banner]"),
    axeInclude: ["[data-version-banner]"],
  },
  { scr: "SCR-159", path: "/offline", open: ({ page }) => main(page) },
];

// ------------------------------------------------------------------------------- page / context

interface Opened {
  readonly context: BrowserContext;
  readonly page: Page;
  readonly ws: WsHarness | undefined;
  readonly offHost: Record<string, number>;
}
interface OpenOpts {
  readonly role?: Role | undefined;
  readonly ws?: GatewayOptions | true | undefined;
  readonly newerServer?: true | undefined;
  readonly theme?: Theme;
  readonly vp?: { readonly width: number; readonly height: number };
  readonly reduced?: boolean;
  readonly listeners?: boolean; // record pointer / drag listener registrations (2.5.7)
  readonly live?: boolean; // log live-region writes (SR proxy)
}
async function openContext(browser: Browser, o: OpenOpts = {}): Promise<Opened> {
  const theme = o.theme ?? DARK;
  const context = await browser.newContext({
    serviceWorkers: "block",
    viewport: o.vp ?? { width: 1280, height: 800 },
    reducedMotion: o.reduced ? "reduce" : "no-preference",
  });
  await context.grantPermissions(["clipboard-read", "clipboard-write"], { origin: ORIGIN });
  const offHost: Record<string, number> = {};
  await context.route("**/*", (r) => {
    const host = new URL(r.request().url()).hostname;
    if (LOOPBACK.has(host)) return r.fallback();
    offHost[host] = (offHost[host] ?? 0) + 1;
    return r.abort();
  });
  await context.addInitScript((v) => {
    try {
      localStorage.setItem("cv.theme.v1", v);
    } catch {
      /* storage unavailable */
    }
  }, JSON.stringify(theme.local));
  if (o.listeners) await context.addInitScript(recordListeners);
  if (o.live) await context.addInitScript(liveLogger);
  const page = await context.newPage();
  if (o.newerServer) {
    // Wrap routeWebSocket so the harness's welcome names another build (SCR-157).
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
            if (f.t === "welcome") f.p["server_version"] = "99.0.0";
            return send(JSON.stringify(f));
          }
          return send(m);
        };
        return handler(ws);
      });
  }
  let ws: WsHarness | undefined;
  if (o.role) {
    await stubSession(page, { role: o.role });
    await page.route("**/api/v1/me/preferences", (r) =>
      r.fulfill(json({ appearance: theme.appearance })),
    );
    if (o.ws) ws = await installWsHarness(page, undefined, o.ws === true ? {} : o.ws);
  }
  return { context, page, ws, offHost };
}
const screenOpts = (s: Screen): OpenOpts => ({
  role: s.role,
  ws: s.ws,
  newerServer: s.newerServer,
});
const selected = (scr: string): boolean => !ONLY || ONLY.has(scr);

// ------------------------------------------------------------------------- in-page instruments

interface QaWin {
  __qa?: QaProbe;
  __qaT?: Element[];
  __qaF?: HTMLElement[];
  __qaScope?: Element[] | undefined;
  __qaVisited?: Map<Element, number>;
  __qaListeners?: { type: string; target: EventTarget; site: string | null }[];
  __qaLive?: LiveEntry[];
}
interface QaProbe {
  focusStep(): FocusStep;
  overlays(): unknown[];
  targets(): Target[];
  drags(): unknown;
  help(): unknown[];
  fields(): Field[];
  syntheticPasteBlocked(f: number): boolean;
  fieldValueLength(f: number): number;
  cognitiveSigns(): unknown;
}
interface FocusStep {
  body?: true;
  seen?: true;
  repeatOfFirst?: boolean;
  stop?: string;
  state?: string;
  [k: string]: unknown;
}
interface Target {
  i: number;
  desc: string;
  path: string;
  tag: string;
  type: string | null;
  in_scope: boolean;
  disabled: boolean;
  own: [number, number];
  size: [number, number];
  center: [number, number];
  rect: [number, number, number, number];
  display: string;
  inline_text_ratio: [number, number] | null;
  has_value_text: boolean;
  label_folded: boolean;
  contiguous: boolean;
}
interface Field {
  f: number;
  label: string;
  type: string;
  maxlength: number | null;
  [k: string]: unknown;
}
interface LiveEntry {
  ms: number;
  role: string;
  live: string;
  text: string;
  busy: boolean;
  inserted?: true;
}
type ProbeCall =
  "focusStep" | "overlays" | "targets" | "drags" | "help" | "fields" | "cognitiveSigns";
/** Calls a no-argument probe method in the page. */
async function probe<T>(page: Page, m: ProbeCall): Promise<T> {
  return (await page.evaluate((name) => {
    const qa = (window as unknown as QaWin).__qa;
    if (!qa) throw new Error("probe not installed");
    return (qa[name as ProbeCall] as () => unknown)();
  }, m)) as T;
}

/**
 * wcag22 probe, installed with page.evaluate after a screen opens. Reads geometry, roles, accessible
 * names and attributes only; never returns an input value. Names pass through `clean`, which also
 * masks secret-shaped runs.
 */
function installProbe(): void {
  const w = window as unknown as QaWin;
  if (w.__qa) return;
  const SECRET = /\b\d{6,}\b|\b[A-Z2-7]{16,}\b|\brc-\d+\b/g;
  const clean = (s: string): string =>
    s.replace(/\s+/g, " ").trim().replace(SECRET, "<redacted>").slice(0, 90);
  const textOf = (id: string): string => document.getElementById(id)?.textContent ?? "";
  const FORM_TAGS = new Set(["input", "textarea", "select"]);
  const name = (el: Element): string => {
    const a = el.getAttribute("aria-label");
    if (a) return clean(a);
    const lb = el.getAttribute("aria-labelledby");
    if (lb) return clean(lb.split(/\s+/).map(textOf).join(" "));
    const labels = (el as HTMLInputElement).labels;
    if (labels && labels.length)
      return clean([...labels].map((l) => l.textContent ?? "").join(" "));
    if (FORM_TAGS.has(el.tagName.toLowerCase())) return clean(el.getAttribute("title") ?? ""); // never a value
    return (
      clean((el as HTMLElement).innerText ?? el.textContent ?? "") ||
      clean(el.getAttribute("title") ?? "")
    );
  };
  const role = (el: Element): string => {
    const r = el.getAttribute("role");
    if (r) return r;
    const t = el.tagName.toLowerCase();
    if (t === "a") return el.hasAttribute("href") ? "link" : "a";
    if (t === "input") return `input:${(el as HTMLInputElement).type}`;
    return t;
  };
  const path = (el: Element): string => {
    const parts: string[] = [];
    let cur: Element | null = el;
    for (let i = 0; cur && i < 6; i++) {
      const t = cur.tagName.toLowerCase();
      if (cur.id && !/^:|^radix-|\d{3,}/.test(cur.id)) {
        parts.unshift(`${t}#${CSS.escape(cur.id)}`);
        break;
      }
      const cmp = cur.getAttribute("data-cmp");
      const tid = cur.getAttribute("data-testid");
      const al = cur.getAttribute("aria-label");
      let seg = t;
      if (tid) seg += `[data-testid="${tid}"]`;
      else if (cmp) seg += `[data-cmp="${cmp}"]`;
      else if (al && al.length < 40 && !/\d{6,}|[A-Z2-7]{16,}/.test(al))
        seg += `[aria-label="${al}"]`;
      else if (cur.parentElement) {
        const tag = cur.tagName;
        const sib = [...cur.parentElement.children].filter((c) => c.tagName === tag);
        if (sib.length > 1) seg += `:nth-of-type(${sib.indexOf(cur) + 1})`;
      }
      parts.unshift(seg);
      cur = cur.parentElement;
      if (cur === document.body) break;
    }
    return parts.join(" > ");
  };
  const desc = (el: Element): string => `${role(el)} "${name(el)}"`;
  const reactProps = (el: Element): Record<string, unknown> | null => {
    const k = Object.keys(el).find((x) => x.startsWith("__reactProps$"));
    return k ? ((el as unknown as Record<string, Record<string, unknown>>)[k] ?? null) : null;
  };
  const shown = (el: Element): boolean => {
    const r = el.getBoundingClientRect();
    if (r.width <= 0 || r.height <= 0) return false;
    const cs = getComputedStyle(el);
    return cs.visibility !== "hidden" && cs.display !== "none";
  };
  const scopeEls = (): Element[] => w.__qaScope ?? [];
  const inScope = (el: Element): boolean => {
    const s = scopeEls();
    return s.length === 0 || s.some((x) => x === el || x.contains(el));
  };
  const positioned = (el: Element): string => getComputedStyle(el).position;
  const overlayRoot = (top: Element, focused: Element): Element => {
    // Highest ancestor of `top` that does not contain the focused element: the covering subtree.
    let cur = top;
    while (cur.parentElement && !cur.parentElement.contains(focused)) cur = cur.parentElement;
    // Prefer the nearest positioned (fixed/sticky/absolute) ancestor on the way, for the report.
    let p: Element | null = top;
    while (p && p !== cur.parentElement) {
      const pos = positioned(p);
      if (pos === "fixed" || pos === "sticky" || pos === "absolute") return p;
      p = p.parentElement;
    }
    return cur;
  };
  const ownVisual = (top: Element, el: Element): boolean => {
    const lab = top.closest("label");
    if (lab && ((lab as HTMLLabelElement).control === el || lab.contains(el))) return true;
    const elLab = el.closest("label");
    return !!elLab && elLab.contains(top);
  };

  w.__qa = {
    focusStep(): FocusStep {
      const el = document.activeElement;
      if (!el || el === document.body || el === document.documentElement) return { body: true };
      const visited = (w.__qaVisited ??= new Map());
      if (visited.has(el)) return { seen: true, repeatOfFirst: visited.get(el) === 0 };
      visited.set(el, visited.size);
      const r = el.getBoundingClientRect();
      const base = {
        stop: desc(el),
        path: path(el),
        in_scope: inScope(el),
        box: [Math.round(r.left), Math.round(r.top), Math.round(r.width), Math.round(r.height)],
      };
      if (r.width < 1 || r.height < 1) return { ...base, state: "zero-size" };
      const x0 = Math.max(r.left, 0);
      const y0 = Math.max(r.top, 0);
      const x1 = Math.min(r.right, innerWidth);
      const y1 = Math.min(r.bottom, innerHeight);
      if (x1 - x0 < 1 || y1 - y0 < 1) return { ...base, state: "offscreen" };
      let total = 0;
      let covered = 0;
      const coverers = new Map<string, string>();
      const N = 5;
      for (let i = 0; i < N; i++)
        for (let j = 0; j < N; j++) {
          const x = x0 + ((i + 0.5) / N) * (x1 - x0);
          const y = y0 + ((j + 0.5) / N) * (y1 - y0);
          const stack = document.elementsFromPoint(x, y);
          const top = stack[0];
          total++;
          if (!top || top === el || el.contains(top) || top.contains(el) || ownVisual(top, el))
            continue;
          if (!stack.includes(el)) continue; // indeterminate (focused box takes no hits): not counted
          covered++;
          const o = overlayRoot(top, el);
          coverers.set(path(o), `${desc(o).slice(0, 60)} position:${positioned(o)}`);
        }
      const clipped =
        x0 > r.left + 0.5 || y0 > r.top + 0.5 || x1 < r.right - 0.5 || y1 < r.bottom - 0.5;
      const state =
        covered === 0
          ? clipped
            ? "visible-clipped-by-viewport"
            : "visible"
          : covered === total
            ? "hidden"
            : "partial";
      return {
        ...base,
        state,
        covered_points: `${covered}/${total}`,
        coverers: Object.fromEntries(coverers),
      };
    },

    overlays(): unknown[] {
      return [...document.querySelectorAll("body *")]
        .filter((e) => {
          const p = positioned(e);
          return (p === "fixed" || p === "sticky") && shown(e);
        })
        .map((e) => {
          const r = e.getBoundingClientRect();
          return {
            el: path(e),
            position: positioned(e),
            box: [Math.round(r.left), Math.round(r.top), Math.round(r.width), Math.round(r.height)],
          };
        });
    },

    targets(): Target[] {
      const SEL =
        'a[href],button,input:not([type="hidden"]),select,textarea,summary,[role="button"],[role="link"],[role="checkbox"],[role="radio"],[role="switch"],[role="tab"],[role="menuitem"],[role="menuitemcheckbox"],[role="menuitemradio"],[role="option"],[role="slider"],[role="spinbutton"],[role="combobox"],[role="treeitem"],[tabindex]:not([tabindex="-1"]),label';
      const set = new Set<Element>(document.querySelectorAll(SEL));
      for (const e of document.querySelectorAll("body *")) {
        const p = reactProps(e);
        if (p && (p["onClick"] || p["onPointerDown"] || p["onMouseDown"])) set.add(e);
      }
      const NATIVE = "a[href],button,label,summary,[role=button],[role=link]";
      const list: Element[] = [];
      for (const e of set) {
        if (e === document.body || e.id === "root") continue;
        // A clickable nested in a native control is the same target; a label is folded into its control.
        if (e.parentElement?.closest(NATIVE) && !FORM_TAGS.has(e.tagName.toLowerCase())) continue;
        if (e.tagName === "LABEL" && (e as HTMLLabelElement).control) continue;
        if (e.tagName === "LABEL" && !reactProps(e)?.["onClick"]) continue;
        list.push(e);
      }
      const out: Target[] = [];
      const kept: Element[] = [];
      w.__qaT = kept;
      for (const e of list) {
        const own = e.getBoundingClientRect();
        const labels = FORM_TAGS.has(e.tagName.toLowerCase())
          ? [...((e as HTMLInputElement).labels ?? [])]
          : [];
        const boxes = [own, ...labels.map((l) => l.getBoundingClientRect())].filter(
          (b) => b.width > 0 && b.height > 0,
        );
        if (!shown(e) && !labels.some(shown)) continue;
        if (boxes.length === 0) continue;
        const cs = getComputedStyle(e);
        if (cs.visibility === "hidden" && !labels.some(shown)) continue;
        // Hit area: the control's own box and its labels' boxes (a label click activates the control).
        const L = Math.min(...boxes.map((b) => b.left)) + scrollX;
        const T = Math.min(...boxes.map((b) => b.top)) + scrollY;
        const R = Math.max(...boxes.map((b) => b.right)) + scrollX;
        const B = Math.max(...boxes.map((b) => b.bottom)) + scrollY;
        // A label not contiguous with its control is not one rectangle: use the largest single box.
        const contiguous = boxes.length === 1 || labels.some((l) => l.contains(e));
        const big = boxes.reduce((a, b) => (b.width * b.height > a.width * a.height ? b : a));
        const bw = contiguous ? R - L : big.width;
        const bh = contiguous ? B - T : big.height;
        const display = cs.display;
        let blockText = 0;
        const ownText = (e.textContent ?? "").trim().length;
        if (display === "inline") {
          let p = e.parentElement;
          while (p && getComputedStyle(p).display.startsWith("inline")) p = p.parentElement;
          blockText = (p?.textContent ?? "").trim().length;
        }
        kept.push(e);
        out.push({
          i: kept.length - 1,
          desc: desc(e),
          path: path(e),
          tag: e.tagName.toLowerCase(),
          type: (e as HTMLInputElement).type ?? null,
          in_scope: inScope(e),
          disabled:
            (e as HTMLButtonElement).disabled === true ||
            e.getAttribute("aria-disabled") === "true",
          own: [Math.round(own.width * 10) / 10, Math.round(own.height * 10) / 10],
          size: [Math.round(bw * 10) / 10, Math.round(bh * 10) / 10],
          label_folded: labels.length > 0,
          contiguous,
          center: [
            contiguous ? (L + R) / 2 : big.left + scrollX + big.width / 2,
            contiguous ? (T + B) / 2 : big.top + scrollY + big.height / 2,
          ],
          rect: contiguous
            ? [L, T, R, B]
            : [big.left + scrollX, big.top + scrollY, big.right + scrollX, big.bottom + scrollY],
          display,
          inline_text_ratio: display === "inline" ? [ownText, blockText] : null,
          has_value_text:
            FORM_TAGS.has(e.tagName.toLowerCase()) &&
            !["checkbox", "radio", "button", "submit"].includes((e as HTMLInputElement).type),
        });
      }
      return out;
    },

    drags(): unknown {
      const found: unknown[] = [];
      for (const e of document.querySelectorAll("body *")) {
        const p = reactProps(e);
        const keys = p
          ? Object.keys(p).filter((k) =>
              /^on(PointerMove|MouseMove|TouchMove|DragStart|Drag|DragOver|Drop)$/.test(k),
            )
          : [];
        const attr = e.getAttribute("draggable") === "true";
        const r = role(e);
        const roleHit =
          ["slider", "separator", "scrollbar", "input:range"].includes(r) &&
          (r !== "separator" || e.hasAttribute("tabindex"));
        if (keys.length || attr || roleHit)
          found.push({
            el: path(e),
            desc: desc(e),
            react_handlers: keys,
            draggable: attr,
            role: r,
            in_scope: inScope(e),
          });
      }
      const listeners = (w.__qaListeners ?? []).map((l) => ({
        type: l.type,
        site: l.site,
        target:
          l.target === window
            ? "window"
            : l.target === document
              ? "document"
              : l.target instanceof Element
                ? path(l.target)
                : "other",
      }));
      return { elements: found, native_listeners: listeners };
    },

    help(): unknown[] {
      const RX =
        /\b(help|support|contact|docs?|documentation|faq|keyboard shortcuts|shortcuts|cheatsheet|guide|tour|about)\b/i;
      const focusables = [
        ...document.querySelectorAll(
          'a[href],button,[role="button"],[role="link"],[role="menuitem"]',
        ),
      ].filter(shown);
      return focusables
        .map((e, idx) => ({ e, idx }))
        .filter(({ e }) => RX.test(name(e)))
        .map(({ e, idx }) => {
          const r = e.getBoundingClientRect();
          const land = e.closest(
            'header,nav,main,aside,footer,[role="dialog"],[role="alertdialog"],[role="region"],section',
          );
          const landLabel = land?.getAttribute("aria-label");
          return {
            name: name(e),
            role: role(e),
            order_index: idx,
            landmark: land
              ? `${land.tagName.toLowerCase()}${landLabel ? `[${landLabel}]` : ""}`
              : "none",
            box: [Math.round(r.left), Math.round(r.top)],
            in_scope: inScope(e),
          };
        });
    },

    fields(): Field[] {
      const out: Field[] = [];
      const kept: HTMLElement[] = [];
      w.__qaF = kept;
      for (const e of document.querySelectorAll<HTMLInputElement>(
        "input:not([type=hidden]),textarea,select",
      )) {
        if (!inScope(e) || !shown(e)) continue;
        const p = reactProps(e);
        kept.push(e);
        out.push({
          f: kept.length - 1,
          label: name(e),
          type: e.type,
          autocomplete: e.getAttribute("autocomplete"),
          name_attr: e.hasAttribute("name"),
          id_attr: e.hasAttribute("id"),
          in_form: !!e.form,
          readonly: e.readOnly,
          maxlength: e.maxLength > 0 ? e.maxLength : null,
          inputmode: e.getAttribute("inputmode"),
          paste_handler:
            !!(p && (p["onPaste"] || p["onPasteCapture"])) || e.hasAttribute("onpaste"),
          copy_cut_handler: !!(p && (p["onCopy"] || p["onCut"])),
          user_select: getComputedStyle(e).userSelect,
        });
      }
      return out;
    },

    syntheticPasteBlocked(f: number): boolean {
      const el = w.__qaF?.[f];
      if (!el) return false;
      const dt = new DataTransfer();
      dt.setData("text/plain", "x");
      const ev = new ClipboardEvent("paste", {
        clipboardData: dt,
        bubbles: true,
        cancelable: true,
      });
      el.dispatchEvent(ev);
      return ev.defaultPrevented;
    },

    fieldValueLength(f: number): number {
      return ((w.__qaF?.[f] as HTMLInputElement | undefined)?.value ?? "").length;
    },

    cognitiveSigns(): unknown {
      const scope = scopeEls()[0] ?? document.body;
      const txt = (scope.textContent ?? "").toLowerCase();
      return {
        captcha_like:
          /captcha|not a robot|puzzle|type the characters|select all images/.test(txt) ||
          !!scope.querySelector('iframe,[class*="captcha" i]'),
        qr_or_image: !!scope.querySelector('img,canvas,svg[role="img"]'),
        copy_control: [...scope.querySelectorAll("button,a")].some((b) => /copy/i.test(name(b))),
        code_user_select: [...scope.querySelectorAll("code")].map(
          (c) => getComputedStyle(c).userSelect,
        ),
      };
    },
  };
}

/** Init script: records native pointer / drag listener registrations (React's root delegation included). */
function recordListeners(): void {
  const w = window as unknown as QaWin;
  const log: { type: string; target: EventTarget; site: string | null }[] = [];
  w.__qaListeners = log;
  const TYPES = new Set(["pointermove", "mousemove", "touchmove", "dragstart", "drag", "drop"]);
  const orig = EventTarget.prototype.addEventListener;
  EventTarget.prototype.addEventListener = function (
    this: EventTarget,
    type: string,
    listener: EventListenerOrEventListenerObject | null,
    options?: boolean | AddEventListenerOptions,
  ): void {
    if (TYPES.has(type))
      log.push({
        type,
        target: this,
        // Registration site (bundle file:line only, host masked) for window/document listeners.
        site:
          this === window || this === document
            ? (new Error().stack ?? "")
                .split("\n")
                .slice(2, 4)
                .map((l) => l.trim().replace(/https?:\/\/[^/]+/g, "<loopback>"))
                .join(" | ")
            : null,
      });
    orig.call(this, type, listener, options);
  };
}

/** Init script: logs every write to a live region (role / politeness / time; text kept in-page). */
function liveLogger(): void {
  const w = window as unknown as QaWin;
  if (w.__qaLive) return;
  const log: LiveEntry[] = [];
  w.__qaLive = log;
  const t0 = performance.now();
  const LIVE = "[aria-live],[role=status],[role=alert],[role=log]";
  const regionOf = (n: Node | null): Element | null => {
    let el: Element | null = n instanceof Element ? n : (n?.parentElement ?? null);
    while (el) {
      const live = el.getAttribute("aria-live");
      const role = el.getAttribute("role");
      if (live !== null || role === "status" || role === "alert" || role === "log") return el;
      el = el.parentElement;
    }
    return null;
  };
  const implicit = (role: string | null): string =>
    role === "alert"
      ? "assertive(implicit)"
      : role === "status" || role === "log"
        ? "polite(implicit)"
        : "?";
  const start = (): void => {
    new MutationObserver((muts) => {
      const seen = new Set<Element>();
      for (const m of muts) {
        for (const n of Array.from(m.addedNodes)) {
          if (!(n instanceof Element)) continue;
          const inner = [n, ...Array.from(n.querySelectorAll(LIVE))].filter((x) => x.matches(LIVE));
          for (const r of inner) {
            if (seen.has(r) || regionOf(m.target)) continue;
            seen.add(r);
            const role = r.getAttribute("role");
            log.push({
              ms: Math.round(performance.now() - t0),
              role: role ?? r.tagName.toLowerCase(),
              live: r.getAttribute("aria-live") ?? implicit(role ?? "status"),
              text: (r.textContent ?? "").replace(/\s+/g, " ").trim().slice(0, 160),
              busy: false,
              inserted: true,
            });
          }
        }
        const r = regionOf(m.target);
        if (!r || seen.has(r)) continue;
        seen.add(r);
        const role = r.getAttribute("role");
        log.push({
          ms: Math.round(performance.now() - t0),
          role: role ?? r.tagName.toLowerCase(),
          live: r.getAttribute("aria-live") ?? implicit(role),
          text: (r.textContent ?? "").replace(/\s+/g, " ").trim().slice(0, 160),
          busy: r.closest("[aria-busy=true]") !== null,
        });
      }
    }).observe(document.documentElement, { subtree: true, childList: true, characterData: true });
  };
  if (document.documentElement) start();
  else document.addEventListener("DOMContentLoaded", start);
}

/** Live-region writes since the last drain; on NO_TEXT surfaces only fixed app copy is kept. */
async function drainLive(page: Page, scr: string, state: string): Promise<LiveEntry[]> {
  const raw = await page.evaluate(() => {
    const w = window as unknown as QaWin;
    const out = w.__qaLive ? w.__qaLive.splice(0) : [];
    return out;
  });
  const hide = noText(scr, state);
  return raw.map((e) => ({
    ...e,
    text: hide ? (e.text === "" || COPY.has(e.text) ? e.text : "<redacted>") : scrubText(e.text),
  }));
}

/** The focused element: role, accessible name (never a value), states. */
async function focusInfo(page: Page): Promise<Record<string, unknown>> {
  return page.evaluate(() => {
    const el = document.activeElement as HTMLElement | null;
    if (!el || el === document.body) return { body: true };
    const t = el.tagName.toLowerCase();
    const role =
      el.getAttribute("role") ??
      (t === "input" ? `input:${(el as HTMLInputElement).type}` : t === "a" ? "link" : t);
    let name = el.getAttribute("aria-label") ?? "";
    const lb = el.getAttribute("aria-labelledby");
    if (!name && lb)
      name = lb
        .split(/\s+/)
        .map((i) => document.getElementById(i)?.textContent ?? "")
        .join(" ");
    const labels = (el as HTMLInputElement).labels;
    if (!name && labels && labels.length) name = [...labels].map((l) => l.textContent).join(" ");
    if (!name && !["input", "textarea", "select"].includes(t)) name = el.innerText ?? "";
    const r = el.getBoundingClientRect();
    const cs = getComputedStyle(el);
    return {
      role,
      name: name.replace(/\s+/g, " ").trim().slice(0, 80),
      inDialog: el.closest("[role=dialog],[role=alertdialog],dialog") !== null,
      disabled: (el as HTMLButtonElement).disabled === true,
      invalid: el.getAttribute("aria-invalid"),
      describedby: el.getAttribute("aria-describedby") ? "set" : null,
      pressed: el.getAttribute("aria-pressed"),
      expanded: el.getAttribute("aria-expanded"),
      checked:
        el.getAttribute("aria-checked") ??
        ((el as HTMLInputElement).checked === true ? "true" : null),
      required:
        (el as HTMLInputElement).required === true || el.getAttribute("aria-required") === "true",
      autocomplete: el.getAttribute("autocomplete"),
      inputmode: el.getAttribute("inputmode"),
      visibleBox: r.width > 0 && r.height > 0,
      outline: `${cs.outlineStyle} ${cs.outlineWidth}`,
      boxShadow: cs.boxShadow === "none" ? "none" : "set",
    };
  });
}

async function tabWalk(page: Page, n: number, back = false): Promise<Record<string, unknown>[]> {
  const out: Record<string, unknown>[] = [];
  for (let i = 0; i < n; i++) {
    await page.keyboard.press(back ? "Shift+Tab" : "Tab");
    out.push(await focusInfo(page));
  }
  return out;
}
/** Tab until the focused control's name matches (max n); returns the stops passed. */
async function tabTo(page: Page, name: RegExp, n = 40): Promise<number> {
  for (let i = 0; i < n; i++) {
    await page.keyboard.press("Tab");
    const f = await focusInfo(page);
    if (typeof f["name"] === "string" && name.test(f["name"])) return i + 1;
  }
  throw new Error(`tabTo ${name.source} not reached`);
}

/** 1.4.10: horizontal overflow and clipped content at the current viewport. */
async function reflowCheck(page: Page): Promise<Record<string, unknown>> {
  return page.evaluate(() => {
    const vw = document.documentElement.clientWidth;
    const over: string[] = [];
    const clipped: string[] = [];
    const label = (el: Element): string =>
      `${el.tagName.toLowerCase()}${el.getAttribute("role") ? `[role=${el.getAttribute("role")}]` : ""}${el.getAttribute("data-cmp") ? `[${el.getAttribute("data-cmp")}]` : ""}`;
    for (const el of Array.from(document.querySelectorAll<HTMLElement>("body *"))) {
      const r = el.getBoundingClientRect();
      if (r.width === 0 || r.height === 0) continue;
      const cs = getComputedStyle(el);
      if (cs.visibility === "hidden") continue;
      if (cs.clipPath && cs.clipPath !== "none") continue; // visually-hidden helpers
      if ((r.right > vw + 1 || r.left < -1) && el.children.length === 0) {
        let a: HTMLElement | null = el.parentElement;
        let via = "none (no scrollable ancestor: content cut off)";
        while (a && a !== document.documentElement) {
          const ac = getComputedStyle(a);
          if (/(auto|scroll)/.test(ac.overflowX) && a.scrollWidth > a.clientWidth + 1) {
            via = `scrolls inside ${label(a)} (2-D)`;
            break;
          }
          a = a.parentElement;
        }
        over.push(
          `${label(el)} left=${Math.round(r.left)} right=${Math.round(r.right)} reach=${via}`,
        );
      }
      if (
        (cs.overflowX === "hidden" || cs.overflow === "hidden" || cs.textOverflow === "ellipsis") &&
        el.scrollWidth > el.clientWidth + 1
      )
        clipped.push(`${label(el)} ${el.scrollWidth}>${el.clientWidth}`);
    }
    const boxes = Array.from(
      document.querySelectorAll(
        '[role=alertdialog],[role=dialog],[data-cmp="CMP-091"],section[aria-label="Connection"]',
      ),
    ).map((e) => {
      const b = e.getBoundingClientRect();
      return `${e.getAttribute("role") ?? e.getAttribute("data-cmp") ?? e.getAttribute("aria-label")} x=${Math.round(b.left)}..${Math.round(b.right)} y=${Math.round(b.top)}..${Math.round(b.bottom)}`;
    });
    return {
      boxes,
      viewport_w: vw,
      doc_scroll_w: document.documentElement.scrollWidth,
      horizontal_scroll: document.documentElement.scrollWidth > vw + 1,
      leaf_overflow: over.slice(0, 12),
      leaf_overflow_n: over.length,
      clipped: clipped.slice(0, 12),
    };
  });
}

/** 1.4.12: apply the four spacing overrides and look for clipped or overflowing text. */
async function textSpacingCheck(page: Page): Promise<Record<string, unknown>> {
  await page.addStyleTag({
    content:
      "*{line-height:1.5 !important;letter-spacing:.12em !important;word-spacing:.16em !important}p{margin-bottom:2em !important}",
  });
  await page.waitForTimeout(100);
  return page.evaluate(() => {
    const clipped: string[] = [];
    for (const el of Array.from(document.querySelectorAll<HTMLElement>("body *"))) {
      const r = el.getBoundingClientRect();
      if (r.width === 0 || r.height === 0) continue;
      const cs = getComputedStyle(el);
      if (cs.clipPath && cs.clipPath !== "none") continue;
      const hides =
        ["hidden", "clip"].includes(cs.overflowX) || ["hidden", "clip"].includes(cs.overflowY);
      if (!hides) continue;
      if (el.scrollWidth > el.clientWidth + 1 || el.scrollHeight > el.clientHeight + 1)
        clipped.push(
          `${el.tagName.toLowerCase()}${el.getAttribute("data-cmp") ? `[${el.getAttribute("data-cmp")}]` : ""} ${el.scrollWidth}x${el.scrollHeight}>${el.clientWidth}x${el.clientHeight}`,
        );
    }
    // Fixed-height controls whose text now overflows their box (tag + role only: no text captured).
    const tight: string[] = [];
    for (const el of Array.from(document.querySelectorAll<HTMLElement>("button,a,label,input"))) {
      const r = el.getBoundingClientRect();
      if (r.width === 0) continue;
      if (el.scrollWidth > el.clientWidth + 2 && getComputedStyle(el).whiteSpace === "nowrap")
        tight.push(
          `${el.tagName.toLowerCase()}${el.getAttribute("data-cmp") ? `[${el.getAttribute("data-cmp")}]` : ""}`,
        );
    }
    return {
      clipped: clipped.slice(0, 12),
      clipped_n: clipped.length,
      nowrap_overflow: tight.slice(0, 12),
      horizontal_scroll:
        document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
    };
  });
}

/** Motion inventory: visible elements with a non-zero transition or animation. */
async function motionCheck(page: Page): Promise<string[]> {
  return page.evaluate(() => {
    const out: string[] = [];
    for (const el of Array.from(document.querySelectorAll<HTMLElement>("body *"))) {
      const r = el.getBoundingClientRect();
      if (r.width === 0 || r.height === 0) continue;
      const cs = getComputedStyle(el);
      const tr = cs.transitionDuration.split(",").some((d) => parseFloat(d) > 0);
      const an =
        cs.animationName !== "none" &&
        cs.animationDuration.split(",").some((d) => parseFloat(d) > 0);
      const cls =
        typeof el.className === "string" && el.className ? `.${el.className.split(" ")[0]}` : "";
      if (tr || an)
        out.push(
          `${el.tagName.toLowerCase()}${cls} ${tr ? `transition ${cs.transitionProperty}:${cs.transitionDuration}` : ""}${an ? ` animation ${cs.animationName}:${cs.animationDuration} x${cs.animationIterationCount}` : ""}`,
        );
    }
    return out.slice(0, 20);
  });
}

/** 1.4.13: title tooltips and content that appears on hover of each focusable. */
async function hoverCheck(page: Page): Promise<Record<string, unknown>> {
  const titles = await page.evaluate(() =>
    Array.from(document.querySelectorAll("[title]"))
      .map((e) => e.tagName.toLowerCase())
      .slice(0, 10),
  );
  const handles = await page.locator("button:visible, a[href]:visible, input:visible").all();
  const appeared: string[] = [];
  for (const h of handles.slice(0, 25)) {
    const before = await page.evaluate(() => document.querySelectorAll("body *").length);
    await h.hover({ timeout: 2000 }).catch(() => undefined);
    await page.waitForTimeout(150);
    const after = await page.evaluate(() => ({
      n: document.querySelectorAll("body *").length,
      tips: document.querySelectorAll("[role=tooltip]").length,
    }));
    if (after.n !== before || after.tips > 0)
      appeared.push(`hover changed DOM (${before}->${after.n}, tooltips ${after.tips})`);
  }
  await page.mouse.move(0, 0);
  return { title_attrs: titles, hover_effects: appeared };
}

/** Headings and landmarks (names only). */
async function structure(page: Page): Promise<Record<string, unknown>> {
  return page.evaluate(() => {
    const hs = Array.from(document.querySelectorAll("h1,h2,h3,h4,h5,h6,[role=heading]"))
      .filter(
        (h) => (h as HTMLElement).offsetParent !== null || getComputedStyle(h).position === "fixed",
      )
      .map((h) => `${h.tagName.toLowerCase()} "${(h.textContent ?? "").trim().slice(0, 60)}"`);
    const lm = Array.from(
      document.querySelectorAll(
        "main,header,footer,nav,aside,section[aria-label],section[aria-labelledby],[role=main],[role=banner],[role=contentinfo],[role=navigation],[role=region],[role=complementary],form[aria-label]",
      ),
    ).map(
      (e) =>
        `${e.getAttribute("role") ?? e.tagName.toLowerCase()}${e.getAttribute("aria-label") ? ` "${e.getAttribute("aria-label")}"` : ""}`,
    );
    return {
      headings: hs,
      landmarks: lm,
      title: document.title,
      lang: document.documentElement.lang,
    };
  });
}

/** One state's SR-proxy record: focus, live writes, structure, the redacted ariaSnapshot. */
async function inspect(
  page: Page,
  scr: string,
  state: string,
  extra: Record<string, unknown> = {},
  tab = 0,
) {
  let snap = await page
    .locator("body")
    .ariaSnapshot()
    .catch((e: unknown) => `<snapshot failed: ${firstLine(e).slice(0, 80)}>`);
  snap = redactSnap(snap, scr, state);
  const focus = await focusInfo(page);
  const rec: Record<string, unknown> = {
    state,
    covered: true,
    focus, // role, accessible name and states only (names are allowed on every surface, BQ-10)
    live: await drainLive(page, scr, state),
    structure: await structure(page),
    snapshot: snap,
    ...extra,
  };
  if (tab) rec["tab"] = await tabWalk(page, tab);
  return rec;
}

async function layoutChecks(
  browser: Browser,
  o: OpenOpts,
  go: (p: Page, ws?: WsHarness) => Promise<void>,
) {
  const out: Record<string, unknown> = {};
  const run = async (opts: OpenOpts, f: (p: Page) => Promise<unknown>): Promise<unknown> => {
    const c = await openContext(browser, opts);
    try {
      await go(c.page, c.ws);
      return await f(c.page);
    } catch (e) {
      return { error: firstLine(e) };
    } finally {
      await c.context.close();
    }
  };
  out["reflow_320"] = await run({ ...o, vp: { width: 320, height: 640 } }, reflowCheck);
  out["text_spacing"] = await run(o, textSpacingCheck);
  out["motion_and_hover"] = await run(o, async (p) => ({
    motion_no_pref: await motionCheck(p),
    hover: await hoverCheck(p),
  }));
  out["motion_reduce"] = await run({ ...o, reduced: true }, motionCheck);
  return out;
}

// ------------------------------------------------------------------------------ mode: automated

/** axe target selectors, with any attribute value that could carry input text redacted. */
const redactSel = (sel: string): string =>
  sel.replace(
    /\[(value|placeholder|aria-valuetext|data-value)(\*|\^|\$)?=("[^"]*"|'[^']*'|[^\]]*)\]/g,
    "[$1=<redacted>]",
  );
const flatTarget = (t: unknown): string =>
  Array.isArray(t) ? t.map(flatTarget).join(" >>> ") : redactSel(String(t));

async function axeState(page: Page, s: Screen) {
  let axe = new AxeBuilder({ page })
    .options({ rules: { "color-contrast": { enabled: true } } })
    .withTags([...AXE_GATE_TAGS]);
  for (const inc of s.axeInclude ?? []) axe = axe.include(inc);
  const res = await axe.analyze();
  return {
    theme_observed: await page.locator("html").getAttribute("data-theme"),
    scope: s.axeInclude ?? "page",
    violations: res.violations.map((v) => ({
      id: v.id,
      impact: v.impact ?? null,
      wcag: v.tags.filter((t) => /^wcag/.test(t)),
      nodes: v.nodes.length,
      targets: v.nodes.map((n) => flatTarget(n.target)),
    })),
    incomplete: res.incomplete.map((v) => `${v.id}:${v.nodes.length}`),
    passes: res.passes.length,
  };
}

async function automated(browser: Browser) {
  const results: unknown[] = [];
  const timings: unknown[] = [];
  for (const s of SCREENS.filter((x) => selected(x.scr))) {
    const t0 = Date.now();
    for (const theme of THEMES) {
      const r0 = Date.now();
      const c = await openContext(browser, { ...screenOpts(s), theme });
      const run: Record<string, unknown> = {
        scr: s.scr,
        path: s.path,
        theme: theme.name,
        signed_in: s.role ?? null,
        states: [],
      };
      try {
        await s.stubs?.(c.page);
        await c.page.goto(s.path);
        await s.open({ page: c.page, ws: c.ws });
        const states = run["states"] as unknown[];
        states.push({ state: "default", ...(await axeState(c.page, s)) });
        for (const st of s.steps ?? []) {
          await st.go({ page: c.page, ws: c.ws });
          states.push({ state: st.label, ...(await axeState(c.page, s)) });
        }
        run["opened"] = true;
      } catch (e) {
        run["opened"] = false;
        run["reason"] = firstLine(e);
      } finally {
        run["landed"] = new URL(c.page.url()).pathname;
        run["ms"] = Date.now() - r0;
        run["off_loopback_aborted"] = c.offHost;
        await c.context.close();
      }
      results.push(run);
      console.log(`${s.scr} ${theme.name} opened=${String(run["opened"])}`);
    }
    timings.push({ scr: s.scr, ms: Date.now() - t0 });
  }
  emit("results.json", {
    mode: MODE,
    sha: SHA,
    auth_screens: [...AUTH],
    screens: results,
    timings,
  });
}

// --------------------------------------------------------------------------------- mode: wcag22

const VIEWPORTS = [
  ["1280x800", { width: 1280, height: 800 }],
  ["200pct(640x400)", { width: 640, height: 400 }], // 200 % zoom of 1280x800 in CSS px
] as const;
const SIZE_PROPS =
  /^(width|height|min-|max-|padding|font|line-height|border|box-sizing|display|inline-size|block-size|appearance|-webkit-appearance|zoom|transform|all|inset)/;

/** UA exception test: does any author rule or inline style set a size-affecting property on target i? */
async function authorSized(
  cdp: CDPSession,
  i: number,
): Promise<{ author: boolean; props: string[] }> {
  const { result } = await cdp.send("Runtime.evaluate", { expression: `window.__qaT[${i}]` });
  if (!result.objectId) return { author: true, props: ["<unresolved>"] };
  const { nodeId } = await cdp.send("DOM.requestNode", { objectId: result.objectId });
  const m = await cdp.send("CSS.getMatchedStylesForNode", { nodeId });
  const props = new Set<string>();
  for (const rm of m.matchedCSSRules ?? []) {
    if (rm.rule.origin !== "regular") continue;
    for (const p of rm.rule.style.cssProperties)
      if (SIZE_PROPS.test(p.name) && p.value) props.add(p.name);
  }
  for (const p of m.inlineStyle?.cssProperties ?? [])
    if (SIZE_PROPS.test(p.name) && p.value) props.add(`inline:${p.name}`);
  return { author: props.size > 0, props: [...props].slice(0, 8) };
}
const distToRect = (c: [number, number], r: [number, number, number, number]): number =>
  Math.hypot(Math.max(r[0] - c[0], 0, c[0] - r[2]), Math.max(r[1] - c[1], 0, c[1] - r[3]));

/** 2.5.8 judgement aids: undersized in-scope targets with the spacing test and the exception checks. */
async function judgeTargets(page: Page, cdp: CDPSession, scr: string, label: string) {
  const all = await probe<Target[]>(page, "targets");
  const small = all.filter((t) => t.size[0] < 24 || t.size[1] < 24);
  const out: unknown[] = [];
  for (const t of all) {
    if (!t.in_scope || (t.size[0] >= 24 && t.size[1] >= 24)) continue;
    const contains = (o: Target) =>
      o.rect[0] <= t.rect[0] &&
      o.rect[1] <= t.rect[1] &&
      o.rect[2] >= t.rect[2] &&
      o.rect[3] >= t.rect[3];
    const hitsTarget = all.filter(
      (o) => o !== t && distToRect(t.center, o.rect) < 12 && !contains(o),
    );
    const hitsCircle = small.filter(
      (o) => o !== t && Math.hypot(o.center[0] - t.center[0], o.center[1] - t.center[1]) < 24,
    );
    const spacingOk = hitsTarget.length === 0 && hitsCircle.length === 0;
    const formControl = ["button", "input", "select", "textarea", "summary"].includes(t.tag);
    const ua = formControl ? await authorSized(cdp, t.i) : null;
    const inline =
      t.inline_text_ratio !== null && t.inline_text_ratio[1] > t.inline_text_ratio[0] + 15;
    const equivalent = all
      .filter((o) => o !== t && o.desc === t.desc && o.size[0] >= 24 && o.size[1] >= 24)
      .map((o) => o.path);
    let verdict: string;
    if (t.disabled) verdict = "not-a-target (disabled)";
    else if (spacingOk) verdict = "pass (spacing exception)";
    else if (inline) verdict = "pass (inline exception)";
    else if (equivalent.length) verdict = "pass (equivalent exception)";
    else if (ua && !ua.author) verdict = "pass (user-agent exception)";
    else verdict = "fail";
    let png: string | null = null;
    if (verdict === "fail" && !AUTH.has(scr) && !t.has_value_text) {
      const box = await page.evaluate((i) => {
        const el = (window as unknown as QaWin).__qaT?.[i];
        if (!el) return { x: 0, y: 0, width: 0, height: 0 };
        el.scrollIntoView({ block: "center", inline: "center" });
        const r = el.getBoundingClientRect();
        return { x: r.left, y: r.top, width: r.width, height: r.height };
      }, t.i);
      if (box.width >= 1 && box.height >= 1) png = await shot(page, scr, box);
    }
    out.push({
      state: label,
      target: t.desc,
      path: t.path,
      size_css_px: t.size,
      own_box: t.own,
      label_folded: t.label_folded,
      disabled: t.disabled,
      spacing: spacingOk
        ? "clear"
        : {
            intersects_targets: hitsTarget.map((o) => o.desc).slice(0, 4),
            intersects_circles: hitsCircle.map((o) => o.desc).slice(0, 4),
          },
      inline,
      equivalent: equivalent.slice(0, 2),
      author_sized: ua,
      verdict,
      screenshot: png,
    });
  }
  return { measured_in_scope: all.filter((t) => t.in_scope).length, undersized: out };
}

/** 2.4.11 aid: Tab through every stop; each stop's covered fraction against fixed / sticky boxes. */
async function tabPass(page: Page, max = 700): Promise<FocusStep[]> {
  await page.evaluate(() => {
    (window as unknown as QaWin).__qaVisited = new Map();
  });
  const stops: FocusStep[] = [];
  let bodies = 0;
  let repeats = 0;
  for (let k = 0; k < max; k++) {
    await page.keyboard.press("Tab");
    const r = await probe<FocusStep>(page, "focusStep");
    if (r.body) {
      if (++bodies >= 2) break;
      continue;
    }
    bodies = 0;
    if (r.seen) {
      if (r.repeatOfFirst || ++repeats > 3) break;
      continue;
    }
    stops.push(r);
  }
  return stops;
}

/** 3.3.8 aid: attributes per field, the synthetic-paste veto, a real clipboard paste (length only). */
async function authFields(page: Page) {
  const fields = await probe<Field[]>(page, "fields");
  for (const f of fields) {
    if (!["password", "text", "email", "tel", "number", "search"].includes(f.type)) continue;
    f["synthetic_paste_prevented"] = await page.evaluate((i) => {
      const qa = (window as unknown as QaWin).__qa;
      return qa ? qa.syntheticPasteBlocked(i) : false;
    }, f.f);
    const stub = /code/i.test(f.label) ? STUB.pasteCode : STUB.pasteText;
    const len = (i: number) =>
      page.evaluate((x) => {
        const qa = (window as unknown as QaWin).__qa;
        return qa ? qa.fieldValueLength(x) : -1;
      }, i);
    const before = await len(f.f);
    await page.evaluate((s) => navigator.clipboard.writeText(s), stub);
    await page.evaluate((i) => (window as unknown as QaWin).__qaF?.[i]?.focus(), f.f);
    await page.keyboard.press("Control+V");
    const after = await len(f.f);
    const expect = f.maxlength ? Math.min(f.maxlength, before + stub.length) : before + stub.length;
    f["real_paste"] = {
      inserted_chars: after - before,
      expected_chars: expect - before,
      value: "<redacted>",
    };
    await page.keyboard.press("Control+A");
    await page.keyboard.press("Delete");
  }
  return { fields, signs: await probe<unknown>(page, "cognitiveSigns") };
}

async function checkState(page: Page, s: Screen, label: string, cdp: CDPSession | null) {
  await page.evaluate(installProbe);
  await page.evaluate(() => {
    (window as unknown as QaWin).__qaScope = undefined;
  });
  await s.scope?.(page);
  const scopeFound = await page.evaluate(
    () => (window as unknown as QaWin).__qaScope?.length ?? -1,
  );
  const rec: Record<string, unknown> = {
    state: label,
    scope_elements: scopeFound,
    overlays: await probe<unknown[]>(page, "overlays"),
  };
  if (cdp) {
    await cdp.send("DOM.getDocument", { depth: 0 });
    rec["targets"] = await judgeTargets(page, cdp, s.scr, label);
    rec["drags"] = await probe<unknown>(page, "drags");
    rec["help"] = await probe<unknown[]>(page, "help");
    if (AUTH.has(s.scr)) rec["auth"] = await authFields(page);
    else rec["fields"] = await probe<Field[]>(page, "fields");
  }
  // Tab pass last: it moves focus.
  rec["toasts_before_pass"] = await page.locator('[data-testid="toast-host"] p').count();
  rec["focus_stops"] = await tabPass(page);
  rec["toasts_after_pass"] = await page.locator('[data-testid="toast-host"] p').count();
  return rec;
}

/** Per-screen behaviour for 3.3.7 / 2.5.7 that needs interaction. Observations only. */
async function flow(page: Page, s: Screen): Promise<unknown> {
  if (s.scr === "SCR-001") {
    await toMfaStep({ page, ws: undefined });
    return {
      step2_heading: "Two-factor code",
      step2_inputs: await page.locator("main input").count(),
      identifier_asked_again: (await page.getByLabel("Username or email").count()) > 0,
    };
  }
  if (s.scr === "SCR-006") {
    await page.getByLabel("Password", { exact: true }).fill(STUB.stepUpPassword);
    await page.getByLabel("Authenticator code").fill(code());
    await page.getByRole("button", { name: "Confirm" }).click();
    await page.getByLabel("Invite link").waitFor({ timeout: W });
    return {
      step_ups: wire.stepUps,
      creates: wire.creates,
      dialog_closed: (await page.getByRole("alertdialog").count()) === 0,
      invite_result_shown: true,
    };
  }
  if (s.scr === "SCR-123") {
    const fields = await page.locator("main form").first().locator("input,select,textarea").count();
    return {
      form_fields: fields,
      steps: "single form; a step-up challenge (SCR-006) may interpose",
    };
  }
  if (s.scr === "SCR-018") {
    let n = 1;
    for (; n < 10; n++) {
      const next = page.getByRole("button", { name: /^Next/ });
      if ((await next.count()) === 0) break;
      await next.first().click();
    }
    const inputs = await page
      .locator('[role="dialog"] input, [role="dialog"] select, [role="dialog"] textarea')
      .count();
    return { tour_steps_seen: n, entry_fields: inputs };
  }
  return null;
}

async function wcag22(browser: Browser) {
  const results: unknown[] = [];
  const timings: unknown[] = [];
  for (const s of SCREENS.filter((x) => selected(x.scr))) {
    const t0 = Date.now();
    const out: Record<string, unknown> = {
      scr: s.scr,
      path: s.path,
      signed_in: s.role ?? null,
      runs: [],
    };
    for (const [vpName, vp] of VIEWPORTS) {
      const full = vpName === "1280x800";
      const c = await openContext(browser, { ...screenOpts(s), vp, listeners: true });
      const run: Record<string, unknown> = { viewport: vpName, states: [] };
      const r0 = Date.now();
      try {
        const cdp = full ? await c.context.newCDPSession(c.page) : null;
        if (cdp) {
          await cdp.send("DOM.enable");
          await cdp.send("CSS.enable");
        }
        await s.stubs?.(c.page);
        await c.page.goto(s.path);
        await s.open({ page: c.page, ws: c.ws });
        const states = run["states"] as unknown[];
        states.push(await checkState(c.page, s, "default", cdp));
        for (const st of s.steps ?? []) {
          await st.go({ page: c.page, ws: c.ws });
          states.push(await checkState(c.page, s, st.label, cdp));
        }
        if (full) run["flow"] = await flow(c.page, s);
        run["opened"] = true;
      } catch (e) {
        run["opened"] = false;
        run["reason"] = firstLine(e);
      } finally {
        run["ms"] = Date.now() - r0;
        run["off_loopback_aborted"] = c.offHost;
        await c.context.close();
      }
      (out["runs"] as unknown[]).push(run);
    }
    out["ms"] = Date.now() - t0;
    results.push(out);
    timings.push({ scr: s.scr, ms: out["ms"] });
    console.log(`${s.scr} wcag22 done`);
  }
  emit("results.json", { mode: MODE, sha: SHA, screens: results, timings });
}

// ----------------------------------------------------------------------------------- mode: deep

interface Rec {
  scr: string;
  theme: ThemeName;
  states: Record<string, unknown>[];
  checks: Record<string, unknown>;
  ms: number;
  off_loopback_aborted: Record<string, number>;
}
const rec = (scr: string, theme: Theme): Rec => ({
  scr,
  theme: theme.name,
  states: [],
  checks: {},
  ms: 0,
  off_loopback_aborted: {},
});
type DeepRun = (browser: Browser, theme: Theme) => Promise<Rec[]>;

const deepLogin: DeepRun = async (browser, theme) => {
  const t0 = Date.now();
  const r1 = rec("SCR-001", theme);
  const r2 = rec("SCR-002", theme);
  let mode: "invalid" | "slow-invalid" | "rate" | "disabled" | "unreachable" | "mfa" = "invalid";
  const loginRoute = (page: Page) =>
    page.route("**/api/v1/auth/login", async (r: Route) => {
      if (mode === "slow-invalid") {
        await new Promise((x) => setTimeout(x, 2500));
        return r.fulfill(json({ title: "x" }, 401));
      }
      if (mode === "invalid") return r.fulfill(json({ title: "x" }, 401));
      if (mode === "disabled") return r.fulfill(json({ title: "x" }, 403));
      if (mode === "rate") return r.fulfill(json({ title: "x" }, 429, { "Retry-After": "4" }));
      if (mode === "unreachable") return r.fulfill(json({ title: "x" }, 503));
      return r.fulfill(json({ status: "mfa_required", mfa_token: "t-1", methods: ["totp"] }));
    });
  const { context, page, offHost } = await openContext(browser, { theme, live: true });
  await loginRoute(page);
  const fresh = async () => {
    await page.goto("/login");
    await page.getByRole("main").waitFor({ timeout: W });
    await drainLive(page, "SCR-001", "");
  };
  const signIn = async () => {
    await fresh();
    await tabTo(page, /Username or email/);
    await page.keyboard.type(STUB.user);
    await page.keyboard.press("Tab");
    await page.keyboard.type(STUB.password);
    await page.keyboard.press("Enter");
  };
  await fresh();
  r1.states.push(await inspect(page, "SCR-001", "idle (on load)", {}, 6));
  mode = "slow-invalid";
  await signIn();
  await page.waitForTimeout(400);
  r1.states.push(
    await inspect(page, "SCR-001", "submitting (button spinner, fields locked)", {
      form_aria_busy: await page.locator("form").getAttribute("aria-busy"),
      fields_disabled: await page.locator("input:disabled").count(),
    }),
  );
  await page.getByText("Username or password is incorrect").waitFor({ timeout: W });
  r1.states.push(
    await inspect(
      page,
      "SCR-001",
      "error (generic message) after submitting",
      {
        id_aria_invalid: await page.locator("#login-id").getAttribute("aria-invalid"),
        pw_aria_invalid: await page.locator("#login-pw").getAttribute("aria-invalid"),
      },
      3,
    ),
  );
  mode = "invalid";
  await signIn();
  await page.getByText("Username or password is incorrect").waitFor({ timeout: W });
  r1.states.push(await inspect(page, "SCR-001", "error (generic message)"));
  mode = "disabled";
  await signIn();
  await page.getByText("Username or password is incorrect").waitFor({ timeout: W });
  r1.states.push(
    await inspect(
      page,
      "SCR-001",
      'account disabled ("This account is disabled. Contact the owner.")',
      {
        note: "403 renders the one invalid string by design (SR-014)",
      },
    ),
  );
  mode = "unreachable";
  await signIn();
  await page.getByText(/Cannot reach the server/).waitFor({ timeout: W });
  r1.states.push(await inspect(page, "SCR-001", "server unreachable (SCR-152 inline variant)"));
  await fresh();
  await tabTo(page, /^Sign in$/);
  await page.keyboard.press("Enter");
  await page.waitForTimeout(300);
  r1.states.push(
    await inspect(page, "SCR-001", "validation: empty username (extra state)", {
      id_aria_invalid: await page.locator("#login-id").getAttribute("aria-invalid"),
      id_describedby: await page.locator("#login-id").getAttribute("aria-describedby"),
    }),
  );
  mode = "rate";
  await signIn();
  await page.getByText(/Too many attempts/).waitFor({ timeout: W });
  const focusAtRate = await focusInfo(page);
  await page.waitForTimeout(5200);
  r1.states.push(
    await inspect(page, "SCR-001", "rate-limited (countdown)", {
      focus_when_rate_limited: focusAtRate,
      note: "live = writes during the 4 s countdown and the return to idle",
      submit_disabled_after: await page.locator("button[type=submit]").isDisabled(),
    }),
  );
  await fresh();
  await tabTo(page, /Show password/);
  const before = await focusInfo(page);
  await page.keyboard.press("Space");
  r1.states.push({
    state: "show/hide password toggle (extra)",
    covered: true,
    before,
    after: await focusInfo(page),
    pw_type_after: await page.locator("#login-pw").getAttribute("type"),
  });
  await page.goto("/login?reason=unlock_attempts");
  await page.getByRole("main").waitFor({ timeout: W });
  await page.waitForTimeout(300);
  r1.states.push(await inspect(page, "SCR-001", "arrival with reason=unlock_attempts (extra)"));
  mode = "mfa";
  await signIn();
  await page.getByRole("heading", { name: "Two-factor code" }).waitFor({ timeout: W });
  await page.waitForTimeout(200);
  r2.states.push(
    await inspect(page, "SCR-002", "built part: heading-only step after mfa_required", {}, 3),
  );
  await page.goto("/login/2fa");
  await page.waitForTimeout(800);
  r2.states.push(
    await inspect(page, "SCR-002", "R-002 /login/2fa bare (StubRoute: not audited as the screen)"),
  );
  r1.off_loopback_aborted = offHost;
  await context.close();
  r1.checks = await layoutChecks(browser, { theme }, async (p) => {
    await p.goto("/login");
    await p.getByRole("main").waitFor({ timeout: W });
  });
  r1.checks["reflow_320_error"] = await layoutError(browser, theme, async (p) => {
    mode = "unreachable";
    await loginRoute(p);
    await p.goto("/login");
    await p.getByLabel("Username or email").fill(STUB.user);
    await p.getByLabel("Password", { exact: true }).fill(STUB.password);
    await p.getByRole("button", { name: "Sign in" }).click();
    await p.getByText(/Cannot reach the server/).waitFor({ timeout: W });
  });
  r1.ms = Date.now() - t0;
  r2.ms = r1.ms; // one task script drives both
  return [r1, r2];
};
async function layoutError(
  browser: Browser,
  theme: Theme,
  go: (p: Page) => Promise<void>,
  o: OpenOpts = {},
) {
  const c = await openContext(browser, { ...o, theme, vp: { width: 320, height: 640 } });
  try {
    await go(c.page);
    return await reflowCheck(c.page);
  } catch (e) {
    return { error: firstLine(e) };
  } finally {
    await c.context.close();
  }
}

const deepEnrol: DeepRun = async (browser, theme) => {
  const t0 = Date.now();
  const r = rec("SCR-003", theme);
  const toStep3 = async (page: Page) => {
    await page.goto(`/invite/${INVITE}`);
    await page.getByRole("heading", { name: "Welcome, Ann" }).waitFor({ timeout: W });
    await tabTo(page, /Accept invitation/);
    await page.keyboard.press("Enter");
    await page.getByRole("heading", { name: "Choose a password" }).waitFor({ timeout: W });
    const f2 = await focusInfo(page);
    await tabTo(page, /New password/);
    await page.keyboard.type(STUB.newPassword);
    await page.keyboard.press("Enter");
    await page.getByRole("heading", { name: "Set up your authenticator" }).waitFor({ timeout: W });
    return f2;
  };
  const { context, page, offHost } = await openContext(browser, { theme, live: true });
  await inviteStubs(1)(page);
  const focusOnStep2 = await toStep3(page);
  await page.waitForTimeout(200);
  r.states.push(
    await inspect(
      page,
      "SCR-003",
      "loading QR -> key shown (step 3 entry)",
      {
        focus_on_entering_step2: focusOnStep2,
        qr_present: (await page.locator("img, canvas, svg[role=img]").count()) > 0,
        copy_control: (await page.getByRole("button", { name: /copy/i }).count()) > 0,
      },
      4,
    ),
  );
  await page.getByLabel("Authenticator code").focus();
  await page.keyboard.type(STUB.wrongCode);
  await page.keyboard.press("Enter");
  await page.getByText("That code did not work. Try again.").waitFor({ timeout: W });
  r.states.push(
    await inspect(page, "SCR-003", "confirm error", {
      code_aria_invalid: await page.getByLabel("Authenticator code").getAttribute("aria-invalid"),
      code_describedby: await page
        .getByLabel("Authenticator code")
        .getAttribute("aria-describedby"),
      code_cleared: (await page.getByLabel("Authenticator code").inputValue()).length === 0,
    }),
  );
  await page.getByLabel("Authenticator code").fill("");
  await page.getByLabel("Authenticator code").focus();
  await page.keyboard.type(code());
  await page.keyboard.press("Enter");
  await page.getByRole("heading", { name: "You are set up" }).waitFor({ timeout: W });
  await page.waitForTimeout(200);
  r.states.push(
    await inspect(
      page,
      "SCR-003",
      "codes shown once (warning that they are never shown again)",
      {
        copy_or_download_control:
          (await page.getByRole("button", { name: /copy|download/i }).count()) > 0,
        ack_checkbox: (await page.getByRole("checkbox").count()) > 0,
      },
      3,
    ),
  );
  r.states.push({
    state: "completed",
    covered: true,
    note: "same render as 'codes shown once': the 'Go to sign in' link is the completion",
  });
  r.off_loopback_aborted = offHost;
  await context.close();
  r.checks = await layoutChecks(browser, { theme }, async (p) => {
    await inviteStubs()(p);
    await toStep3(p);
  });
  r.ms = Date.now() - t0;
  return [r];
};

const deepChangePassword: DeepRun = async (browser, theme) => {
  const t0 = Date.now();
  const r = rec("SCR-004", theme);
  let mode: "breach" | "reuse" | "invalid" | "ok" | "down" = "breach";
  const { context, page, offHost } = await openContext(browser, { theme, live: true });
  await page.route("**/api/v1/auth/password", (x) => {
    if (mode === "breach") return x.fulfill(json({ code: "password_breached", title: "x" }, 422));
    if (mode === "reuse")
      return x.fulfill(json({ code: "password_reused", detail: "previous", title: "x" }, 422));
    if (mode === "invalid")
      return x.fulfill(json({ code: "current_password_invalid", title: "x" }, 401));
    if (mode === "down") return x.fulfill(json({ title: "x" }, 503));
    return x.fulfill({ status: 204, body: "" });
  });
  const fill = async (cur: string, nw: string, conf: string) => {
    await page.goto("/login/change-password");
    await page.getByRole("main").waitFor({ timeout: W });
    await drainLive(page, "SCR-004", "");
    await tabTo(page, /Current password/);
    await page.keyboard.type(cur);
    await page.keyboard.press("Tab");
    await page.keyboard.type(nw);
    await page.keyboard.press("Tab");
    await page.keyboard.type(conf);
    await page.keyboard.press("Enter");
    await page.waitForTimeout(400);
  };
  const P = STUB.policyPassword;
  await page.goto("/login/change-password");
  await page.getByRole("main").waitFor({ timeout: W });
  r.states.push(await inspect(page, "SCR-004", "default", {}, 7));
  await page.getByLabel("New password", { exact: true }).focus();
  await drainLive(page, "SCR-004", "");
  await page.keyboard.type("abcdefghijklmnop", { delay: 30 }); // stub
  r.states.push(
    await inspect(page, "SCR-004", "typing new password (extra: live requirement list)"),
  );
  await fill(STUB.oldPassword, "short", "short");
  r.states.push(
    await inspect(page, "SCR-004", "too short (<12 chars)", {
      new_aria_invalid: await page
        .getByLabel("New password", { exact: true })
        .getAttribute("aria-invalid"),
    }),
  );
  await fill(STUB.oldPassword, P, `${P.slice(0, -1)}X`);
  r.states.push(
    await inspect(page, "SCR-004", "confirmation mismatch", {
      conf_aria_invalid: await page.getByLabel("Confirm new password").getAttribute("aria-invalid"),
      conf_describedby: await page
        .getByLabel("Confirm new password")
        .getAttribute("aria-describedby"),
    }),
  );
  for (const [m, label] of [
    ["breach", "breached password"],
    ["reuse", "reuses one of previous 5"],
    ["invalid", "current password refused (extra)"],
    ["down", "server unreachable (extra)"],
  ] as const) {
    mode = m;
    await fill(m === "invalid" ? STUB.wrongOld : STUB.oldPassword, P, P);
    r.states.push(await inspect(page, "SCR-004", label));
  }
  mode = "ok";
  await fill(STUB.oldPassword, P, P);
  await page.getByRole("heading", { name: "Password changed" }).waitFor({ timeout: W });
  r.states.push(await inspect(page, "SCR-004", "changed (extra)", {}, 2));
  r.off_loopback_aborted = offHost;
  await context.close();
  r.checks = await layoutChecks(browser, { theme }, async (p) => {
    await p.goto("/login/change-password");
    await p.getByRole("main").waitFor({ timeout: W });
  });
  r.ms = Date.now() - t0;
  return [r];
};

const deepLock: DeepRun = async (browser, theme) => {
  const t0 = Date.now();
  const r = rec("SCR-005", theme);
  let session: "locked" | "warn" | "open" = "locked";
  let unlock: "invalid" | "ok" | "expired" = "invalid";
  const clock = (deadlineInS: number) => {
    const s = sessionInfo("owner");
    const st = Date.parse(s.server_time);
    return {
      ...s,
      session: {
        ...s.session,
        locked: false,
        idle_deadline: new Date(st + deadlineInS * 1000).toISOString(),
      },
    };
  };
  const locked = () => {
    const s = sessionInfo("owner");
    return { ...s, session: { ...s.session, locked: true } };
  };
  const stubs = async (page: Page) => {
    await page.route(
      (u) => u.pathname === "/api/v1/auth/session",
      (x) =>
        x.request().method() === "GET"
          ? x.fulfill(
              json(session === "locked" ? locked() : session === "warn" ? clock(40) : clock(900)),
            )
          : x.fallback(),
    );
    await page.route("**/api/v1/auth/session/extend", (x) => {
      session = "open";
      return x.fulfill(json(clock(900)));
    });
    await page.route("**/api/v1/auth/unlock", (x) => {
      if (unlock === "invalid") return x.fulfill(json({ code: "unlock_invalid", title: "x" }, 401));
      if (unlock === "expired")
        return x.fulfill(
          json({ code: "session_revoked", revoked_reason: "expired", title: "x" }, 401),
        );
      session = "open";
      return x.fulfill(json(clock(900)));
    });
    await page.route("**/api/v1/auth/logout", (x) => x.fulfill({ status: 204, body: "" }));
  };
  const o: OpenOpts = { role: "owner", ws: true, theme, live: true };
  {
    const { context, page, offHost } = await openContext(browser, o);
    await stubs(page);
    await page.goto("/terminal/last");
    await page.getByRole("alertdialog").waitFor({ timeout: W });
    await page.waitForTimeout(300);
    r.states.push(
      await inspect(
        page,
        "SCR-005",
        "default / idle-lock variant",
        {
          background_inert: await page.evaluate(() => document.querySelectorAll("[inert]").length),
          aria_hidden_siblings: await page.evaluate(
            () => document.querySelectorAll("body [aria-hidden=true]").length,
          ),
        },
        5,
      ),
    );
    await page.keyboard.press("Escape");
    const escStill = (await page.getByRole("alertdialog").count()) > 0;
    await page.getByLabel("Password").focus();
    await page.keyboard.type(STUB.wrongPassword);
    await page.keyboard.press("Enter");
    await page.getByText("Incorrect password. Try again.").waitFor({ timeout: W });
    r.states.push(
      await inspect(page, "SCR-005", "wrong password (extra)", {
        esc_kept_dialog: escStill,
        pw_aria_invalid: await page.getByLabel("Password").getAttribute("aria-invalid"),
      }),
    );
    await tabTo(page, /Sign out instead/, 6);
    await page.keyboard.press("Enter");
    await page.getByRole("heading", { name: "Sign out?" }).waitFor({ timeout: W });
    r.states.push(await inspect(page, "SCR-005", "sign-out-instead confirm (extra)", {}, 3));
    await page.keyboard.press("Escape");
    await page.getByRole("heading", { name: "Session locked" }).waitFor({ timeout: W });
    r.states.push(await inspect(page, "SCR-005", "back to unlock after Esc (extra)"));
    unlock = "ok";
    await page.getByLabel("Password").focus();
    await page.keyboard.type(STUB.rightPassword);
    await page.keyboard.press("Enter");
    await until(async () => (await page.getByRole("alertdialog").count()) === 0);
    await page.waitForTimeout(300);
    r.states.push(
      await inspect(page, "SCR-005", "unlock success: UI unfreezes, open orders reconciled", {
        note: "no open-orders reconciliation UI is mounted (no order panels); only the dialog close and focus are observable",
      }),
    );
    r.off_loopback_aborted = offHost;
    await context.close();
  }
  {
    session = "locked";
    unlock = "expired";
    const { context, page } = await openContext(browser, o);
    await stubs(page);
    await page.goto("/terminal/last");
    await page.getByRole("alertdialog").waitFor({ timeout: W });
    await page.getByLabel("Password").focus();
    await page.keyboard.type(STUB.anyPassword);
    await page.keyboard.press("Enter");
    await page.getByRole("heading", { name: "Session expired" }).waitFor({ timeout: W });
    await page.waitForTimeout(200);
    r.states.push(await inspect(page, "SCR-005", "absolute-expiry variant", {}, 2));
    await context.close();
  }
  for (const how of ["Escape", "Enter"] as const) {
    session = "warn";
    const { context, page } = await openContext(browser, o);
    await stubs(page);
    await page.goto("/journal");
    await page.getByRole("heading", { level: 1 }).first().waitFor({ timeout: W });
    await page.getByRole("alertdialog").waitFor({ timeout: W });
    if (how === "Escape") {
      await page.waitForTimeout(3200);
      r.states.push(
        await inspect(
          page,
          "SCR-005",
          "pre-lock warning (CMP-098, 60 s)",
          {
            note: "live = writes during ~3 s of countdown",
            countdown_live_attr: await page.getByText(/^Lock in/).getAttribute("aria-live"),
          },
          2,
        ),
      );
      await page.keyboard.press("Escape");
      await page.waitForTimeout(300);
      r.states.push(await inspect(page, "SCR-005", "pre-lock warning dismissed by Esc (extra)"));
    } else {
      await page.keyboard.press("Enter"); // focus starts on Stay signed in
      await until(async () => (await page.getByRole("alertdialog").count()) === 0);
      await page.waitForTimeout(300);
      r.states.push(await inspect(page, "SCR-005", "pre-lock warning extended (extra)"));
    }
    await context.close();
  }
  r.states.push({
    state: "emergency-stop path (killswitch:write)",
    covered: false,
    reason:
      "not built: SessionLockDialog renders Unlock and Sign out instead only (no kill-switch control)",
  });
  session = "locked";
  r.checks = await layoutChecks(browser, { role: "owner", ws: true, theme }, async (p) => {
    await stubs(p);
    await p.goto("/terminal/last");
    await p.getByRole("alertdialog").waitFor({ timeout: W });
  });
  r.ms = Date.now() - t0;
  return [r];
};

const deepStepUp: DeepRun = async (browser, theme) => {
  const t0 = Date.now();
  const r = rec("SCR-006", theme);
  let target: string | null = null;
  let expiresInMs = 5 * 60_000;
  let stepUp: "invalid" | "ok" = "invalid";
  let created = 0;
  const stubs = async (page: Page) => {
    await page.route("**/api/v1/users/invites", (x) => x.fulfill(json({ items: [] })));
    await page.route("**/api/v1/users", (x) => {
      created += 1;
      return created % 2 === 1
        ? x.fulfill(json(challenge(expiresInMs, target), 403))
        : x.fulfill(json(INVITE_CREATED, 201));
    });
    await page.route("**/api/v1/auth/step-up", (x) =>
      stepUp === "invalid"
        ? x.fulfill(json({ code: "mfa_invalid", title: "x" }, 401))
        : x.fulfill(
            json({
              elevated_until: new Date(Date.now() + 600_000).toISOString(),
              action_class: "users",
            }),
          ),
    );
  };
  const openDialog = async (page: Page) => {
    created = 0;
    await page.goto("/admin/users/new");
    await page.getByRole("heading", { level: 1 }).first().waitFor({ timeout: W });
    await tabTo(page, /^Username/);
    await page.keyboard.type("annie"); // stub username
    await tabTo(page, /Create invitation/);
    const opener = await focusInfo(page);
    await page.keyboard.press("Enter");
    await page.getByRole("alertdialog").waitFor({ timeout: W });
    await page.waitForTimeout(200);
    return opener;
  };
  const o: OpenOpts = { role: "owner", ws: true, theme, live: true };
  {
    const { context, page, offHost } = await openContext(browser, o);
    await stubs(page);
    const opener = await openDialog(page);
    r.states.push(await inspect(page, "SCR-006", "default (code-only)", { opener }, 6));
    await page.getByLabel("Password", { exact: true }).focus();
    await page.keyboard.type(STUB.stepUpPassword);
    await page.keyboard.press("Tab");
    await page.keyboard.type("12345"); // 5 digits: incomplete stub
    await page.keyboard.press("Enter");
    await page.waitForTimeout(300);
    r.states.push(
      await inspect(page, "SCR-006", "Confirm disabled until fields valid", {
        confirm_disabled: await page.getByRole("button", { name: "Confirm" }).isDisabled(),
        any_message: await page
          .getByRole("alertdialog")
          .locator("[role=alert],[role=status]")
          .count(),
        code_describedby: await page
          .getByLabel("Authenticator code")
          .getAttribute("aria-describedby"),
      }),
    );
    await page.keyboard.press("Escape");
    await page.waitForTimeout(400);
    r.states.push(
      await inspect(page, "SCR-006", "cancelled by Esc (extra: focus return, Not sent)"),
    );
    await openDialog(page);
    await drainLive(page, "SCR-006", "");
    for (let i = 1; i <= 3; i++) {
      await page.getByLabel("Password", { exact: true }).focus();
      await page.keyboard.type(STUB.stepUpPassword);
      await page.keyboard.press("Tab");
      await page.keyboard.type(STUB.wrongCode);
      await page.keyboard.press("Enter");
      await page.waitForTimeout(600);
      const open = (await page.getByRole("alertdialog").count()) > 0;
      r.states.push(
        await inspect(
          page,
          "SCR-006",
          i < 3 ? `failures 1-2 (failure ${i})` : "3rd-failure read-only downgrade (5 min)",
          {
            dialog_open: open,
            code_aria_invalid: open
              ? await page.getByLabel("Authenticator code").getAttribute("aria-invalid")
              : null,
          },
        ),
      );
    }
    r.off_loopback_aborted = offHost;
    await context.close();
  }
  {
    target = "annie";
    const { context, page } = await openContext(browser, o);
    await stubs(page);
    await openDialog(page);
    r.states.push(await inspect(page, "SCR-006", "code + typed confirmation", {}, 5));
    await page.getByLabel("Password", { exact: true }).fill(STUB.stepUpPassword);
    await page.getByLabel("Authenticator code").fill(code());
    await page.getByLabel(/to confirm/).focus();
    await page.keyboard.type("Annie"); // mismatched case, stub
    await page.keyboard.press("Enter");
    await page.waitForTimeout(300);
    r.states.push(
      await inspect(page, "SCR-006", "typed confirmation mismatch", {
        confirm_disabled: await page.getByRole("button", { name: "Confirm" }).isDisabled(),
        typed_aria_invalid: await page.getByLabel(/to confirm/).getAttribute("aria-invalid"),
        any_message: await page
          .getByRole("alertdialog")
          .locator("[role=alert],[role=status]")
          .count(),
      }),
    );
    stepUp = "ok";
    await page.getByLabel(/to confirm/).fill("annie");
    await page.getByRole("button", { name: "Confirm" }).focus();
    await page.keyboard.press("Enter");
    await page.getByLabel("Invite link").waitFor({ timeout: W });
    await page.waitForTimeout(300);
    r.states.push(
      await inspect(page, "SCR-006", "valid-grace (server expiry) / success (extra)", {
        note: "after a 200 step-up the held invite is re-sent and the dialog closes; the grace window itself has no UI",
      }),
    );
    await context.close();
  }
  {
    // 2.2.1: the challenge expires while the dialog is open
    target = null;
    stepUp = "invalid";
    expiresInMs = 4_000;
    const { context, page } = await openContext(browser, o);
    await stubs(page);
    await openDialog(page);
    await page.getByLabel("Password", { exact: true }).focus();
    await page.keyboard.type(STUB.stepUpPassword);
    await drainLive(page, "SCR-006", "");
    await page.waitForTimeout(5_000);
    r.states.push(
      await inspect(page, "SCR-006", "challenge expiry while typing (extra: 2.2.1)", {
        dialog_open: (await page.getByRole("alertdialog").count()) > 0,
      }),
    );
    await context.close();
    expiresInMs = 5 * 60_000;
  }
  {
    // pointer on the scrim, then Tab: does focus leave the modal?
    const { context, page } = await openContext(browser, o);
    await stubs(page);
    await openDialog(page);
    await page.mouse.click(5, 5);
    const afterClick = await focusInfo(page);
    r.states.push({
      state: "scrim click then Tab (extra: focus containment)",
      covered: true,
      after_click: afterClick,
      tab: await tabWalk(page, 3),
      dialog_open: (await page.getByRole("alertdialog").count()) > 0,
    });
    await context.close();
  }
  r.states.push({
    state: "no-grace variant (Live enablement / kill-switch disable)",
    covered: false,
    reason:
      "not reachable: no Live-enablement or kill-switch-disable screen is built at the sha; only R-303 mounts the gate",
  });
  r.checks = await layoutChecks(browser, { role: "owner", ws: true, theme }, async (p) => {
    await stubs(p);
    await openDialog(p);
  });
  r.ms = Date.now() - t0;
  return [r];
};

const deepDisconnected: DeepRun = async (browser, theme) => {
  const t0 = Date.now();
  const r = rec("SCR-152", theme);
  const ready = async (page: Page, ws?: WsHarness) => {
    await page.goto("/journal");
    await page.getByRole("heading", { level: 1 }).first().waitFor({ timeout: W });
    await until(async () => (ws?.authenticated() ?? 0) >= 1);
    await page.waitForTimeout(300);
  };
  const region = (page: Page) => page.getByRole("region", { name: "Connection" });
  const harness = (ws: WsHarness | undefined): WsHarness => {
    if (!ws) throw new Error("WS harness not installed");
    return ws;
  };
  const o: OpenOpts = { role: "owner", ws: true, theme, live: true };
  {
    const { context, page, ws, offHost } = await openContext(browser, o);
    const h = harness(ws);
    await ready(page, ws);
    r.states.push(
      await inspect(page, "SCR-152", "default (live: region absent)", {
        region: await region(page).count(),
      }),
    );
    await page.keyboard.press("Tab");
    await page.keyboard.press("Tab");
    const parked = await focusInfo(page);
    h.kill();
    await region(page).waitFor({ timeout: W });
    await page.waitForTimeout(4500);
    r.states.push(
      await inspect(page, "SCR-152", "reconnecting (backoff with jitter)", {
        parked_before_kill: parked,
        region_focusables: await region(page).locator("button,a,[tabindex]").count(),
        region_dom_index: await page.evaluate(() => {
          const reg = document.querySelector('section[aria-label="Connection"]');
          const m = document.querySelector("main");
          return reg && m
            ? reg.compareDocumentPosition(m) & Node.DOCUMENT_POSITION_FOLLOWING
              ? "before main"
              : "after main"
            : "n/a";
        }),
        note: "live = all writes in ~4.5 s after the drop (countdown is aria-live=off)",
      }),
    );
    h.restore();
    await until(async () => (await region(page).count()) === 0, 30_000);
    await page.waitForTimeout(500);
    r.states.push(await inspect(page, "SCR-152", "reconnected (extra: region clears)"));
    h.desync();
    await page.waitForTimeout(1200);
    r.states.push(await inspect(page, "SCR-152", "desync", { region: await region(page).count() }));
    h.revokeSession();
    await region(page).waitFor({ timeout: W });
    await page.waitForTimeout(800);
    r.states.push(
      await inspect(page, "SCR-152", "offline: retry stopped (extra: 4401 bye reconnect=false)"),
    );
    r.off_loopback_aborted = offHost;
    await context.close();
  }
  for (const [label, body] of [
    [
      "trading controls disabled: read-only R2 kill switch engaged (built part)",
      { kind: "kill_switch", kill_switch: { engaged: true, scope: "global" } },
    ],
    ["read-only R6 kill-switch status unknown (extra)", { kind: "kill_switch" }],
  ] as const) {
    const { context, page, ws } = await openContext(browser, {
      ...o,
      ws: { firstAuthSystem: [body] },
    });
    await ready(page, ws);
    r.states.push(await inspect(page, "SCR-152", label, { region: await region(page).count() }));
    await context.close();
  }
  {
    const { context, page, ws } = await openContext(browser, o);
    await page.clock.install();
    await ready(page, ws);
    harness(ws).kill();
    await region(page).waitFor({ timeout: W });
    await drainLive(page, "SCR-152", "");
    await page.clock.fastForward("05:10");
    await page.waitForTimeout(1500);
    const st = await page
      .locator('section[aria-label="Connection"]')
      .getAttribute("data-state")
      .catch(() => null);
    r.states.push(
      await inspect(page, "SCR-152", "stale - locked (long-outage escalation, page clock +5:10)", {
        data_state: st,
      }),
    );
    await context.close();
  }
  for (const s of [
    "panels frozen with last-good timestamp",
    "reconnected with divergence report",
    "per-account reconciling",
    "recovered summary",
  ])
    r.states.push({
      state: s,
      covered: false,
      reason:
        s === "panels frozen with last-good timestamp"
          ? "no data panels mounted at the sha (connection region only)"
          : "not built at the sha (ConnectionRegion defers recovered / Details / reconciliation)",
    });
  r.checks = await layoutChecks(browser, { role: "owner", ws: true, theme }, async (p, ws) => {
    await ready(p, ws);
    harness(ws).kill();
    await region(p).waitFor({ timeout: W });
  });
  r.ms = Date.now() - t0;
  return [r];
};

const deepErrorBoundary: DeepRun = async (browser, theme) => {
  const t0 = Date.now();
  const r = rec("SCR-156", theme);
  const crashPanel = async (page: Page) => {
    await page.route("**/api/v1/onboarding/checklist", (x) =>
      x.fulfill(json({ complete: false, dismissed: false, items: null })),
    );
    await page.goto("/terminal/last");
    await page.getByRole("button", { name: /Reload panel/ }).waitFor({ timeout: W });
    await page.waitForTimeout(300);
  };
  const crashRoute = async (page: Page) => {
    // Route level: an invites list body with items = null makes AdminInviteScreen throw at render.
    await page.route("**/api/v1/users/invites", (x) => x.fulfill(json({ items: null })));
    await page.goto("/admin/users/new");
    await page.getByRole("button", { name: /Reload page/ }).waitFor({ timeout: W });
  };
  const o: OpenOpts = { role: "owner", ws: true, theme, live: true };
  {
    const { context, page, offHost } = await openContext(browser, o);
    await crashPanel(page);
    r.states.push(await inspect(page, "SCR-156", "panel level (default)", {}, 6));
    await page.getByRole("button", { name: "Technical detail" }).focus();
    await page.keyboard.press("Enter");
    const expanded = await page
      .getByRole("button", { name: "Technical detail" })
      .getAttribute("aria-expanded");
    await page.getByRole("button", { name: "Copy diagnostics" }).focus();
    await page.keyboard.press("Enter");
    await page.waitForTimeout(400);
    r.states.push(
      await inspect(page, "SCR-156", "diagnostics action", { technical_detail_expanded: expanded }),
    );
    for (let i = 2; i <= 3; i++) {
      await page.getByRole("button", { name: "Reload panel" }).focus();
      await page.keyboard.press("Enter");
      await page.waitForTimeout(800);
      r.states.push(
        await inspect(
          page,
          "SCR-156",
          i < 3 ? "panel level after Reload panel (extra: crash 2)" : "repeated-crash stop",
          {
            reload_panel_present: await page.getByRole("button", { name: "Reload panel" }).count(),
          },
          i === 3 ? 4 : 0,
        ),
      );
    }
    r.off_loopback_aborted = offHost;
    await context.close();
  }
  {
    const { context, page } = await openContext(browser, o);
    let calls = 0;
    await page.route("**/api/v1/onboarding/checklist", (x) => {
      calls += 1;
      return x.fulfill(
        json(
          calls === 1
            ? { complete: false, dismissed: false, items: null }
            : { complete: false, dismissed: false, items: [] },
        ),
      );
    });
    await page.goto("/terminal/last");
    await page.getByRole("button", { name: /Reload panel/ }).waitFor({ timeout: W });
    await page.getByRole("button", { name: "Reload panel" }).focus();
    await drainLive(page, "SCR-156", "");
    await page.keyboard.press("Enter");
    await page.waitForTimeout(1000);
    r.states.push(
      await inspect(page, "SCR-156", "Reload panel succeeds (extra: focus after recovery)", {
        fallback_present: await page.locator('[data-cmp="CMP-091"]').count(),
        checklist_calls: calls,
      }),
    );
    await context.close();
  }
  {
    const { context, page } = await openContext(browser, o);
    await crashRoute(page);
    await page.waitForTimeout(300);
    r.states.push(await inspect(page, "SCR-156", "route level", {}, 6));
    await context.close();
  }
  r.states.push({
    state: "default",
    covered: true,
    note: "the catalogue's derived default is the panel-level fallback: see 'panel level (default)'",
  });
  r.checks = await layoutChecks(browser, { role: "owner", ws: true, theme }, crashPanel);
  r.checks["reflow_320_route"] = await layoutError(browser, theme, crashRoute, {
    role: "owner",
    ws: true,
  });
  r.ms = Date.now() - t0;
  return [r];
};

const DEEP: readonly (readonly [readonly string[], DeepRun])[] = [
  [["SCR-001", "SCR-002"], deepLogin],
  [["SCR-003"], deepEnrol],
  [["SCR-004"], deepChangePassword],
  [["SCR-005"], deepLock],
  [["SCR-006"], deepStepUp],
  [["SCR-152"], deepDisconnected],
  [["SCR-156"], deepErrorBoundary],
];

async function deep(browser: Browser) {
  const results: Rec[] = [];
  const failures: unknown[] = [];
  for (const [ids, run] of DEEP) {
    if (!ids.some(selected)) continue;
    for (const theme of THEMES) {
      const t0 = Date.now();
      try {
        results.push(...(await run(browser, theme)));
      } catch (e) {
        failures.push({ scr: ids, theme: theme.name, reason: firstLine(e), ms: Date.now() - t0 });
      }
      console.log(`${ids.join("+")} ${theme.name} deep done (${Date.now() - t0} ms)`);
    }
  }
  const timings = results.map((r) => ({ scr: r.scr, theme: r.theme, ms: r.ms }));
  emit("results.json", { mode: MODE, sha: SHA, screens: results, failures, timings });
}

// ----------------------------------------------------------------------------------- mode: spot

/** Spot check (BQ-08 (b)): keyboard walk, contrast spot check, one activation, SR proxies, layout. */
const SPOT: readonly string[] = ["SCR-113", "SCR-116", "SCR-117"];
async function spotActivate(page: Page, scr: string): Promise<Record<string, unknown>> {
  const html = () =>
    page.evaluate(() => ({
      theme: document.documentElement.getAttribute("data-theme"),
      attrs: Array.from(document.documentElement.attributes)
        .map((a) => a.name)
        .filter((n) => n.startsWith("data-")),
    }));
  if (scr === "SCR-113") {
    const first = page.locator('section[aria-labelledby="hk-h"]').getByRole("button").first();
    await first.focus();
    const before = await focusInfo(page);
    await page.keyboard.press("Enter");
    await page.waitForTimeout(300);
    const during = await focusInfo(page);
    await page.keyboard.press("Escape");
    await page.waitForTimeout(300);
    return {
      action: "Enter on the first editor button, then Escape",
      before,
      during,
      after: await focusInfo(page),
    };
  }
  if (scr === "SCR-116") {
    const radio = page.getByRole("radio").first();
    await radio.focus();
    const before = { focus: await focusInfo(page), html: await html() };
    await page.keyboard.press("ArrowDown");
    await page.waitForTimeout(300);
    return {
      action: "ArrowDown in the first radio group",
      before,
      after: { focus: await focusInfo(page), html: await html() },
    };
  }
  const section = page.locator('section[aria-labelledby="a11y-h"]');
  const ctl = section.getByRole("switch").or(section.getByRole("checkbox")).first();
  await ctl.focus();
  const before = { focus: await focusInfo(page), html: await html() };
  await page.keyboard.press("Space");
  await page.waitForTimeout(300);
  return {
    action: "Space on the first switch / checkbox",
    before,
    after: { focus: await focusInfo(page), html: await html() },
  };
}
/**
 * Contrast spot check (BQ-08 (b), heuristic): axe `color-contrast` "incomplete" nodes, which axe could not
 * resolve, are measured from pixels. Each node is scrolled into view and clipped in memory; the most
 * frequent colour is the background and the highest-contrast colour (at least 2 px) the foreground,
 * against 4.5:1 (3:1 for large text); computed styles are kept as the cross-check. A clip PNG is saved
 * (shot(), BQ-25) only for a node below its threshold that is not disabled.
 */
async function contrastSpot(page: Page, s: Screen) {
  let axe = new AxeBuilder({ page }).withRules(["color-contrast"]);
  for (const inc of s.axeInclude ?? []) axe = axe.include(inc);
  const res = await axe.analyze();
  const nodes = res.incomplete.find((v) => v.id === "color-contrast")?.nodes ?? [];
  const out: Record<string, unknown>[] = [];
  for (const n of nodes.slice(0, 600)) {
    const data = (n.any[0]?.data ?? {}) as Record<string, unknown>;
    const rec: Record<string, unknown> = {
      target: flatTarget(n.target),
      messageKey: data["messageKey"] ?? null,
    };
    try {
      const loc = page.locator(n.target.map(String).join(" ")).first();
      await loc.scrollIntoViewIfNeeded({ timeout: 2000 });
      const info = await loc.evaluate((el) => {
        const cs = getComputedStyle(el);
        let bg: string | null = null;
        for (let e: Element | null = el; e && bg === null; e = e.parentElement) {
          const b = getComputedStyle(e).backgroundColor;
          if (b !== "rgba(0, 0, 0, 0)") bg = b;
        }
        return {
          tag: el.tagName.toLowerCase(),
          color: cs.color,
          bg,
          fs: parseFloat(cs.fontSize),
          fw: parseInt(cs.fontWeight, 10) || 400,
          hidden: cs.visibility === "hidden",
          disabled: el.closest("[aria-disabled=true], :disabled") !== null,
        };
      });
      Object.assign(rec, {
        tag: info.tag,
        color: info.color,
        background: info.bg,
        font_px: info.fs,
        weight: info.fw,
        disabled: info.disabled,
      });
      const required = info.fs >= 24 || (info.fs >= 18.66 && info.fw >= 700) ? 3 : 4.5;
      rec["required"] = required;
      const box = await loc.boundingBox();
      if (!box || box.width < 2 || box.height < 2 || info.hidden) {
        rec["verdict"] = "not measurable (no visible box)";
        out.push(rec);
        continue;
      }
      const clip = {
        x: Math.max(0, box.x),
        y: Math.max(0, box.y),
        width: Math.max(2, Math.min(box.width, 1280)),
        height: Math.max(2, Math.min(box.height, 800)),
      };
      const buf = await page.screenshot({ clip });
      const px = await page.evaluate(async (b64) => {
        const img = new Image();
        img.src = "data:image/png;base64," + b64;
        await img.decode();
        const cv = document.createElement("canvas");
        cv.width = img.width;
        cv.height = img.height;
        const cx = cv.getContext("2d");
        if (!cx) return null;
        cx.drawImage(img, 0, 0);
        const d = cx.getImageData(0, 0, cv.width, cv.height).data;
        const hist = new Map<string, number>();
        for (let i = 0; i < d.length; i += 4) {
          const k = `${d[i]},${d[i + 1]},${d[i + 2]}`;
          hist.set(k, (hist.get(k) ?? 0) + 1);
        }
        const lum = (k: string) => {
          const [r, g, b] = k.split(",").map((v) => {
            const c = Number(v) / 255;
            return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
          });
          return 0.2126 * (r ?? 0) + 0.7152 * (g ?? 0) + 0.0722 * (b ?? 0);
        };
        const ent = [...hist.entries()].sort((a, b) => b[1] - a[1]);
        const bg = ent[0]?.[0] ?? "0,0,0";
        const lb = lum(bg);
        let best = 1;
        let fg = bg;
        for (const [k, c] of ent) {
          if (c < 2) continue;
          const l = lum(k);
          const ratio = (Math.max(l, lb) + 0.05) / (Math.min(l, lb) + 0.05);
          if (ratio > best) {
            best = ratio;
            fg = k;
          }
        }
        return { bg, fg, ratio: Math.round(best * 100) / 100, colours: ent.length };
      }, buf.toString("base64"));
      rec["pixel"] = px;
      rec["verdict"] = !px
        ? "not measurable"
        : px.colours < 2
          ? "no text pixels in box"
          : px.ratio >= required
            ? "meets (pixel)"
            : info.disabled
              ? "below (disabled: exempt)"
              : "below (pixel)";
      if (rec["verdict"] === "below (pixel)")
        rec["png"] = await shot(page, s.scr, {
          x: Math.max(0, clip.x - 8),
          y: Math.max(0, clip.y - 8),
          width: clip.width + 16,
          height: clip.height + 16,
        });
    } catch (e) {
      rec["verdict"] = `not measurable (${firstLine(e)})`;
    }
    out.push(rec);
  }
  const tally: Record<string, number> = {};
  const keys: Record<string, number> = {};
  for (const r of out) {
    const v = String(r["verdict"]).split(" (")[0] ?? "?";
    tally[v] = (tally[v] ?? 0) + 1;
    const k = String(r["messageKey"]);
    keys[k] = (keys[k] ?? 0) + 1;
  }
  return { heuristic: true, incomplete_nodes: nodes.length, tally, messageKeys: keys, nodes: out };
}
async function spot(browser: Browser) {
  const results: unknown[] = [];
  for (const s of SCREENS.filter((x) => SPOT.includes(x.scr) && selected(x.scr))) {
    for (const theme of THEMES) {
      const t0 = Date.now();
      const out: Record<string, unknown> = { scr: s.scr, theme: theme.name };
      const c = await openContext(browser, { ...screenOpts(s), theme, live: true });
      try {
        await s.stubs?.(c.page);
        await c.page.goto(s.path);
        await s.open({ page: c.page, ws: c.ws });
        out["default"] = await inspect(c.page, s.scr, "default", {}, 30);
        out["contrast_spot"] = await contrastSpot(c.page, s);
        out["activation"] = await spotActivate(c.page, s.scr);
        out["live_after_activation"] = await drainLive(c.page, s.scr, "activation");
        out["opened"] = true;
      } catch (e) {
        out["opened"] = false;
        out["reason"] = firstLine(e);
      } finally {
        out["off_loopback_aborted"] = c.offHost;
        await c.context.close();
      }
      out["checks"] = await layoutChecks(browser, { ...screenOpts(s), theme }, async (p, ws) => {
        await s.stubs?.(p);
        await p.goto(s.path);
        await s.open({ page: p, ws });
      });
      out["ms"] = Date.now() - t0;
      results.push(out);
      console.log(`${s.scr} ${theme.name} spot done`);
    }
  }
  const timings = results.map((r) => {
    const x = r as Record<string, unknown>;
    return { scr: x["scr"], theme: x["theme"], ms: x["ms"] };
  });
  emit("results.json", { mode: MODE, sha: SHA, screens: results, timings });
}

// --------------------------------------------------------------------------------- mode: sanity

async function sanity(browser: Browser) {
  const c = await openContext(browser);
  const out: Record<string, unknown> = {};
  try {
    const page = c.page;
    await page.goto("/404");
    await main(page);
    await page.evaluate(() => {
      const m = document.querySelector("main");
      const p = document.createElement("p");
      p.textContent = "sanity low contrast";
      p.style.cssText = "color:#777;background:#808080;font-size:12px";
      m?.appendChild(p);
      const i = document.createElement("input");
      i.type = "text";
      m?.appendChild(i);
      const bar = document.createElement("div");
      bar.style.cssText =
        "position:fixed;top:0;left:0;right:0;height:120px;background:#123;z-index:9999";
      document.body.appendChild(bar);
      const mk = (txt: string, css: string) => {
        const b = document.createElement("button");
        b.textContent = txt;
        b.style.cssText = css;
        document.body.appendChild(b);
      };
      mk("under", "position:absolute;top:20px;left:20px;width:80px;height:30px");
      mk(
        "a",
        "position:absolute;top:300px;left:300px;width:10px;height:10px;padding:0;font-size:6px",
      );
      mk(
        "b",
        "position:absolute;top:300px;left:315px;width:10px;height:10px;padding:0;font-size:6px",
      );
      mk(
        "c",
        "position:absolute;top:600px;left:900px;width:10px;height:10px;padding:0;font-size:6px",
      );
    });
    const res = await new AxeBuilder({ page })
      .options({ rules: { "color-contrast": { enabled: true } } })
      .withTags([...AXE_GATE_TAGS])
      .analyze();
    const ids = res.violations.map((v) => v.id);
    await page.evaluate(installProbe);
    const cdp = await c.context.newCDPSession(page);
    await cdp.send("DOM.enable");
    await cdp.send("CSS.enable");
    await cdp.send("DOM.getDocument", { depth: 0 });
    const t = await judgeTargets(page, cdp, "SANITY", "default");
    const v = Object.fromEntries(
      (t.undersized as { target: string; verdict: string }[]).map((u) => [u.target, u.verdict]),
    );
    const under = (await tabPass(page)).find((s) => s.stop === 'button "under"');
    const checks = {
      axe_color_contrast: ids.includes("color-contrast"),
      axe_label: ids.includes("label"),
      focus_hidden_under_fixed_bar: under?.state === "hidden",
      target_a_fail: v['button "a"'] === "fail",
      target_b_fail: v['button "b"'] === "fail",
      target_c_spacing_pass: v['button "c"'] === "pass (spacing exception)",
    };
    out["checks"] = checks;
    out["ok"] = Object.values(checks).every(Boolean);
  } finally {
    await c.context.close();
  }
  emit("results.json", { mode: MODE, sha: SHA, ...out });
  if (!out["ok"]) throw new Error(`instrument sanity failed: ${JSON.stringify(out["checks"])}`);
}

// ------------------------------------------------------------------------------------- the test

test(`E47-T01 sweep (${MODE})`, async ({ browser }) => {
  await loadSupport();
  const run = { automated, wcag22, deep, spot, sanity }[MODE];
  await run(browser);
  console.log(`results: ${join(OUT, "results.json")}`);
});
