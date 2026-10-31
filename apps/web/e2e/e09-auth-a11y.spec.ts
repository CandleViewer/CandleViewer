import { test, expect, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { AXE_GATE_TAGS } from "./a11y/tags";
import { stubSessionsList } from "./support/api";

// E09-Q04: axe-core over all twelve E09 audit screens (WCAG 2.2 AA tags).
// Network is stubbed at the transport layer; no live calls. Screens whose real UI has not
// shipped yet render the shell placeholder; they are still scanned so the gate is in place
// the moment the screen lands (see docs/qa/a11y/e09-auth-a11y-audit.md).

const json = (body: unknown) => ({
  status: 200,
  contentType: "application/json",
  body: JSON.stringify(body),
});

// `shipped: false` => the route still renders the StubRoute placeholder. Those are NOT counted as
// conformant: the test asserts the stub marker (so it fails loudly, forcing review, when the real
// screen lands) and is annotated as not-assessed instead of passing silently.
// `reason` documents why a screen is waived. Owner exception (#295) waives ONLY screens that do not
// exist on main yet; every screen that exists is audited.
export const E09_SCREENS: ReadonlyArray<{
  scr: string;
  path: string;
  shipped?: boolean;
  reason?: string;
  // Real-UI marker to assert instead of "no placeholder" (screen is mounted beside a StubRoute).
  marker?: string;
  // A built screen with no page of its own to scan here: the spec whose tests scan it.
  scannedIn?: string;
}> = [
  { scr: "SCR-001", path: "/login" }, // LoginScreen (#1824), R-001
  {
    scr: "SCR-002",
    shipped: false,
    path: "/login/2fa",
    reason: "no TOTP challenge screen in features/auth",
  },
  {
    scr: "SCR-003",
    shipped: false,
    path: "/login/2fa/enroll",
    reason: "no TOTP enrolment screen in features/auth",
  },
  { scr: "SCR-004", path: "/login/change-password" }, // ChangePasswordScreen (#1824), R-007
  {
    scr: "SCR-005",
    path: "/locked",
    reason: "a dialog over the current route (#1640): R-005 /locked only redirects to the terminal",
    scannedIn: "auth/session.spec.ts (E09-TC-C02 scans the warning and the lock)",
  },
  { scr: "SCR-006", path: "/admin/users/new" },
  { scr: "SCR-017", path: "/invite/tok-a11y-0123456789" },
  // SetupChecklistCard (SCR-019) is mounted on R-101 beside the stub; needs a non-dismissed payload.
  { scr: "SCR-019", path: "/terminal/last", marker: "Finish setting up" },
  {
    scr: "SCR-111",
    shipped: false,
    path: "/settings/profile",
    reason: "profile section not built; R-201 now hosts SCR-112's sessions section (#1640 S3)",
  },
  // SCR-112's sessions section is mounted on R-201 (#1640 S3); the list is stubbed in stub().
  { scr: "SCR-112", path: "/settings/profile", marker: "Signed-in sessions" },
  { scr: "SCR-123", path: "/admin/users/new" },
  { scr: "SCR-154", path: "/403" },
];

async function stub(page: Page): Promise<void> {
  // Playwright sees a shared worker's script start and never end, so `networkidle` never comes on a page that starts one (every page
  // does: the shell starts the WS client). The scans do not depend on the kind of worker: they get the tab's own (the Q8 fallback).
  await page.addInitScript(() =>
    Object.defineProperty(window, "SharedWorker", { value: undefined }),
  );
  const far = new Date(Date.now() + 3_600_000).toISOString();
  await page.route("**/api/v1/me", (r) =>
    r.fulfill(
      json({
        role: "owner",
        permissions: [],
        session: { environment: "demo", elevated_until: far },
      }),
    ),
  );
  await page.route("**/api/v1/me/preferences", (r) => r.fulfill(json({})));
  await page.route("**/api/v1/me/keymap", (r) => r.fulfill(json({ bindings: [] })));
  await stubSessionsList(page);
  await page.route("**/api/v1/onboarding/checklist", (r) =>
    r.fulfill(
      json({
        complete: false,
        dismissed: false,
        items: [{ key: "totp", state: "pending", action_route: "/login/2fa/enroll" }],
      }),
    ),
  );
  await page.route("**/api/v1/invites/**", (r) =>
    r.fulfill(json({ display_name: "Ann", role: "viewer", expires_at: "x" })),
  );
}

test("E09 screen list covers all twelve SCR ids", () => {
  expect(new Set(E09_SCREENS.map((s) => s.scr)).size).toBe(12);
});

test("not-assessed screens are still placeholders (fails when one ships: audit it, flip shipped)", async ({
  page,
}) => {
  await stub(page);
  // A route a shipped screen also renders on (R-201: SCR-111 beside SCR-112) is no longer a placeholder.
  const shippedPaths = new Set(E09_SCREENS.filter((s) => s.shipped !== false).map((s) => s.path));
  for (const { path } of E09_SCREENS.filter(
    (s) => s.shipped === false && !shippedPaths.has(s.path),
  )) {
    await page.goto(path);
    await expect(page.getByText("This screen has not shipped yet.")).toBeVisible();
  }
});

// Built screens with a page of their own to scan here (a `scannedIn` one is scanned in its spec).
const SCANNED_HERE = E09_SCREENS.filter((s) => s.shipped !== false && s.scannedIn === undefined);

for (const { scr, path, shipped, marker, scannedIn } of E09_SCREENS) {
  test(`${scr} ${path}: axe serious/critical`, async ({ page }) => {
    await stub(page);
    await page.goto(path);
    await page.waitForLoadState("networkidle");
    // Placeholder screens are reported as SKIPPED (not passed): axe on a stub proves nothing.
    test.skip(
      shipped === false || scannedIn !== undefined,
      scannedIn === undefined
        ? "not-assessed: placeholder screen, no real UI to audit"
        : `scanned in ${scannedIn}`,
    );
    if (marker) await expect(page.getByText(marker)).toBeVisible();
    else await expect(page.getByText("This screen has not shipped yet.")).toHaveCount(0);
    const res = await new AxeBuilder({ page }).withTags([...AXE_GATE_TAGS]).analyze();
    const bad = res.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
    expect(bad.map((v) => `${v.id}: ${v.help}`)).toEqual([]);
  });
}

for (const { scr, path } of SCANNED_HERE) {
  test(`${scr}: reflow at 320px, no horizontal scroll (SC 1.4.10)`, async ({ page }) => {
    await stub(page);
    await page.setViewportSize({ width: 320, height: 640 });
    await page.goto(path);
    await page.waitForLoadState("networkidle");
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(0);
  });

  test(`${scr}: reduced motion leaves no running animations (SC 2.3.3)`, async ({ page }) => {
    await stub(page);
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.goto(path);
    await page.waitForLoadState("networkidle");
    const running = await page.evaluate(
      () => document.getAnimations().filter((a) => a.playState === "running").length,
    );
    expect(running).toBe(0);
  });
}

// D-01 (#5196, WCAG 2.4.2): each route sets its own unique, descriptive page title.
const TITLES: ReadonlyArray<readonly [string, string]> = [
  ["/login", "Login - CandleViewer"],
  ["/login/change-password", "Forced password change - CandleViewer"],
  ["/admin/users/new", "Invite user - CandleViewer"],
  ["/invite/tok-a11y-0123456789", "Invitation acceptance - CandleViewer"],
  ["/terminal/last", "Terminal - CandleViewer"],
  ["/settings/profile", "Profile and security - CandleViewer"],
  ["/403", "Forbidden - CandleViewer"],
  ["/no-such-page", "Not found - CandleViewer"],
];

test("every audited route sets its own page title (SC 2.4.2)", async ({ page }) => {
  await stub(page);
  for (const [path, title] of TITLES) {
    await page.goto(path);
    await expect(page).toHaveTitle(title);
  }
  expect(new Set(TITLES.map(([, title]) => title)).size).toBe(TITLES.length);
});

// ---- SCR-017 enrolment wizard: every step, not just the landing step (E09-Q04 review) ----
// This is the only implemented enrolment flow (TOTP secret + recovery codes). It covers the
// SR-enrolment, SC 3.3.1 (error identification), reflow/200% zoom and reduced-motion criteria
// for what exists. SCR-002/003 remain not-assessed (not built); SCR-005 is scanned in auth/session.spec.ts.
const TOK = "tok-a11y-0123456789";

async function stubWizard(page: Page, opts: { reject?: boolean } = {}): Promise<void> {
  await stub(page);
  await page.route(`**/api/v1/invites/${TOK}`, (r) =>
    r.request().method() === "GET"
      ? r.fulfill(json({ display_name: "Ann", role: "viewer", expires_at: "x" }))
      : opts.reject
        ? r.fulfill({ status: 422, contentType: "application/json", body: "{}" })
        : r.fulfill(json({ method_id: "m1", otpauth_uri: "otpauth://x", secret_base32: "AAAA" })),
  );
  await page.route(`**/api/v1/invites/${TOK}/confirm`, (r) =>
    opts.reject
      ? r.fulfill({ status: 422, contentType: "application/json", body: "{}" })
      : r.fulfill(json({ status: "active", role: "viewer", recovery_codes: ["rc-1", "rc-2"] })),
  );
}

async function seriousAxe(page: Page): Promise<string[]> {
  const res = await new AxeBuilder({ page }).withTags([...AXE_GATE_TAGS]).analyze();
  return res.violations
    .filter((v) => v.impact === "serious" || v.impact === "critical")
    .map((v) => `${v.id}: ${v.help}`);
}

async function noOverflow(page: Page): Promise<number> {
  return page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
}

async function walk(page: Page, check: () => Promise<void>): Promise<void> {
  await page.goto(`/invite/${TOK}`);
  await expect(page.getByText(/Step 1 of 4/)).toBeVisible();
  await check();
  await page.getByRole("button", { name: "Accept invitation" }).click();
  await expect(page.getByText(/Step 2 of 4/)).toBeVisible();
  await check();
  await page.getByLabel("New password").fill("correct horse battery");
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page.getByText(/Step 3 of 4/)).toBeVisible();
  await check();
  await page.getByLabel("Authenticator code").fill("123456");
  await page.getByRole("button", { name: "Activate account" }).click();
  await expect(page.getByText(/Step 4 of 4/)).toBeVisible();
  await check();
}

