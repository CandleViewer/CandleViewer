import { type Page } from "@playwright/test";
import { expect, packTest as test } from "../ga/fixtures";
import { json, stubSession, watchForLeaks } from "../support/api";

// E09-Q02 (#293) denied.spec. SCR-154 is the permission-denied state; the shipped renderers are
// R-900 /403 (ForbiddenState) and /admin/** -> 404 for non-owners. Server-side denial (E09-TC-E06/E07)
// is owned by E09-Q03 (contract-level).

test("E09-TC-E06 viewer deep link to /admin/users shows not-found with no admin data @ga-regression @ga-area-admin", async ({
  page,
}) => {
  const adminCalls: string[] = [];
  await stubSession(page, { role: "viewer" });
  await page.route("**/api/v1/admin/**", (r) => {
    adminCalls.push(r.request().url());
    return r.fulfill(json({ users: [{ email: "secret@example.test" }] }));
  });
  await page.goto("/admin/users");
  await expect(page.getByRole("heading", { name: "Not found" })).toBeVisible();
  await expect(page.getByText("secret@example.test")).toHaveCount(0);
  expect(adminCalls).toEqual([]);
});

test("E09-TC-E06 owner-only risk route returns the forbidden state to a viewer @ga-regression @ga-area-admin", async ({
  page,
}) => {
  await stubSession(page, { role: "viewer" });
  await page.goto("/risk");
  await expect(
    page.getByRole("heading", { level: 1, name: "You don't have access to this" }),
  ).toBeVisible();
  await expect(page.getByRole("link", { name: "Back to your workspace" })).toBeVisible();
});

test("E09-TC-E07 denied page is identical for any account id (no enumeration) @ga-regression @ga-area-admin", async ({
  page,
}) => {
  await stubSession(page, { role: "viewer" });
  const texts: string[] = [];
  for (const id of ["acct-x", "acct-does-not-exist"]) {
    await page.goto(`/admin/accounts/${id}`);
    await expect(page.getByRole("heading", { name: "Not found" })).toBeVisible();
    texts.push(await page.getByRole("heading", { level: 1 }).innerText());
  }
  expect(texts[0]).toBe(texts[1]);
});

// ---- The network side of a denial: the SPA is not the control (the server is, E09-Q03), but a denied route must
// not even ask for the data it guards, and nothing of it may reach the page. Each such test first proves its
// watcher can see: the bootstrap read of `/api/v1/me` is among the calls, so an empty list is not a blind one.
const SECRET = "secret@example.test";
/** The `/api/v1/` families behind the denied routes below. */
const GUARDED = /^\/api\/v1\/(admin|users|accounts|risk)(\/|$)/u;
/** A denied route and the heading of its denial: not found under `/admin`, forbidden for an owner-only screen. */
const DENIED: readonly (readonly [string, string])[] = [
  ["/admin/users", "Not found"],
  ["/admin/accounts/acct-x", "Not found"],
  ["/risk", "You don't have access to this"],
];

/** The `/api/v1/` calls the page makes from now on, as `path?query`. */
function watchApi(page: Page): () => string[] {
  const calls: string[] = [];
  page.on("request", (request) => {
    const { pathname, search } = new URL(request.url());
    if (pathname.startsWith("/api/v1/")) calls.push(pathname + search);
  });
  return () => calls;
}

/** The shell's own reads after its first paint (`SessionLockHost`, `PreferencesProvider`), stubbed by `stubSession`. */
const SHELL_READS = ["/api/v1/auth/session", "/api/v1/settings"];

// Each deep link gets a page of its own: the shell's liveness probe (every 2 s) may start after a flush, and a
// navigation of the same page would drop it before its body is read, or leave it unsettled, which the guard fails.
test("E09-TC-E06 a viewer's deep link to a denied route fetches none of the data it guards, and no such body reaches the page @ga-regression @ga-area-admin", async ({
  context,
}) => {
  for (const [path, heading] of DENIED) {
    const page = await context.newPage();
    await stubSession(page, { role: "viewer" });
    // were the SPA to ask, this is what a server that forgot the check would answer
    await page.route(
      (url) => GUARDED.test(url.pathname),
      (r) => r.fulfill(json({ items: [{ email: SECRET }] })),
    );
    const guard = watchForLeaks(page, [SECRET]);
    const calls = watchApi(page);
    await page.goto(path);
    await expect(page.getByRole("heading", { level: 1, name: heading })).toBeVisible();
    // the shell reads these after its heading: once it has asked, the flush waits for their bodies and checks them
    await expect.poll(calls).toEqual(expect.arrayContaining(SHELL_READS));
    expect(calls()).toContain("/api/v1/me"); // positive control: the watcher sees the SPA's own reads
    await expect(page.getByText(SECRET)).toHaveCount(0);
    await guard.flush();
    await page.close();
    // after the close, so no guarded call the page started can fall between this check and it
    expect(calls().filter((call) => GUARDED.test(call.split("?")[0] ?? ""))).toEqual([]);
  }
});

test("E09-TC-E07 the denied page makes no call that names the account id it was asked for @ga-regression @ga-area-admin", async ({
  page,
}) => {
  await stubSession(page, { role: "viewer" });
  const calls = watchApi(page);
  const ids = ["acct-x", "acct-does-not-exist"];
  for (const id of ids) {
    await page.goto(`/admin/accounts/${id}`);
    await expect(page.getByRole("heading", { level: 1, name: "Not found" })).toBeVisible();
  }
  expect(calls()).toContain("/api/v1/me"); // positive control: the watcher sees the SPA's own reads
  expect(calls().filter((call) => ids.some((id) => call.includes(id)))).toEqual([]);
});
