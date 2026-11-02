// @vitest-environment jsdom
import { composeStories } from "@storybook/react-vite";
import { act, StrictMode, useState, type JSX } from "react";
import { createRoot } from "react-dom/client";
import { expect, userEvent, within } from "storybook/test";
import { afterEach, beforeEach, describe, it, vi } from "vitest";
import { ADMIN_COPY, AdminLayout, sortAdminStrip } from "../src/index.js";
import type { AdminLayoutProps, AdminStripItem, LinkRouteProps } from "../src/index.js";
import * as stories from "../src/components/AdminLayout.stories.js";
import { tabbables } from "../src/components/internal/tabbable.js";
import { seriousViolations } from "./axe.js";
import { mount } from "./theme/mount.js";

const T0 = Date.UTC(2026, 9, 22, 14, 2, 11);
/** OV-3's five items and the precedence set, as the stories carry them. */
const OV3 = stories.StripWithItems.args?.strip ?? [];
const PRECEDENCE = stories.StripPrecedence.args?.strip ?? [];
const GRACE = { classLabel: "user changes", expiresAt: T0 + 134_000 };
/** A grace still live on the real clock, for the tests without fake timers. */
const liveGrace = () => ({ classLabel: "user changes", expiresAt: Date.now() + 134_000 });
/** Every node that could speak: a live region of any politeness, or a live role. */
const LIVE = '[aria-live]:not([aria-live="off"]), [role="status"], [role="alert"], [role="log"]';

const layout = (props: Partial<AdminLayoutProps> = {}, children: JSX.Element = <p>Page</p>) =>
  mount(
    <AdminLayout routeLabel="Users" {...props}>
      {children}
    </AdminLayout>,
  );
const item = (id: string, more: Partial<AdminStripItem> = {}): AdminStripItem => ({
  id,
  label: `Item ${id}`,
  href: `/admin/${id}`,
  kind: "other",
  severity: "warning",
  ...more,
});
const band = (host: HTMLElement): HTMLElement =>
  within(host).getByRole("region", { name: "Admin area" });
const strip = (host: HTMLElement): HTMLElement =>
  within(host).getByRole("region", { name: "Needs your action" });
const links = (host: HTMLElement): HTMLElement[] => within(strip(host)).getAllByRole("link");
const root = (host: HTMLElement): Element => host.querySelector('[data-cmp="CMP-087"]') ?? host;
/** A strip badge's environment, read from its class modifier (`cv-adminlayout__env--live`). */
const envModifier = (badge: Element): string =>
  [...badge.classList].filter((name) => name.startsWith("cv-adminlayout__env--")).join(" ");

