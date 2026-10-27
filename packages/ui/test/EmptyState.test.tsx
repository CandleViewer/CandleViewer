// @vitest-environment jsdom
import { composeStories } from "@storybook/react-vite";
import { expect, fn, userEvent, within } from "storybook/test";
import { describe, it } from "vitest";
import { EmptyState, ProgressBar, type EmptyStateVariant } from "../src/components/index.js";
import { Icon } from "../src/icons/Icon.js";
import * as stories from "../src/components/EmptyState.stories.js";
import { mount } from "./theme/mount.js";

const glyphOf = async (name: Parameters<typeof Icon>[0]["name"]): Promise<string | undefined> =>
  (await mount(<Icon name={name} size="lg" />)).querySelector("svg")?.outerHTML;

describe("EmptyState (CMP-026)", () => {
  it("renders the title as an h3, the description and a primary CTA (Empty and error states are first-class)", async () => {
    const onClick = fn();
    const host = await mount(
      <EmptyState
        title="No rules yet"
        description="Start from a template."
        cta={{ label: "Browse templates", onClick }}
      />,
    );
    const el = host.querySelector<HTMLElement>(".cv-empty-state");
    expect(el?.dataset["cmp"]).toBe("CMP-026");
    expect(el?.dataset["variant"]).toBe("no-data");
    expect(within(host).getByRole("heading", { level: 3, name: "No rules yet" })).toBeTruthy();
    expect(within(host).getByText("Start from a template.")).toBeTruthy();
    const cta = within(host).getByRole("button", { name: "Browse templates" });
    expect(cta.dataset["cmp"]).toBe("CMP-001");
    expect(cta.dataset["variant"]).toBe("primary");
    await userEvent.tab();
    expect(cta).toHaveFocus();
    await userEvent.keyboard("{Enter}");
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it("is static: no live region, never announced", async () => {
    const host = await mount(<EmptyState title="No rows match" variant="filtered-empty" />);
    expect(host.querySelector("[aria-live], [role]")).toBeNull();
  });

  it("headingLevel sets the outline", async () => {
    const host = await mount(<EmptyState title="Empty" headingLevel={2} />);
    expect(within(host).getByRole("heading", { level: 2, name: "Empty" })).toBeTruthy();
  });

  it.each([
    ["no-data", "info"],
    ["recording-not-started", "pending"],
    ["backfill-in-progress", "pending"],
    ["filtered-empty", "search"],
  ] as const)("%s draws the %s glyph at lg, hidden", async (variant, glyph) => {
    const host = await mount(<EmptyState variant={variant as EmptyStateVariant} title="t" />);
    const svg = host.querySelector(".cv-empty-state__glyph svg");
    expect(svg?.getAttribute("aria-hidden")).toBe("true");
    expect(svg?.outerHTML).toBe(await glyphOf(glyph));
  });

  it("a host's icon replaces the variant's", async () => {
    const host = await mount(<EmptyState title="t" icon="lock" />);
    expect(host.querySelector(".cv-empty-state__glyph svg")?.outerHTML).toBe(await glyphOf("lock"));
  });

  it("the one secondary link follows the CTA in the Tab order", async () => {
    const host = await mount(
      <EmptyState
        variant="recording-not-started"
        title="History starts 14:02"
        cta={{ label: "Open the recorder", onClick: fn() }}
        link={{ label: "Show coverage", href: "#coverage" }}
      />,
    );
    const link = within(host).getByRole("link", { name: "Show coverage" });
    expect(link.dataset["cmp"]).toBe("CMP-021");
    expect(link).toHaveAttribute("href", "#coverage");
    await userEvent.tab();
    await userEvent.tab();
    expect(link).toHaveFocus();
  });

  it("the sentence form: no cta renders no button, the description carries the reason", async () => {
    const host = await mount(
      <EmptyState title="No rules yet" description="Your role can't change rules." />,
    );
    expect(within(host).queryByRole("button")).toBeNull();
    expect(host.querySelector(".cv-empty-state__actions")).toBeNull();
    expect(within(host).getByText("Your role can't change rules.")).toBeTruthy();
  });

  it("backfill renders the host's progress; other variants ignore it", async () => {
    const bar = <ProgressBar label="History" value={33} valueText="page 3 of ~9" />;
    const backfill = await mount(
      <EmptyState variant="backfill-in-progress" title="Loading history" progress={bar} />,
    );
    expect(within(backfill).getByRole("progressbar", { name: "History" })).toBeTruthy();
    const other = await mount(<EmptyState title="Empty" progress={bar} />);
    expect(within(other).queryByRole("progressbar")).toBeNull();
  });

  it("variant=error renders CMP-027's panel, polite, with the CTA as Retry and no link", async () => {
    const retry = fn();
    const host = await mount(
      <EmptyState
        variant="error"
        title="Couldn't load users"
        description="The store is unavailable."
        cta={{ label: "Retry", onClick: retry }}
        link={{ label: "Status page", href: "#status" }}
      />,
    );
    const panel = host.querySelector<HTMLElement>(".cv-error-state");
    expect(panel?.dataset["cmp"]).toBe("CMP-027");
    expect(panel?.dataset["form"]).toBe("panel");
    expect(host.querySelector(".cv-empty-state")).toBeNull();
    const status = within(host).getByRole("status");
    expect(status).toHaveAttribute("aria-live", "polite");
    expect(status).toHaveTextContent("The store is unavailable.");
    expect(within(host).queryByRole("alert")).toBeNull();
    expect(
      within(host).getByRole("heading", { level: 3, name: "Couldn't load users" }),
    ).toBeTruthy();
    expect(within(host).queryByRole("link")).toBeNull();
    await userEvent.click(within(host).getByRole("button", { name: "Retry" }));
    expect(retry).toHaveBeenCalledTimes(1);
  });

  it("variant=error without a description speaks the title as its message", async () => {
    const host = await mount(
      <EmptyState variant="error" title="Couldn't load users" headingLevel={2} />,
    );
    expect(within(host).queryByRole("heading")).toBeNull();
    expect(within(host).getByRole("status")).toHaveTextContent("Couldn't load users");
  });

  it("composes every story", async () => {
    const composed = composeStories(stories);
    for (const Story of Object.values(composed)) {
      const host = await mount(<Story />);
      expect(host.querySelector(".cv-empty-state, .cv-error-state")).toBeTruthy();
    }
  });
});
