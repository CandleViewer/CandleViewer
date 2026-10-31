// @vitest-environment jsdom
import { composeStories } from "@storybook/react-vite";
import { expect, userEvent, within } from "storybook/test";
import { describe, it } from "vitest";
import { Button, PageHeader } from "../src/components/index.js";
import * as stories from "../src/components/PageHeader.stories.js";
import { seriousViolations } from "./axe.js";
import { mount } from "./theme/mount.js";

const META = "All times UTC · as of 14:02:11";
const MARKER = "Viewing this log is recorded — Audit log viewed (admin.audit_read)";

const root = (host: HTMLElement): HTMLElement => {
  const el = host.querySelector<HTMLElement>('[data-cmp="CMP-088"]');
  if (el === null) throw new Error("no page header rendered");
  return el;
};

describe("PageHeader (CMP-088)", () => {
  it("renders the route's one h1 and nothing it was not given", async () => {
    const host = await mount(<PageHeader title="Settings" />);
    const headings = within(host).getAllByRole("heading");
    expect(headings).toHaveLength(1);
    expect(within(host).getByRole("heading", { level: 1, name: "Settings" })).toBe(headings[0]);
    expect(root(host).children).toHaveLength(1);
    expect(root(host).dataset["lines"]).toBe("1");
  });

  it("gives the h1 the host's id, the skip link's target, and no tab stop of its own", async () => {
    const host = await mount(<PageHeader title="Users" headingId="page-title" />);
    const h1 = within(host).getByRole("heading", { level: 1 });
    expect(h1.id).toBe("page-title");
    expect(h1).not.toHaveAttribute("tabindex");
  });

  it("puts the actions right after the h1, before the meta and the marker (DOM and Tab order)", async () => {
    const host = await mount(
      <PageHeader
        title="Audit log"
        actions={<Button variant="primary">Invite user</Button>}
        meta={META}
        marker={MARKER}
      />,
    );
    const order = [...root(host).children].map((el) => el.className);
    expect(order).toEqual([
      "cv-page-header__title",
      "cv-page-header__actions",
      "cv-page-header__meta",
      "cv-page-header__marker",
    ]);
    await userEvent.tab();
    expect(within(host).getByRole("button", { name: "Invite user" })).toHaveFocus();
  });

  it("keeps the meta and the marker plain text: no live region, status or alert", async () => {
    const host = await mount(<PageHeader title="Audit log" meta={META} marker={MARKER} />);
    for (const text of [META, MARKER]) {
      const line = within(host).getByText(text);
      expect(line.closest("[aria-live], [role]")).toBeNull();
    }
    expect(host.querySelector("[aria-live], [role='status'], [role='alert']")).toBeNull();
  });

  it("counts the text lines beside the actions for the CSS span: title, meta, marker", async () => {
    const meta = await mount(<PageHeader title="Users" meta={META} />);
    expect(root(meta).dataset["lines"]).toBe("2");
    const both = await mount(<PageHeader title="Users" meta={META} marker={MARKER} />);
    expect(root(both).dataset["lines"]).toBe("3");
    const marker = await mount(<PageHeader title="Users" marker={MARKER} />);
    expect(root(marker).dataset["lines"]).toBe("2");
  });

  it("renders the breadcrumb first; the admin form omits it (the band carries the route)", async () => {
    const crumb = (
      <nav aria-label="Breadcrumb">
        <ol>
          <li>Settings</li>
        </ol>
      </nav>
    );
    const host = await mount(<PageHeader title="Hotkeys" breadcrumb={crumb} />);
    expect(root(host).firstElementChild?.className).toBe("cv-page-header__breadcrumb");
    expect(within(host).getByRole("navigation", { name: "Breadcrumb" })).toBeVisible();
    const admin = await mount(<PageHeader title="Users" />);
    expect(within(admin).queryByRole("navigation")).toBeNull();
  });

  it.each([null, false, undefined])("a slot of %s counts as absent", async (empty) => {
    const host = await mount(
      <PageHeader title="Users" breadcrumb={empty} actions={empty} meta={empty} marker={empty} />,
    );
    expect(root(host).children).toHaveLength(1);
    expect(root(host).dataset["lines"]).toBe("1");
  });

  it("has no serious or critical axe violation with every slot filled", async () => {
    const host = await mount(
      <PageHeader
        title="Users"
        breadcrumb={
          <nav aria-label="Breadcrumb">
            <ol>
              <li>
                <a href="#admin">Admin</a>
              </li>
            </ol>
          </nav>
        }
        actions={<Button variant="primary">Invite user</Button>}
        meta={META}
        marker={MARKER}
      />,
    );
    expect(await seriousViolations(host)).toEqual([]);
  });
});

describe("PageHeader stories", () => {
  it.each(Object.entries(composeStories(stories)))(
    "%s renders exactly one h1",
    async (_name, Story) => {
      const host = await mount(<Story />);
      expect(within(host).getAllByRole("heading", { level: 1 })).toHaveLength(1);
    },
  );

  // The storybook project runs each play in Chromium; here in jsdom too, but for LongText, whose play measures
  // the wrapped layout jsdom does not compute.
  it("runs each story's play function but LongText's", { timeout: 20_000 }, async () => {
    for (const [name, Story] of Object.entries(composeStories(stories))) {
      if (name === "LongText") continue;
      const canvasElement = document.body.appendChild(document.createElement("div"));
      await expect(Story.run({ canvasElement }), name).resolves.toBeUndefined();
    }
  });
});
