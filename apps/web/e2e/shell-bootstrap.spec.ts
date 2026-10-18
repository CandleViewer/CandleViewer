import { test, expect } from "@playwright/test";

// E10-T04-B1 (#1725): the real app (main.tsx -> startShell) loads the session
// from /me, so an authenticated route renders instead of redirecting to /login.
// The API is stubbed at the network layer; the app code is not mocked.
const json = (body: unknown) => ({
  status: 200,
  contentType: "application/json",
  body: JSON.stringify(body),
});

test("authenticated session reaches /terminal without redirect to /login", async ({ page }) => {
  const calls: string[] = [];
  await page.route("**/api/v1/me", (r) => {
    calls.push("me");
    return r.fulfill(
      json({
        role: "owner",
        permissions: [],
        session: { environment: "demo", elevated_until: null },
      }),
    );
  });
  await page.route("**/api/v1/me/preferences", (r) => r.fulfill(json({})));
  await page.route("**/api/v1/me/keymap", (r) => r.fulfill(json({ bindings: [] })));
  await page.goto("/terminal");
  // R-100 `/terminal` redirects to the last-used layout (`12-sitemap.md` R-100).
  await expect(page).toHaveURL(/\/terminal\/last$/);
  expect(calls).toEqual(["me"]);
});

test("unauthenticated (/me 401) is redirected to /login", async ({ page }) => {
  await page.route("**/api/v1/me", (r) => r.fulfill({ status: 401, body: "{}" }));
  await page.route("**/api/v1/me/**", (r) => r.fulfill({ status: 401, body: "{}" }));
  await page.goto("/terminal");
  await expect(page).toHaveURL(/\/login/);
});

// E47-S06: theme switch + chart colour mode reach the document root that every
// surface (incl. the canvas theme object) keys off, after a real bootstrap.
test("stored theme and chart colour mode are applied to the root", async ({ page }) => {
  await page.addInitScript(() =>
    localStorage.setItem(
      "cv.chartColorMode",
      JSON.stringify({ palette: "cvd-safe", convention: "inverted" }),
    ),
  );
  await page.route("**/api/v1/me", (r) =>
    r.fulfill(
      json({
        role: "owner",
        permissions: [],
        session: { environment: "demo", elevated_until: null },
      }),
    ),
  );
  await page.route("**/api/v1/me/preferences", (r) =>
    r.fulfill(json({ appearance: { theme: "light" } })),
  );
  await page.route("**/api/v1/me/keymap", (r) => r.fulfill(json({ bindings: [] })));
  await page.goto("/terminal");
  const root = page.locator("html");
  await expect(root).toHaveAttribute("data-theme", "light");
  await expect(root).toHaveAttribute("data-palette", "cvd-safe");
  await expect(root).toHaveAttribute("data-convention", "inverted");
});

// #3139: the theme runtime of @candleviewer/ui is the only writer of the root attributes, and the token
// CSS and theme.css that the app imports (built into the page) follow them.
test("server appearance reaches the root through the runtime and the built CSS applies", async ({
  page,
}) => {
  await page.route("**/api/v1/me", (r) =>
    r.fulfill(
      json({
        role: "owner",
        permissions: [],
        session: { environment: "demo", elevated_until: null },
      }),
    ),
  );
  await page.route("**/api/v1/me/preferences", (r) =>
    r.fulfill(
      json({
        appearance: { theme: "light", density: "spacious", font_scale: 1.25, high_contrast: false },
        accessibility: { reduced_motion: "on" },
      }),
    ),
  );
  await page.route("**/api/v1/me/keymap", (r) => r.fulfill(json({ bindings: [] })));
  await page.goto("/terminal");
  const root = page.locator("html");
  await expect(root).toHaveAttribute("data-theme", "light");
  await expect(root).toHaveAttribute("data-density", "comfortable"); // "spacious" has no runtime density
  await expect(root).toHaveAttribute("data-text-scale", "125");
  await expect(root).toHaveAttribute("data-motion", "reduce");
  for (const retired of ["data-reduced-motion", "data-high-contrast", "data-contrast"]) {
    await expect(root).not.toHaveAttribute(retired, /.*/);
  }
  const computed = await page.evaluate(() => {
    const style = getComputedStyle(document.documentElement);
    return {
      border: style.getPropertyValue("--color-border-default").trim(),
      fontSize: style.fontSize,
      legacyScale: style.getPropertyValue("--cv-font-scale"),
    };
  });
  expect(computed.border).toBe("#D6DAE0"); // tokens.light.css, selected by data-theme
  expect(computed.fontSize).toBe("20px"); // theme.css: 125 % of the 16px default
  expect(computed.legacyScale).toBe("");
});