describe("AdminLayout (CMP-087)", () => {
  it("leads with the band: a region named Admin area reading ◆ Admin area · {route}", async () => {
    const host = await layout();
    expect(root(host).firstElementChild).toBe(band(host));
    expect(band(host)).toHaveTextContent(/^◆ Admin area · Users$/);
    expect(within(band(host)).getByText("◆")).toHaveAttribute("aria-hidden", "true");
    expect(host.querySelectorAll('[data-cmp="CMP-087"]')).toHaveLength(1);
    expect(root(host)).toHaveAttribute("data-density", "comfortable");
  });

  it("keeps the band, grace line included, out of the Tab order; renders no h1 and no main", async () => {
    const host = await layout({ strip: OV3, grace: liveGrace(), footer: "Footer line" });
    expect(band(host)).toHaveTextContent("Still trusted for user changes");
    expect(band(host)).not.toHaveAttribute("tabindex");
    expect(tabbables(band(host))).toEqual([]);
    expect(within(host).queryByRole("heading")).toBeNull();
    expect(host.querySelector("h1, main")).toBeNull();
  });

  it("lists the strip under its title in the order rule's order, never live", async () => {
    const host = await layout({ strip: OV3 });
    expect(strip(host)).toHaveTextContent(/^Needs your action \(5\)/);
    expect(within(strip(host)).getAllByRole("listitem")).toHaveLength(5);
    expect(strip(host).querySelectorAll(LIVE)).toHaveLength(0);
    const [first, , third, , last] = links(host);
    expect(first).toHaveAccessibleName(
      "Attention: 1 key expires within 30 days → Accounts and keys LIVE",
    );
    expect(third).toHaveAccessibleName("Attention: 1 active user without two-factor → Users");
    expect(third).toHaveAttribute("href", "/admin/users");
    expect(last).toHaveAccessibleName("Attention: clock drift 2.3 s — order entry halted → Health");
    const badges = [...strip(host).querySelectorAll<HTMLElement>(".cv-adminlayout__env")];
    expect(badges.map((badge) => `${badge.textContent?.trim()} ${envModifier(badge)}`)).toEqual([
      ...["LIVE cv-adminlayout__env--live", "LIVE cv-adminlayout__env--live"],
    ]);
  });

  it("names critical and warning items with Attention once, info items without", async () => {
    const host = await layout({ strip: PRECEDENCE });
    const [, breakGlass, tamper, , info] = links(host);
    expect(breakGlass).toHaveAccessibleName(
      "Attention: break-glass recovery was used — review it → Incidents",
    );
    expect(tamper).toHaveAccessibleName("Attention: Tamper check FAILED → Open audit log");
    expect(info).toHaveAccessibleName("Last backup 3 days ago → Backups");
    const tones = within(strip(host))
      .getAllByRole("listitem")
      .map((li) => li.dataset["severity"]);
    expect(tones).toEqual(["critical", "critical", "critical", "warning", "info"]);
  });

  it("reads Nothing needs your action on one line when empty, and draws no strip unread", async () => {
    const empty = await layout({ strip: [] });
    expect(strip(empty)).toHaveTextContent(/^Nothing needs your action$/);
    expect(within(strip(empty)).queryByRole("list")).toBeNull();
    const unread = await layout();
    expect(within(unread).queryByRole("region", { name: "Needs your action" })).toBeNull();
  });

  it("links through the host's router link with `to` when it passes one", async () => {
    function RouterLink({ to, children, ...rest }: LinkRouteProps): JSX.Element {
      return (
        <a {...rest} href={`#route${to}`}>
          {children}
        </a>
      );
    }
    const items = [item("users", { env: "demo" }), item("tn", { env: "testnet" })];
    const host = await layout({ strip: items, linkAs: RouterLink });
    const [demo, testnet] = links(host);
    expect(demo).toHaveAttribute("href", "#route/admin/users");
    expect(demo).toHaveAttribute("data-cmp", "CMP-021");
    expect(demo).toHaveAccessibleName("Attention: Item users DEMO");
    expect(testnet?.querySelector(".cv-adminlayout__env--testnet")).toHaveTextContent("TESTNET");
  });

  it("badges an item's environment with a class modifier, never a data attribute", async () => {
    // The top bar's badge owns the attribute: its guard rejects any shipped selector that names it.
    const items = [
      item("live", { env: "live" }),
      item("demo", { env: "demo" }),
      item("tn", { env: "testnet" }),
      item("bare"),
    ];
    const host = await layout({ strip: items });
    const badges = [...strip(host).querySelectorAll<HTMLElement>(".cv-adminlayout__env")];
    expect(badges.map((badge) => [badge.textContent?.trim(), badge.className])).toEqual([
      ["LIVE", "cv-adminlayout__env cv-adminlayout__env--live"],
      ["DEMO", "cv-adminlayout__env cv-adminlayout__env--demo"],
      ["TESTNET", "cv-adminlayout__env cv-adminlayout__env--testnet"],
    ]);
    for (const badge of badges) expect(badge.getAttributeNames()).toEqual(["class"]);
    expect(host.querySelector("[data-env], [data-environment]")).toBeNull();
    // The words and names are the ones the attribute read: the badge is no role, no label.
    const [live, demo, testnet, bare] = links(host);
    expect(live).toHaveAccessibleName("Attention: Item live LIVE");
    expect(demo).toHaveAccessibleName("Attention: Item demo DEMO");
    expect(testnet).toHaveAccessibleName("Attention: Item tn TESTNET");
    expect(bare).toHaveAccessibleName("Attention: Item bare");
    expect(bare?.querySelector(".cv-adminlayout__env")).toBeNull();
  });

  it("takes the session's environment id, as CMP-178 does, and reads its word in capitals", async () => {
    // CR-5287-04: one value feeds both components, the shell's `environment` ("live"), never a word.
    expect(ADMIN_COPY.env).toEqual({ live: "LIVE", demo: "DEMO", testnet: "TESTNET" });
    const host = await layout({ strip: [item("keys", { env: "live" })] });
    const [keys] = links(host);
    expect(keys).toHaveAccessibleName("Attention: Item keys LIVE");
    expect(keys?.querySelector(".cv-adminlayout__env")).toHaveClass("cv-adminlayout__env--live");
  });

  it("renders the band, the strip, the children, then the footer, and no empty footer", async () => {
    const host = await layout({ strip: [], footer: ADMIN_COPY.footerAreaEntered });
    const [first, second, third, fourth, ...rest] = [...root(host).children];
    expect([first, second, rest]).toEqual([band(host), strip(host), []]);
    expect(third).toHaveTextContent("Page");
    expect(fourth).toHaveTextContent(
      /^Entering this area was recorded — Area entered \(admin\.area_entered\)$/,
    );
    expect((await layout()).querySelector(".cv-adminlayout__footer")).toBeNull();
  });

  it("tabs through the strip's links in order, then the children", async () => {
    const host = await layout({ strip: OV3 }, <button type="button">Invite user</button>);
    for (const stop of [...links(host), within(host).getByRole("button")]) {
      await userEvent.tab();
      expect(document.activeElement).toBe(stop);
    }
  });

  it("gives a removed pill's focus to the next pill, the strip's line, then the page's h1", async () => {
    const host = document.body.appendChild(document.createElement("div"));
    const root = createRoot(host);
    const render = (items?: readonly AdminStripItem[]): Promise<void> =>
      act(async () =>
        root.render(
          <AdminLayout routeLabel="Overview" strip={items}>
            <h1>Overview</h1>
          </AdminLayout>,
        ),
      );
    const [a, b, c] = [item("a"), item("b"), item("c")] as const;
    await render([a, b, c]);
    act(() => links(host)[1]?.focus());
    // A-5330-02: b's condition cleared, so focus goes to the pill after it, then before the last.
    await render([a, c]);
    expect(document.activeElement).toBe(links(host)[1]);
    expect(document.activeElement).toHaveAccessibleName("Attention: Item c");
    await render([a]);
    expect(document.activeElement).toHaveAccessibleName("Attention: Item a");
    // No pill left: the strip's one line, lent a tabindex for the move only.
    await render([]);
    const none = within(strip(host)).getByText(ADMIN_COPY.stripNone);
    expect(document.activeElement).toBe(none);
    expect(none).toHaveAttribute("tabindex", "-1");
    // No strip at all: the page's h1, the same way.
    await render(undefined);
    const h1 = within(host).getByRole("heading", { level: 1 });
    expect(document.activeElement).toBe(h1);
    act(() => h1.blur());
    expect(h1).not.toHaveAttribute("tabindex");
    // Focus moved elsewhere on purpose is never taken back.
    await render([a, b, c]);
    const outside = document.body.appendChild(document.createElement("button"));
    act(() => links(host)[0]?.focus());
    act(() => outside.focus());
    await render([b]);
    expect(document.activeElement).toBe(outside);
    await act(async () => root.unmount());
  });

  it("has no serious or critical axe violation, empty or with items and a grace", async () => {
    expect(await seriousViolations(await layout({ strip: [] }))).toEqual([]);
    const full = await layout({ strip: PRECEDENCE, grace: liveGrace(), footer: "Footer line" });
    expect(await seriousViolations(full)).toEqual([]);
  });

  it.each(Object.entries(composeStories(stories)))("story %s renders", async (_name, Story) => {
    const host = await mount(<Story />);
    expect(host.querySelector('[data-cmp="CMP-087"]')).not.toBeNull();
  });
});

