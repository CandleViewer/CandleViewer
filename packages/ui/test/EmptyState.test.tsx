// @vitest-environment jsdom
import { composeStories } from "@storybook/react-vite";
import { act, useState, type JSX } from "react";
import { expect, fn, userEvent, within } from "storybook/test";
import { describe, it } from "vitest";
import {
  EmptyState,
  ProgressBar,
  formatRbacReason,
  type EmptyStateProps,
  type EmptyStateVariant,
} from "../src/components/index.js";
import { Icon } from "../src/icons/Icon.js";
import * as stories from "../src/components/EmptyState.stories.js";
import { seriousViolations } from "./axe.js";
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
    // A JavaScript or spread caller can still pass a link (the types forbid it): it never renders.
    const props = {
      variant: "error",
      title: "Couldn't load users",
      description: "The store is unavailable.",
      cta: { label: "Retry", onClick: retry },
      link: { label: "Status page", href: "#status" },
    } as unknown as EmptyStateProps;
    const host = await mount(<EmptyState {...props} />);
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

  it("keeps link and progress off variant=error at the type level", () => {
    // @ts-expect-error CMP-027 has no link
    const linked = <EmptyState variant="error" title="x" link={{ label: "l", href: "#l" }} />;
    // @ts-expect-error CMP-027 has no progress
    const progressing = <EmptyState variant="error" title="x" progress={<span />} />;
    const allowed = (
      <EmptyState variant="filtered-empty" title="x" link={{ label: "l", href: "#l" }} />
    );
    expect([linked, progressing, allowed]).toHaveLength(3);
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

describe("EmptyState actions (E08-D05 A-D05-5)", () => {
  const COOLDOWN = "Checked a moment ago.";
  const OWNER_ONLY = formatRbacReason("rbac.owner_only", { verb: "refresh the instrument list" });
  const looks = (host: HTMLElement): string[] =>
    within(host)
      .getAllByRole("button")
      .map((b) => `${b.textContent ?? ""}:${b.dataset["variant"] ?? ""}`);
  /** Fresh actions per test: their mocks never carry calls over. */
  const fresh = () => ({
    clear: { label: "Clear search", onClick: fn() },
    check: { label: "Check again", onClick: fn(), disabledReason: COOLDOWN },
    retry: { label: "Retry now", onClick: fn() },
  });

  it("one or two CMP-001 buttons in order: the first primary, the second secondary, unless variant says", async () => {
    const { clear } = fresh();
    const info = fn();
    const host = await mount(
      <>
        <EmptyState title="No match" actions={[clear, { label: "Retry", onClick: fn() }]} />
        <EmptyState
          title="Closed"
          actions={[{ label: "Info", onClick: info, variant: "secondary" }]}
        />
      </>,
    );
    expect(looks(host)).toEqual(["Clear search:primary", "Retry:secondary", "Info:secondary"]);
    await userEvent.tab();
    await userEvent.keyboard("{Enter}");
    await userEvent.tab();
    await userEvent.tab();
    await userEvent.keyboard(" ");
    expect([clear.onClick.mock.calls.length, info.mock.calls.length]).toEqual([1, 1]);
  });

  it("a T2 action (CMP-079, 2a): focusable, aria-disabled, its reason under it and its description; inert, re-said per press", async () => {
    const { clear, check } = fresh();
    const host = await mount(
      <EmptyState variant="filtered-empty" title="No match" actions={[clear, check]} />,
    );
    const gated = within(host).getByRole("button", { name: "Check again" });
    expect([gated.getAttribute("aria-disabled"), gated.hasAttribute("disabled")]).toEqual([
      "true",
      false,
    ]);
    expect(gated).toHaveAccessibleDescription(COOLDOWN);
    expect(gated.querySelector(".cv-button__glyph svg")).not.toBeNull(); // the CMP-019 `lock`
    const line = host.querySelector(".cv-empty-state__reason");
    expect([line?.textContent, line?.getAttribute("aria-hidden")]).toEqual([COOLDOWN, "true"]);
    const status = within(host).getByRole("status");
    expect(status).toBeEmptyDOMElement();
    await userEvent.tab();
    await userEvent.tab();
    expect(gated).toHaveFocus();
    await userEvent.keyboard("{Enter}");
    expect(status).toHaveTextContent(COOLDOWN);
    const said = status.firstElementChild;
    await userEvent.click(gated);
    expect(status.firstElementChild).not.toBe(said); // a new node: said again
    expect(check.onClick).not.toHaveBeenCalled();
    expect(await seriousViolations(host)).toEqual([]);
  });

  it("a gate coming or going never re-parents the button: focus stays, and a returning gate starts silent", async () => {
    const { clear } = fresh();
    let regate: (reason: string | undefined) => void = () => undefined;
    function Toggling(): JSX.Element {
      const [reason, setReason] = useState<string | undefined>(COOLDOWN);
      regate = setReason;
      const check = { label: "Check again", onClick: fn() };
      const gate = reason === undefined ? check : { ...check, disabledReason: reason };
      return <EmptyState variant="filtered-empty" title="No match" actions={[clear, gate]} />;
    }
    const host = await mount(<Toggling />);
    const button = within(host).getByRole("button", { name: "Check again" });
    act(() => button.focus());
    await userEvent.keyboard("{Enter}"); // said while gated
    for (const reason of [undefined, COOLDOWN, undefined, COOLDOWN]) {
      await act(async () => regate(reason));
      expect(document.activeElement).toBe(button); // CR-B1-01: "lifts in place"
    }
    expect(within(host).getByRole("status")).toBeEmptyDOMElement(); // CR-B1-08: no stale words
  });

  it("variant=error: live assertive is role=alert; the actions and a selectable Ref follow CMP-027's words, outside it", async () => {
    const { retry } = fresh();
    const refresh = { label: "Refresh from Bybit", onClick: fn(), disabledReason: OWNER_ONLY };
    const host = await mount(
      <EmptyState
        variant="error"
        live="assertive"
        title="Couldn't load the instrument list."
        description="CandleViewer can't reach its server."
        reference="urn:cv:req:abc"
        actions={[retry, refresh]}
      />,
    );
    const alert = await within(host).findByRole("alert");
    expect(alert.closest('[data-cmp="CMP-027"]')).not.toBeNull();
    expect(within(alert).getByRole("heading", { level: 3 })).toHaveTextContent("Couldn't load");
    const ref = within(host).getByText("Ref urn:cv:req:abc");
    expect([alert.contains(ref), within(alert).queryByRole("button")]).toEqual([false, null]);
    expect(looks(host)).toEqual(["Retry now:primary", "Refresh from Bybit:secondary"]);
    const gated = within(host).getByRole("button", { name: "Refresh from Bybit" });
    expect(gated).toHaveAccessibleDescription(OWNER_ONLY);
    await userEvent.click(within(host).getByRole("button", { name: "Retry now" }));
    expect(retry.onClick).toHaveBeenCalledOnce();
    expect(await seriousViolations(host)).toEqual([]);
  });

  it("variant=error stays polite by default (E05-D02 H13); a deprecated cta keeps CMP-027's secondary Retry beside a Ref", async () => {
    const host = await mount(
      <EmptyState
        variant="error"
        title="Couldn't load users"
        description="Down."
        reference="r-2"
        cta={{ label: "Retry", onClick: fn() }}
      />,
    );
    expect(await within(host).findByRole("status")).toHaveTextContent("Down.");
    expect(within(host).queryByRole("alert")).toBeNull();
    expect([within(host).getByText("Ref r-2").tagName, ...looks(host)]).toEqual([
      "P",
      "Retry:secondary",
    ]);
    const bare = await mount(<EmptyState variant="error" title="Down" actions={[fresh().retry]} />);
    expect(bare.querySelector(".cv-empty-state__ref")).toBeNull(); // no reference, no Ref line
  });

  it("type: one or two actions, a sole one never gated; reference and live are the error variant's", () => {
    const { clear } = fresh();
    // @ts-expect-error at most two actions (A-D05-5)
    const three = <EmptyState title="x" actions={[clear, clear, clear]} />;
    // @ts-expect-error an empty list is no actions: leave `actions` out
    const none = <EmptyState title="x" actions={[]} />;
    // @ts-expect-error the Ref line is an error's (a problem's `instance`)
    const ref = <EmptyState title="x" reference="r" />;
    // @ts-expect-error the politeness is an error's
    const live = <EmptyState title="x" live="assertive" />;
    // @ts-expect-error a sole gated action is the sentence form (E09-D09 §8): the reason as the description
    const sole = <EmptyState title="x" actions={[fresh().check]} />;
    const pair = <EmptyState title="x" actions={[clear, fresh().check]} />; // either of two may be gated
    expect([three, none, ref, live, sole, pair]).toHaveLength(6);
  });
});
