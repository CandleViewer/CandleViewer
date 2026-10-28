// @vitest-environment jsdom
import { composeStories } from "@storybook/react-vite";
import { act, useLayoutEffect } from "react";
import { expect, fn, userEvent, within } from "storybook/test";
import { describe, it } from "vitest";
import { Callout, ErrorState, InlineError } from "../src/components/index.js";
import { Icon } from "../src/icons/Icon.js";
import * as stories from "../src/components/ErrorState.stories.js";
import { loadCss } from "./css-contract.js";
import { mount } from "./theme/mount.js";

const root = (host: HTMLElement): HTMLElement => {
  const el = host.querySelector<HTMLElement>(".cv-error-state");
  if (el === null) throw new Error("no error state rendered");
  return el;
};
const glyphOf = async (
  name: Parameters<typeof Icon>[0]["name"],
  size?: "lg",
): Promise<string | undefined> =>
  (
    await mount(size === undefined ? <Icon name={name} /> : <Icon name={name} size={size} />)
  ).querySelector("svg")?.outerHTML;

describe("ErrorState / InlineError (CMP-027)", () => {
  it.each([
    ["error", "alert", "assertive"],
    ["warning", "status", "polite"],
  ] as const)("%s defaults to role=%s (%s), atomic", async (severity, role, live) => {
    const host = await mount(<ErrorState severity={severity} message="Failed" />);
    const region = within(host).getByRole(role);
    expect(region).toHaveAttribute("aria-live", live);
    expect(region).toHaveAttribute("aria-atomic", "true");
    expect(region).toHaveTextContent("Failed");
    expect(within(host).queryByRole(role === "alert" ? "status" : "alert")).toBeNull();
  });

  it("defaults to the error severity and the panel form", async () => {
    const el = root(await mount(<ErrorState message="Failed" />));
    expect(el.dataset["severity"]).toBe("error");
    expect(el.dataset["form"]).toBe("panel");
    expect(el.dataset["cmp"]).toBe("CMP-027");
  });

  it.each([
    ["error", "polite", "status"],
    ["warning", "assertive", "alert"],
  ] as const)("live overrides the %s default to %s", async (severity, live, role) => {
    const host = await mount(<ErrorState severity={severity} live={live} message="Failed" />);
    expect(within(host).getByRole(role)).toHaveAttribute("aria-live", live);
  });

  it("live=off renders no live role, and the words render at once", async () => {
    const host = await mount(<ErrorState live="off" message="Already announced" />);
    expect(host.querySelector("[aria-live]")).toBeNull();
    expect(within(host).queryByRole("alert")).toBeNull();
    expect(root(host)).toHaveTextContent("Already announced");
  });

  it("mounts the alert empty, then inserts the words, so a transient failure is announced once", async () => {
    const seen: string[] = [];
    function Probe(): null {
      useLayoutEffect(() => {
        seen.push(document.querySelector('[role="alert"]')?.textContent ?? "missing");
      }, []);
      return null;
    }
    const host = await mount(
      <>
        <ErrorState message="Not sent" />
        <Probe />
      </>,
    );
    expect(seen).toEqual([""]);
    expect(within(host).getByRole("alert")).toHaveTextContent("Not sent");
  });

  it.each([
    ["error", "error"],
    ["warning", "warning"],
  ] as const)("%s carries the %s registry glyph, hidden, lg in the panel", async (sev, glyph) => {
    const host = await mount(<ErrorState severity={sev} message="m" />);
    const svg = root(host).querySelector(".cv-error-state__glyph svg");
    expect(svg?.getAttribute("aria-hidden")).toBe("true");
    expect(svg?.outerHTML).toBe(await glyphOf(glyph, "lg"));
  });

  it("inline and banner draw the glyph at size.icon", async () => {
    for (const form of ["inline", "banner"] as const) {
      const host = await mount(<ErrorState form={form} message="m" />);
      expect(root(host).querySelector(".cv-error-state__glyph svg")?.outerHTML).toBe(
        await glyphOf("error"),
      );
    }
  });

  it("banner reuses CMP-028's box in the error or warning tone, its message strong", async () => {
    const error = root(await mount(<ErrorState form="banner" message="Off-tick" />));
    expect(error).toHaveClass("cv-callout");
    expect(error.dataset["tone"]).toBe("danger");
    expect(error.dataset["placement"]).toBe("inline");
    expect(error.querySelector(".cv-callout__title")).toHaveTextContent("Off-tick");
    const warning = root(
      await mount(<ErrorState form="banner" severity="warning" message="Far" />),
    );
    expect(warning.dataset["tone"]).toBe("warning");
  });

  it("panel and inline carry no callout box", async () => {
    for (const form of ["panel", "inline"] as const) {
      const el = root(await mount(<ErrorState form={form} message="m" />));
      expect(el).not.toHaveClass("cv-callout");
      expect(el.dataset["tone"]).toBeUndefined();
    }
  });

  it("InlineError is the inline form", async () => {
    const host = await mount(<InlineError message="Not sent" />);
    expect(root(host).dataset["form"]).toBe("inline");
    expect(within(host).getByRole("alert")).toHaveTextContent("Not sent");
  });

  it("retry then action are CMP-001 secondary buttons outside the live region, in order", async () => {
    const retry = fn();
    const action = fn();
    const host = await mount(
      <ErrorState
        message="Failed"
        retry={{ label: "Retry", onClick: retry }}
        action={{ label: "Open logs", onClick: action }}
      />,
    );
    const buttons = within(host).getAllByRole("button");
    expect(buttons.map((b) => b.textContent)).toEqual(["Retry", "Open logs"]);
    for (const b of buttons) {
      expect(b.dataset["cmp"]).toBe("CMP-001");
      expect(b.dataset["variant"]).toBe("secondary");
    }
    expect(within(host).getByRole("alert")).not.toHaveTextContent("Retry");
    await userEvent.tab();
    await userEvent.keyboard("{Enter}");
    await userEvent.tab();
    await userEvent.keyboard(" ");
    expect(retry).toHaveBeenCalledTimes(1);
    expect(action).toHaveBeenCalledTimes(1);
  });

  it("nothing focusable without retry, action, details or items", async () => {
    const host = await mount(<ErrorState message="Failed" />);
    expect(within(host).queryByRole("button")).toBeNull();
    await userEvent.tab();
    expect(document.body).toHaveFocus();
  });

  it("details sit behind a 'Technical details' disclosure, outside the live region", async () => {
    const host = await mount(
      <ErrorState message="Failed" details="code: STORE_UNAVAILABLE" live="polite" />,
    );
    const toggle = within(host).getByRole("button", { name: "Technical details" });
    const panel = document.getElementById(toggle.getAttribute("aria-controls") ?? "");
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(panel).not.toBeVisible();
    expect(within(host).getByRole("status")).not.toHaveTextContent("STORE_UNAVAILABLE");
    await userEvent.tab();
    await userEvent.keyboard("{Enter}");
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(panel).toBeVisible();
    expect(panel).toHaveTextContent("code: STORE_UNAVAILABLE");
    expect(within(host).getByRole("button", { name: "Copy technical details" })).toBeTruthy();
    await userEvent.keyboard(" ");
    expect(toggle).toHaveAttribute("aria-expanded", "false");
  });

  it("the heading takes tabindex -1 only with a headingId", async () => {
    const host = await mount(<ErrorState title="Can't load" message="m" live="off" />);
    expect(within(host).getByRole("heading", { name: "Can't load" })).not.toHaveAttribute(
      "tabindex",
    );
  });

  it("title is a heading at headingLevel (default 3) with tabindex -1, inside the alert", async () => {
    const host = await mount(
      <ErrorState title="Can't submit" headingId="sum" message="Fix these" />,
    );
    const heading = within(host).getByRole("heading", { level: 3, name: "Can't submit" });
    expect(heading).toHaveAttribute("tabindex", "-1");
    expect(heading.id).toBe("sum");
    expect(within(host).getByRole("alert")).toContainElement(heading);
    const h2 = await mount(<ErrorState title="T" headingLevel={2} message="m" />);
    expect(within(h2).getByRole("heading", { level: 2 })).toBeTruthy();
  });

  it("no heading without a title", async () => {
    const host = await mount(<ErrorState message="m" />);
    expect(within(host).queryByRole("heading")).toBeNull();
  });

  it("an error summary's links move focus to their fields", async () => {
    const host = await mount(
      <>
        <ErrorState
          form="banner"
          title="Can't submit — 2 problems"
          message="Fix these."
          items={[
            { label: "Enter a quantity", href: "#qty" },
            { label: "Enter a stop-loss", href: "#stop" },
          ]}
        />
        <input id="qty" aria-label="Quantity" />
        <input id="stop" aria-label="Stop-loss" />
      </>,
    );
    const links = within(host).getAllByRole("link");
    expect(links.map((l) => l.textContent)).toEqual(["Enter a quantity", "Enter a stop-loss"]);
    for (const l of links) expect(l.dataset["cmp"]).toBe("CMP-021");
    expect(within(host).getByRole("alert")).toContainElement(links[1] ?? null);
    await userEvent.click(within(host).getByRole("link", { name: "Enter a stop-loss" }));
    expect(within(host).getByLabelText("Stop-loss")).toHaveFocus();
  });

  it("a link to no field, or off the page, is left to navigate", async () => {
    const host = await mount(
      <ErrorState
        message="m"
        items={[
          { label: "Missing", href: "#nowhere" },
          { label: "Elsewhere", href: "/help" },
        ]}
      />,
    );
    // The window sees the click last: it records whether the component kept the navigation, then stops it
    // (jsdom implements no navigation).
    const seen: boolean[] = [];
    const record = (event: Event): void => {
      seen.push(event.defaultPrevented);
      event.preventDefault();
    };
    window.addEventListener("click", record);
    for (const name of ["Missing", "Elsewhere"]) {
      const link = within(host).getByRole("link", { name });
      act(() => {
        link.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
      });
    }
    window.removeEventListener("click", record);
    expect(seen).toEqual([false, false]);
  });

  /** Clicks `name` and reports whether the component kept the default; the window then stops jsdom navigating. */
  const clickKeepsDefault = (
    host: HTMLElement,
    name: string,
    init: MouseEventInit = {},
  ): boolean => {
    let prevented: boolean | undefined;
    const record = (event: Event): void => {
      prevented = event.defaultPrevented;
      event.preventDefault();
    };
    window.addEventListener("click", record);
    act(() => {
      within(host)
        .getByRole("link", { name })
        .dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true, ...init }));
    });
    window.removeEventListener("click", record);
    return prevented === false;
  };

  it("a malformed href falls through to the default", async () => {
    const host = await mount(
      <ErrorState live="off" message="m" items={[{ label: "Bad", href: "#%E0%A4%A" }]} />,
    );
    expect(clickKeepsDefault(host, "Bad")).toBe(true);
  });

  it.each([
    ["ctrl", { ctrlKey: true }],
    ["meta", { metaKey: true }],
    ["shift", { shiftKey: true }],
    ["alt", { altKey: true }],
    ["middle-button", { button: 1 }],
  ] as const)("a %s click keeps the default and leaves focus alone", async (_, init) => {
    const host = await mount(
      <>
        <ErrorState live="off" message="m" items={[{ label: "Qty", href: "#qty" }]} />
        <input id="qty" aria-label="Quantity" />
      </>,
    );
    expect(clickKeepsDefault(host, "Qty", init)).toBe(true);
    expect(within(host).getByLabelText("Quantity")).not.toHaveFocus();
  });

  it("a target that does not take focus keeps the default", async () => {
    const host = await mount(
      <>
        <ErrorState live="off" message="m" items={[{ label: "Note", href: "#note" }]} />
        <div id="note">Not focusable</div>
      </>,
    );
    expect(clickKeepsDefault(host, "Note")).toBe(true);
    expect(document.getElementById("note")).not.toHaveFocus();
  });

  it("only a #id href moves focus: /qty navigates even with an id=qty field present", async () => {
    const host = await mount(
      <>
        <ErrorState live="off" message="m" items={[{ label: "Qty page", href: "/qty" }]} />
        <input id="qty" aria-label="Quantity" />
      </>,
    );
    expect(clickKeepsDefault(host, "Qty page")).toBe(true);
    expect(within(host).getByLabelText("Quantity")).not.toHaveFocus();
  });

  it("a plain click on a #id link prevents the navigation and focuses the field", async () => {
    const host = await mount(
      <>
        <ErrorState live="off" message="m" items={[{ label: "Qty", href: "#qty" }]} />
        <input id="qty" aria-label="Quantity" />
      </>,
    );
    expect(clickKeepsDefault(host, "Qty")).toBe(false);
    expect(within(host).getByLabelText("Quantity")).toHaveFocus();
  });

  it("the banner's CMP-028 class names exist on a rendered Callout", async () => {
    const banner = await mount(
      <ErrorState
        form="banner"
        live="polite"
        message="Off-tick"
        retry={{ label: "Retry", onClick: fn() }}
      />,
    );
    const used = new Set(
      [...banner.querySelectorAll("*")].flatMap((el) =>
        [...el.classList].filter((c) => c.startsWith("cv-callout")),
      ),
    );
    expect([...used].sort()).toEqual([
      "cv-callout",
      "cv-callout__actions",
      "cv-callout__glyph",
      "cv-callout__main",
      "cv-callout__message",
      "cv-callout__title",
    ]);
    const callout = await mount(
      <Callout tone="danger" title="t" live="polite" retry={{ label: "Retry", onClick: fn() }} />,
    );
    for (const name of used) expect(callout.querySelector(`.${name}`)).not.toBeNull();
    // The two tones the banner sets are ones callout.css draws.
    const calloutCss = loadCss("callout.css").normal;
    for (const severity of ["error", "warning"] as const) {
      const tone = root(await mount(<ErrorState form="banner" severity={severity} message="m" />))
        .dataset["tone"];
      expect(calloutCss).toContain(`.cv-callout[data-tone="${tone ?? ""}"]`);
    }
  });

  it("composes every story", async () => {
    const composed = composeStories(stories);
    for (const Story of Object.values(composed)) {
      const host = await mount(<Story />);
      expect(host.childElementCount).toBeGreaterThan(0);
    }
  });
});