describe("sortAdminStrip (E42-D03 §4, D02:118)", () => {
  it("puts withdrawal, break-glass, tamper and locked first, then severity, then recency", () => {
    const sorted = sortAdminStrip([
      item("info", { severity: "info", at: T0 }),
      item("warn-old", { at: T0 - 60_000 }),
      item("tamper", { kind: "tamper", severity: "critical", at: T0 - 1 }),
      item("crit", { severity: "critical", at: T0 - 120_000 }),
      item("locked", { kind: "locked", severity: "critical", at: T0 }),
      item("break-glass", { kind: "break_glass", severity: "critical", at: T0 - 2 }),
      item("warn-new", { at: T0 - 1_000 }),
      item("withdrawal", { kind: "withdrawal", severity: "critical", at: T0 - 999_999 }),
    ]);
    expect(sorted.map(({ id }) => id)).toEqual([
      ...["withdrawal", "break-glass", "tamper", "locked"],
      ...["crit", "warn-new", "warn-old", "info"],
    ]);
  });

  it("is stable, puts an untimed item after the timed ones and leaves the input alone", () => {
    const input = [item("a"), item("b", { at: T0 }), item("c"), item("d", { at: T0 })];
    expect(sortAdminStrip(input).map(({ id }) => id)).toEqual(["b", "d", "a", "c"]);
    expect(input.map(({ id }) => id)).toEqual(["a", "b", "c", "d"]);
  });
});

