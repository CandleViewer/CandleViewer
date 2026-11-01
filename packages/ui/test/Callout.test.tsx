// @vitest-environment jsdom
import { composeStories } from "@storybook/react-vite";
import { act, useLayoutEffect, useState } from "react";
import { expect, fn, userEvent, within } from "storybook/test";
import { describe, it, vi } from "vitest";
import { Callout, type CalloutTone } from "../src/components/index.js";
import { Icon } from "../src/icons/Icon.js";
import * as stories from "../src/components/Callout.stories.js";
import { mount } from "./theme/mount.js";

const root = (host: HTMLElement): HTMLElement => {
  const el = host.querySelector<HTMLElement>(".cv-callout");
  if (el === null) throw new Error("no callout rendered");
  return el;
};
const glyphOf = async (name: Parameters<typeof Icon>[0]["name"]): Promise<string | undefined> =>
  (await mount(<Icon name={name} />)).querySelector("svg")?.outerHTML;

describe("Callout (CMP-028)", () => {
  it.each([
    ["info", "status", "polite"],
    ["success", "status", "polite"],
    ["connection-reconnecting", "status", "polite"],
    ["warning", "alert", "assertive"],
    ["danger", "alert", "assertive"],
    ["connection-disconnected", "alert", "assertive"],
  ] as const)("%s defaults to role=%s (%s)", async (tone, role, live) => {
    const host = await mount(<Callout tone={tone} title="State" />);
    const region = within(host).getByRole(role);
    expect(region).toHaveAttribute("aria-live", live);
    expect(region).toHaveAttribute("aria-atomic", "true");
    expect(region).toHaveTextContent("State");
    expect(within(host).queryByRole(role === "alert" ? "status" : "alert")).toBeNull();
    expect(root(host).dataset["tone"]).toBe(tone);
  });

  it.each([
    ["warning", "polite", "status"],
    ["info", "assertive", "alert"],
  ] as const)("live overrides the %s default to %s", async (tone, live, role) => {
    const host = await mount(<Callout tone={tone} title="State" live={live} />);
    expect(within(host).getByRole(role)).toHaveAttribute("aria-live", live);
  });

  it("live=off renders no live role, and the words render at once", async () => {
    const host = await mount(<Callout tone="danger" title="Your access changed" live="off" />);
    expect(within(host).queryByRole("alert")).toBeNull();
    expect(within(host).queryByRole("status")).toBeNull();
    expect(host.querySelector("[aria-live]")).toBeNull();
    expect(root(host)).toHaveTextContent("Your access changed");
  });

  it("mounts the live region empty, then inserts the words, so the entry is announced", async () => {
    const seen: string[] = [];
    function Probe(): null {
      // A sibling's layout effect runs in the callout's first commit, before its text effect.
      useLayoutEffect(() => {
        seen.push(document.querySelector('[role="alert"]')?.textContent ?? "missing");
      }, []);
      return null;
    }
    const host = await mount(
      <>
        <Callout tone="warning" title="Degraded" />
        <Probe />
      </>,
    );
    expect(seen).toEqual([""]);
    expect(within(host).getByRole("alert")).toHaveTextContent("Degraded");
  });

  it.each([
    [
      "a tone crossing to assertive",
      { tone: "connection-reconnecting" },
      { tone: "connection-disconnected" },
      "alert",
    ],
    ["live going from off to on", { tone: "info", live: "off" }, { tone: "info" }, "status"],
  ] as const)(
    "re-announces on %s: a fresh region, empty first, then filled",
    async (_, before, after, role) => {
      const seen: string[] = [];
      function Probe({ phase }: { phase: string }): null {
        // Runs in the same commit as the role change, before the callout's fill effect.
        useLayoutEffect(() => {
          seen.push(document.querySelector(`[role="${role}"]`)?.textContent ?? "missing");
        }, [phase]);
        return null;
      }
      const { createRoot } = await import("react-dom/client");
      const host = document.body.appendChild(document.createElement("div"));
      const r = createRoot(host);
      await act(async () =>
        r.render(
          <>
            <Callout {...before} title="Connection" />
            <Probe phase="before" />
          </>,
        ),
      );
      const region = host.querySelector(".cv-callout__message");
      await act(async () =>
        r.render(
          <>
            <Callout {...after} title="Connection" />
            <Probe phase="after" />
          </>,
        ),
      );
      expect(seen.at(-1)).toBe("");
      const fresh = within(host).getByRole(role);
      expect(fresh).toHaveTextContent("Connection");
      expect(fresh).not.toBe(region);
      await act(async () => r.unmount());
    },
  );

  it("never moves focus when it mounts or updates while focus is elsewhere", async () => {
    const outside = document.body.appendChild(document.createElement("button"));
    outside.textContent = "Elsewhere";
    outside.focus();
    const { createRoot } = await import("react-dom/client");
    const r = createRoot(document.body.appendChild(document.createElement("div")));
    await act(async () =>
      r.render(<Callout tone="info" title="Syncing" dismissible onDismiss={fn()} />),
    );
    expect(document.activeElement).toBe(outside);
    await act(async () =>
      r.render(
        <Callout
          tone="danger"
          title="Locked"
          retry={{ label: "Retry now", onClick: fn() }}
          dismissible
          onDismiss={fn()}
        />,
      ),
    );
    expect(document.activeElement).toBe(outside);
    await act(async () => r.unmount());
  });

  it("actions with the same label render as separate buttons, with no duplicate-key warning", async () => {
    const error = vi.spyOn(console, "error").mockImplementation(() => undefined);
    // Restored even when an assertion throws, so a failure here never silences the next test's errors.
    try {
      const first = fn();
      const second = fn();
      const host = await mount(
        <Callout
          title="Two"
          actions={[
            { label: "Details", onClick: first },
            { label: "Details", onClick: second },
          ]}
        />,
      );
      const buttons = within(host).getAllByRole("button", { name: "Details" });
      expect(buttons).toHaveLength(2);
      act(() => buttons[1]?.click());
      expect(second).toHaveBeenCalledTimes(1);
      expect(first).not.toHaveBeenCalled();
      const keyWarnings = error.mock.calls.filter((args) =>
        args.some((a) => typeof a === "string" && a.includes("same key")),
      );
      expect(keyWarnings).toEqual([]);
    } finally {
      error.mockRestore();
    }
  });

  it.each([
    ["info", "info"],
    ["success", "success"],
    ["warning", "warning"],
    ["danger", "danger"],
    ["connection-reconnecting", "disconnected"],
    ["connection-disconnected", "disconnected"],
  ] as const)("%s carries the %s registry glyph, hidden, beside its words", async (tone, glyph) => {
    const host = await mount(<Callout tone={tone as CalloutTone} title="Words" />);
    const svg = root(host).querySelector(".cv-callout__glyph svg");
    expect(svg?.getAttribute("aria-hidden")).toBe("true");
    expect(svg?.outerHTML).toBe(await glyphOf(glyph));
    expect(root(host).querySelector(".cv-callout__title")).toHaveTextContent("Words");
  });

  it("a host's icon replaces the tone's glyph", async () => {
    const host = await mount(<Callout title="Read-only" icon="lock" />);
    expect(root(host).querySelector(".cv-callout__glyph svg")?.outerHTML).toBe(
      await glyphOf("lock"),
    );
  });

  it("renders the body and a connection tone's details under the title", async () => {
    const host = await mount(
      <Callout tone="connection-disconnected" title="Disconnected" details="Stops are unaffected.">
        Last data 00:12 ago.
      </Callout>,
    );
    expect(root(host).querySelector(".cv-callout__body")).toHaveTextContent("Last data 00:12 ago.");
    expect(root(host).querySelector(".cv-callout__details")).toHaveTextContent(
      "Stops are unaffected.",
    );
  });

  it("inline by default; band on request", async () => {
    expect(root(await mount(<Callout title="a" />)).dataset["placement"]).toBe("inline");
    expect(root(await mount(<Callout title="b" placement="band" />)).dataset["placement"]).toBe(
      "band",
    );
  });

  it("retry then actions are CMP-001 secondary buttons outside the live region, in order", async () => {
    const retry = fn();
    const details = fn();
    const host = await mount(
      <Callout
        tone="connection-disconnected"
        title="Disconnected"
        retry={{ label: "Retry now", onClick: retry }}
        actions={[{ label: "Details", onClick: details }]}
      />,
    );
    const buttons = within(host).getAllByRole("button");
    expect(buttons.map((b) => b.textContent)).toEqual(["Retry now", "Details"]);
    for (const b of buttons) {
      expect(b.dataset["cmp"]).toBe("CMP-001");
      expect(b.dataset["variant"]).toBe("secondary");
    }
    expect(within(host).getByRole("alert")).not.toHaveTextContent("Retry now");
    await userEvent.tab();
    await userEvent.keyboard("{Enter}");
    await userEvent.tab();
    await userEvent.keyboard(" ");
    expect(retry).toHaveBeenCalledTimes(1);
    expect(details).toHaveBeenCalledTimes(1);
  });

  it("an action takes CMP-001's loading: busy, focusable, a press does nothing, the element kept", async () => {
    // E16-D02 §6.5: the level-3 banner's "Purge data…" is busy while this client's purge runs (not T2).
    const onClick = fn();
    function Banner() {
      const [busy, setBusy] = useState(false);
      return (
        <>
          <button type="button" onClick={() => setBusy(true)}>
            Start
          </button>
          <Callout
            tone="danger"
            title="Recording stopped"
            actions={[{ label: "Purge data…", onClick, loading: busy }]}
          />
        </>
      );
    }
    const host = await mount(<Banner />);
    const action = within(host).getByRole("button", { name: "Purge data…" });
    expect(action).not.toHaveAttribute("aria-busy");
    await userEvent.click(within(host).getByRole("button", { name: "Start" }));
    const busy = within(host).getByRole("button", { name: "Purge data…" });
    expect(busy).toBe(action);
    expect(busy).toHaveAttribute("aria-busy", "true");
    expect(busy).not.toHaveAttribute("aria-disabled");
    await userEvent.click(busy);
    expect(onClick).not.toHaveBeenCalled();
  });

  it("no buttons and nothing focusable without retry, actions or dismissible", async () => {
    const host = await mount(<Callout title="Info" />);
    expect(within(host).queryByRole("button")).toBeNull();
    await userEvent.tab();
    expect(document.body).toHaveFocus();
  });

  it("dismissible: a ghost CMP-002 close named 'Dismiss {title}' that calls onDismiss", async () => {
    const onDismiss = fn();
    const host = await mount(<Callout title="Reconnected" dismissible onDismiss={onDismiss} />);
    const button = within(host).getByRole("button", { name: "Dismiss Reconnected" });
    expect(button.dataset["cmp"]).toBe("CMP-002");
    expect(button.dataset["variant"]).toBe("ghost");
    expect(within(host).getByRole("status")).not.toHaveTextContent("Dismiss");
    await userEvent.tab();
    await userEvent.keyboard("{Enter}");
    expect(onDismiss).toHaveBeenCalledTimes(1);
    // The callout never moves focus itself: the host owns where it goes next.
    expect(button).toHaveFocus();
  });

  it("Esc never dismisses", async () => {
    const onDismiss = fn();
    await mount(<Callout tone="danger" title="Locked" dismissible onDismiss={onDismiss} />);
    await userEvent.tab();
    await userEvent.keyboard("{Escape}");
    expect(onDismiss).not.toHaveBeenCalled();
  });

  it("keeps dismissal to dismissible callouts at the type level", () => {
    // @ts-expect-error onDismiss needs dismissible
    const stray = <Callout title="x" onDismiss={fn()} />;
    // @ts-expect-error a dismissible callout needs onDismiss
    const noHandler = <Callout title="x" dismissible />;
    expect([stray, noHandler]).toHaveLength(2);
  });

  it("the Dismissible story's host returns focus to its panel after the dismissal", async () => {
    const { Dismissible } = composeStories(stories);
    const host = await mount(<Dismissible />);
    await userEvent.tab();
    await userEvent.keyboard("{Enter}");
    await act(async () => {
      await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()));
    });
    expect(within(host).getByRole("region", { name: "Orders panel" })).toHaveFocus();
    expect(within(host).queryByRole("button")).toBeNull();
  });

  it("composes every story", async () => {
    const composed = composeStories(stories);
    for (const Story of Object.values(composed)) {
      const host = await mount(<Story />);
      expect(root(host)).toBeTruthy();
    }
  });
});
