// @vitest-environment jsdom
import { composeStories } from "@storybook/react-vite";
import type { JSX } from "react";
import { expect, within } from "storybook/test";
import { describe, it } from "vitest";
import {
  AUDIT_ACTION_LABELS,
  AuditRow,
  AuditRowList,
  type AuditRowProps,
  type LinkRouteProps,
} from "../src/components/index.js";
import { formatAuditTime } from "../src/components/AuditRow.js";
import * as stories from "../src/components/AuditRow.stories.js";
import { seriousViolations } from "./axe.js";
import { mount } from "./theme/mount.js";

type Entry = AuditRowProps["entry"];

/** E42-D03's worked example: Owner basiltt's read of the overview, every field an Owner sees filled. */
const base: Entry = {
  id: 1204120,
  ts: "2026-10-22T14:02:11.204816+00:00",
  actor_user_id: "9f1c2b4e-0a1d-4f2b-9e3a-11c0ffee0001",
  actor_username: "basiltt",
  action: "admin.area_entered",
  subject_type: "admin_route",
  subject_id: "/admin/overview",
  subject_label: null,
  outcome: "success",
  severity: "info",
  reason: null,
  environment: "live",
  ip: "100.84.12.9",
  session_id: "5e000000-0000-4000-8000-000000000001",
  user_agent: "Mozilla/5.0 (X11; Linux x86_64)",
  request_id: "0193f2bb-9c11-7a3d-88f1-0d2e3f4a5b6c",
  detail: { before: null, after: { route: "/admin/overview", reauth_age_s: 412 } },
  entry_hash: "3c9a5e2f1b",
  prev_hash: "7d1e0b44aa",
};

const HEAD = "2026-10-22 14:02:11 UTC · basiltt · Area entered (admin.area_entered)";
const NAME = `${HEAD} · /admin/overview · Success · Info`;

const rowOf = async (entry: Entry, props: Partial<AuditRowProps> = {}): Promise<HTMLElement> =>
  mount(
    <AuditRowList aria-label="Latest audit entries">
      <AuditRow entry={entry} variant="compact" href={`#audit-${entry.id}`} {...props} />
    </AuditRowList>,
  );

const link = (host: HTMLElement): HTMLElement => within(host).getByRole("link");