describe("AdminLayout grace line (SH-5, variant b)", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(T0);
  });
  afterEach(() => {
    vi.useRealTimers();
  });
  const advance = (ms: number): Promise<void> => act(async () => void vi.advanceTimersByTime(ms));
  const digits = (host: HTMLElement): string =>
    band(host).querySelector(".cv-countdown__digits")?.textContent ?? "";

  it("reads Still trusted for user changes · 2:14 at the band's end, on the server's clock", async () => {
    const host = await layout({ grace: GRACE });
    expect(band(host).lastElementChild).toHaveTextContent(/^Still trusted for user changes · 2:14/);
    expect(band(host).querySelector('[data-cmp="CMP-035"]')).toHaveAttribute(
      "data-format",
      "mm:ss",
    );
    // The server runs 4 s ahead of this client: the deadline is counted on its clock, never locally.
    const ahead = await layout({
      grace: { ...GRACE, expiresAt: T0 + 138_000 },
      now: () => T0 + 4_000,
    });
    expect(digits(ahead)).toBe("2:14");
  });

  it("is the only live node, ticks each second and speaks once at 60 s and once at 10 s", async () => {
    const host = await layout({ grace: GRACE, strip: OV3, footer: "Footer line" });
    const live = [...root(host).querySelectorAll(LIVE)];
    expect(live).toEqual([within(band(host)).getByRole("status")]);
    expect(live[0]).toHaveAttribute("aria-live", "polite");
    const said: string[] = [];
    for (let left = 134; left > 1; left -= 1) {
      await advance(1_000);
      const text = live[0]?.textContent ?? "";
      if (text !== (said[said.length - 1] ?? "")) said.push(text);
    }
    expect(digits(host)).toBe("0:01");
    // Each names what runs out, as §14's `announce.admin_1min` does; never a bare "1 minute left".
    expect(said).toEqual([
      "Trust for user changes expires in 1 minute.",
      "Trust for user changes expires in 10 seconds.",
    ]);
    // The line itself reads as it did: the words and the digits, the spoken twins hidden.
    const line = band(host).lastElementChild?.cloneNode(true) as Element;
    line.querySelectorAll(".cv-visually-hidden").forEach((node) => node.remove());
    expect(line.textContent).toBe("Still trusted for user changes · 0:01");
  });

  it("goes at 0: onGraceExpire fires once and focus stays where it was", async () => {
    const onGraceExpire = vi.fn();
    const host = await layout({ grace: GRACE, onGraceExpire }, <button type="button">Save</button>);
    const save = within(host).getByRole("button", { name: "Save" });
    act(() => save.focus());
    await advance(133_000);
    expect(onGraceExpire).not.toHaveBeenCalled();
    await advance(1_000);
    expect(band(host)).toHaveTextContent(/^◆ Admin area · Users$/);
    expect(onGraceExpire).toHaveBeenCalledTimes(1);
    expect(document.activeElement).toBe(save);
    await advance(10_000);
    expect(onGraceExpire).toHaveBeenCalledTimes(1);
  });

  it("shows no line for a grace already over at mount, firing once under StrictMode", async () => {
    const onGraceExpire = vi.fn();
    const grace = { ...GRACE, expiresAt: T0 - 1_000 };
    const host = await mount(
      <StrictMode>
        <AdminLayout routeLabel="Users" grace={grace} onGraceExpire={onGraceExpire}>
          <p>Page</p>
        </AdminLayout>
      </StrictMode>,
    );
    expect(band(host)).not.toHaveTextContent("Still trusted");
    expect(onGraceExpire).toHaveBeenCalledTimes(1);
  });

  it("brings the line back for a new deadline after one went", async () => {
    function Host(): JSX.Element {
      const [expiresAt, setExpiresAt] = useState(T0 + 2_000);
      return (
        <AdminLayout routeLabel="Risk policy" grace={{ classLabel: "risk limits", expiresAt }}>
          <button type="button" onClick={() => setExpiresAt(Date.now() + 61_000)}>
            Step up again
          </button>
        </AdminLayout>
      );
    }
    const host = await mount(<Host />);
    await advance(2_000);
    expect(band(host)).not.toHaveTextContent("Still trusted");
    await act(async () => within(host).getByRole("button").click());
    expect(band(host)).toHaveTextContent("Still trusted for risk limits · 1:01");
  });
});