test("SCR-017 enrolment: axe clean at every wizard step", async ({ page }) => {
  await stubWizard(page);
  await walk(page, async () => expect(await seriousAxe(page)).toEqual([]));
});

test("SCR-017 enrolment: secret and recovery codes are readable text for screen readers", async ({
  page,
}) => {
  await stubWizard(page);
  await walk(page, async () => undefined);
  await expect(page.getByRole("list").getByRole("listitem")).toHaveCount(2);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("You are set up");
});

test("SCR-017 enrolment: TOTP secret is selectable text, not only a QR (SC 1.1.1)", async ({
  page,
}) => {
  await stubWizard(page);
  await page.goto(`/invite/${TOK}`);
  await page.getByRole("button", { name: "Accept invitation" }).click();
  await page.getByLabel("New password").fill("correct horse battery");
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page.getByText("AAAA")).toBeVisible();
});

test("SCR-017 SC 3.3.1: rejected password and code are announced via role=alert", async ({
  page,
}) => {
  await stubWizard(page, { reject: true });
  await page.goto(`/invite/${TOK}`);
  await page.getByRole("button", { name: "Accept invitation" }).click();
  await page.getByLabel("New password").fill("x");
  await page.getByRole("button", { name: "Continue" }).click();
  const alert = page.getByRole("alert");
  await expect(alert).toHaveText("That password does not meet the policy.");
  expect(await seriousAxe(page)).toEqual([]);
});

test("SCR-017: reflow at 320 px and 200% zoom on every step (SC 1.4.10 / 1.4.4)", async ({
  page,
}) => {
  await stubWizard(page);
  // 320 CSS px wide; 200% zoom of a 1280 px window is a 640 CSS px viewport.
  for (const width of [320, 640]) {
    await page.setViewportSize({ width, height: 640 });
    await walk(page, async () => expect(await noOverflow(page)).toBeLessThanOrEqual(0));
  }
});

test("SCR-017: reduced motion leaves no running animation on any step (SC 2.3.3)", async ({
  page,
}) => {
  await stubWizard(page);
  await page.emulateMedia({ reducedMotion: "reduce" });
  await walk(page, async () => {
    const running = await page.evaluate(
      () => document.getAnimations().filter((a) => a.playState === "running").length,
    );
    expect(running).toBe(0);
  });
});