describe("AuditRow (CMP-173), compact", () => {
  it("is one list item in a named list, holding one link to SCR-136 read in words", async () => {
    const host = await rowOf(base);
    const list = within(host).getByRole("list", { name: "Latest audit entries" });
    const item = within(list).getByRole("listitem");
    expect(item.dataset).toMatchObject({ cmp: "CMP-173", variant: "compact", severity: "info" });
    expect(within(item).getAllByRole("link")).toHaveLength(1);
    expect(link(host)).toHaveAttribute("href", "#audit-1204120");
    expect(link(host)).toHaveAccessibleName(NAME);
    // HTML's `datetime` takes three fraction digits at most: the instant to the millisecond.
    expect(host.querySelector("time")).toHaveAttribute("datetime", "2026-10-22T14:02:11.204Z");
  });

  it("shows a time that is not a full date-time as served, in plain text with no `datetime`", async () => {
    const host = await rowOf({ ...base, ts: "2026-10-22T14:02:11" });
    expect(host.querySelector("time")).toBeNull();
    expect(link(host)).toHaveAccessibleName(/^2026-10-22T14:02:11 · basiltt · /);
  });

  it("never shows the IP, a hash, the session, the agent, the env or the detail", async () => {
    const text = link(await rowOf(base)).textContent ?? "";
    for (const hidden of ["100.84", "3c9a", "7d1e", "5e00", "Mozilla", "0193", "412", "live"]) {
      expect(text).not.toContain(hidden);
    }
    const elided = await rowOf({
      ...base,
      detail: { before: null, after: null, elided: ["after"] },
    });
    expect(link(elided)).toHaveAccessibleName(NAME);
    const projected = await rowOf({ ...base, detail: {}, ip: null, entry_hash: null });
    expect(link(projected)).toHaveAccessibleName(NAME);
  });

  it.each<[string, Partial<Entry>, string]>([
    ["success", {}, "Success"],
    ["failure", { outcome: "failure" }, "Failure"],
    ["denied", { outcome: "denied" }, "Denied"],
    ["write-ahead (reason started)", { reason: "started" }, "Started"],
    ["intent (phase intent)", { detail: { after: { value: true, phase: "intent" } } }, "Intent"],
    ["unlisted", { outcome: "partial" as Entry["outcome"] }, "partial"],
  ])("outcome %s reads %s, never Success for a write-ahead record", async (_, fields, word) => {
    const host = await rowOf({ ...base, ...fields });
    expect(link(host)).toHaveAccessibleName(`${HEAD} · /admin/overview · ${word} · Info`);
  });

  it.each([
    ["critical", "Critical", "danger"],
    ["error", "Error", "danger"],
    ["warning", "Warning", "warning"],
    ["info", "Info", undefined],
    ["debug", "Debug", undefined],
    ["notice", "notice", undefined],
  ] as const)("severity %s reads %s, the %s glyph hidden", async (severity, word, glyph) => {
    const host = await rowOf({ ...base, severity: severity as Entry["severity"] });
    expect(link(host)).toHaveAccessibleName(`${HEAD} · /admin/overview · Success · ${word}`);
    const mark = host.querySelector<HTMLElement>(".cv-audit-row__glyph");
    expect(mark?.dataset["glyph"]).toBe(glyph);
    if (mark !== null) expect(mark.querySelector("svg")).toHaveAttribute("aria-hidden", "true");
    expect(within(host).getByRole("listitem").dataset["severity"]).toBe(severity);
  });

  it("labels a known action and keeps its code; any other code reads as itself", async () => {
    expect(AUDIT_ACTION_LABELS["admin.area_entered"]).toBe("Area entered");
    const unknown = await rowOf({ ...base, action: "rbac.denied" });
    expect(link(unknown)).toHaveAccessibleName(/ · basiltt · rbac\.denied · /);
    const inherited = await rowOf({ ...base, action: "constructor" });
    expect(link(inherited)).toHaveAccessibleName(/ · basiltt · constructor · /);
    const own = await rowOf(base, { actionLabels: { "admin.area_entered": "Entered admin" } });
    expect(link(own)).toHaveAccessibleName(/ · Entered admin \(admin\.area_entered\) · /);
  });

  it("reads the recorded actor, a system one too, and a dash when none was recorded", async () => {
    const system = await rowOf({ ...base, actor_user_id: null, actor_username: "system:backups" });
    expect(link(system)).toHaveAccessibleName(/^[^·]+ · system:backups · /);
    const unrecorded: Entry = { ...base };
    delete unrecorded.actor_username;
    for (const entry of [{ ...base, actor_username: null }, unrecorded]) {
      expect(link(await rowOf(entry))).toHaveAccessibleName(/^[^·]+ · — · /);
    }
  });

  it("reads the subject label, else the subject id, else leaves the subject out", async () => {
    const labelled = await rowOf({ ...base, subject_label: "BTCUSDT" });
    expect(link(labelled)).toHaveAccessibleName(`${HEAD} · BTCUSDT · Success · Info`);
    const none = await rowOf({ ...base, subject_id: null });
    expect(link(none)).toHaveAccessibleName(`${HEAD} · Success · Info`);
    expect(none.querySelectorAll(".cv-audit-row__sep")).toHaveLength(4);
  });

  it("is one tab stop with CMP-039's ring, plain-text dots and no live region", async () => {
    const host = await rowOf(base);
    expect(host.querySelectorAll("a[href], button, [tabindex]")).toHaveLength(1);
    expect(link(host)).toHaveClass("cv-focus-ring", "cv-audit-row__link");
    const dots = [...host.querySelectorAll(".cv-audit-row__sep")];
    expect(dots.map((dot) => dot.textContent)).toEqual(["·", "·", "·", "·", "·"]);
    expect(host.querySelector("[aria-hidden]:not(svg), [aria-live], [role]")).toBeNull();
  });

  it("hands the route to the app's router link (CMP-021's `as`), which renders the anchor", async () => {
    const seen: string[] = [];
    function RouterLink({ to, children, ...rest }: LinkRouteProps): JSX.Element {
      seen.push(to);
      return (
        <a {...rest} href={to} data-router="">
          {children}
        </a>
      );
    }
    const host = await rowOf(base, { linkAs: RouterLink, href: "/admin/audit?entry=1204120" });
    expect(seen).toContain("/admin/audit?entry=1204120");
    expect(link(host)).toHaveAttribute("data-router");
    expect(link(host)).toHaveClass("cv-focus-ring", "cv-audit-row__link");
    expect(link(host)).toHaveAccessibleName(NAME);
  });

  it("has no serious or critical axe violation in a list of rows", async () => {
    const host = await mount(
      <AuditRowList aria-label="Latest audit entries">
        <AuditRow entry={base} variant="compact" href="#a" />
        <AuditRow entry={{ ...base, id: 2, severity: "critical" }} variant="compact" href="#b" />
        <AuditRow entry={{ ...base, id: 3, severity: "warning" }} variant="compact" href="#c" />
      </AuditRowList>,
    );
    expect(await seriousViolations(host)).toEqual([]);
  });
});

describe("formatAuditTime", () => {
  it.each([
    ["2026-10-22T14:02:11.204816+00:00", "2026-10-22 14:02:11 UTC"],
    ["2026-09-14T10:33:00.114Z", "2026-09-14 10:33:00 UTC"],
    ["2026-10-22T14:02:11Z", "2026-10-22 14:02:11 UTC"],
    ["2026-10-22T14:02:11.5Z", "2026-10-22 14:02:11 UTC"],
    ["2026-10-22T16:02:11.000001+02:00", "2026-10-22 14:02:11 UTC"],
    ["2026-10-22T23:30:00-01:00", "2026-10-23 00:30:00 UTC"],
    // No zone, no date-time or no such date: shown as served, never guessed.
    ["2026-10-22T14:02:11", "2026-10-22T14:02:11"],
    ["2026-10-22 14:02:11Z", "2026-10-22 14:02:11Z"],
    ["2026-13-40T14:02:11Z", "2026-13-40T14:02:11Z"],
    ["yesterday", "yesterday"],
  ])("%s reads %s", (ts, text) => {
    expect(formatAuditTime(ts)).toBe(text);
  });
});

describe("AuditRow stories", () => {
  it.each(Object.entries(composeStories(stories)))("%s renders its rows", async (_name, Story) => {
    const host = await mount(<Story />);
    const rows = host.querySelectorAll('[data-cmp="CMP-173"]');
    expect(rows.length).toBeGreaterThan(0);
    expect(within(host).getAllByRole("link")).toHaveLength(rows.length);
  });

  // The storybook project runs each play in Chromium; here in jsdom too, so a wrong name fails without a browser.
  it("runs each story's play function", { timeout: 20_000 }, async () => {
    for (const [name, Story] of Object.entries(composeStories(stories))) {
      const canvasElement = document.body.appendChild(document.createElement("div"));
      await expect(Story.run({ canvasElement }), name).resolves.toBeUndefined();
    }
  });
});
