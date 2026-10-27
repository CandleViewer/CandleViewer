// @vitest-environment jsdom
import { composeStories } from "@storybook/react-vite";
import { expect, fireEvent, fn, userEvent, within } from "storybook/test";
import { describe, it } from "vitest";
import { Tag } from "../src/components/index.js";
import * as stories from "../src/components/Tag.stories.js";
import { mount } from "./theme/mount.js";

const REASON = "Owner only";
const chip = (host: HTMLElement): HTMLElement => {
  const el = host.querySelector<HTMLElement>(".cv-tag");
  if (el === null) throw new Error("no chip rendered");
  return el;
};

describe("Tag (CMP-011)", () => {
  it("a static neutral chip is a generic span named by its text, not focusable, no glyph", async () => {
    const host = await mount(<Tag label="Breakout" />);
    const el = chip(host);
    expect(el.tagName).toBe("SPAN");
    expect(el.hasAttribute("role")).toBe(false);
    expect(el.dataset["cmp"]).toBe("CMP-011");
    expect(el.dataset["variant"]).toBe("neutral");
    expect(el).toHaveTextContent("Breakout");
    expect(el.querySelector("svg")).toBeNull();
    expect(within(host).queryByRole("button")).toBeNull();
    await userEvent.tab();
    expect(document.body).toHaveFocus();
  });

  it("a neutral chip takes an optional decorative leading icon", async () => {
    const host = await mount(<Tag label="Breakout" icon="lock" />);
    const svg = chip(host).querySelector(".cv-tag__glyph svg");
    expect(svg?.getAttribute("aria-hidden")).toBe("true");
  });

  it.each([
    ["info", "Syncing"],
    ["warning", "Degraded"],
    ["danger", "Blocked"],
  ] as const)("the %s tone always carries its registry glyph plus the word", async (tone, word) => {
    const host = await mount(<Tag variant={tone} label={word} />);
    const el = chip(host);
    expect(el.dataset["variant"]).toBe(tone);
    const glyph = el.querySelector(".cv-tag__glyph svg");
    expect(glyph?.getAttribute("aria-hidden")).toBe("true");
    expect(glyph?.outerHTML).toBe(
      (await mount(<Tag label="x" icon={tone} />)).querySelector(".cv-tag__glyph svg")?.outerHTML,
    );
    expect(el.querySelector(".cv-tag__label")).toHaveTextContent(word);
    expect(within(host).queryByRole("button")).toBeNull();
  });

  it("keeps icon to neutral and removal to neutral at the type level", () => {
    // @ts-expect-error a status chip's glyph is fixed (E10)
    const iconOnStatus = <Tag variant="info" label="x" icon="lock" />;
    // @ts-expect-error only neutral chips are removable (E10)
    const removableStatus = <Tag variant="danger" label="x" removable onRemove={fn()} />;
    // @ts-expect-error a removable chip needs onRemove
    const noHandler = <Tag label="x" removable />;
    expect([iconOnStatus, removableStatus, noHandler]).toHaveLength(3);
  });

  it("removable: a ghost CMP-002 named 'Remove {label}', the only focus stop", async () => {
    const host = await mount(<Tag label="Breakout" removable onRemove={fn()} />);
    const button = within(host).getByRole("button", { name: "Remove Breakout" });
    expect(button.dataset["cmp"]).toBe("CMP-002");
    expect(button.dataset["variant"]).toBe("ghost");
    expect(button.closest(".cv-tag")).toHaveAttribute("data-removable");
    // Conv. 20: the chip itself never takes focus, so it never draws a second ring.
    expect(chip(host).hasAttribute("tabindex")).toBe(false);
    await userEvent.tab();
    expect(button).toHaveFocus();
    await userEvent.tab();
    expect(document.body).toHaveFocus();
  });

  it("Enter and Space on the remove button fire onRemove; the chip does not move focus", async () => {
    const onRemove = fn();
    const host = await mount(<Tag label="Breakout" removable onRemove={onRemove} />);
    const button = within(host).getByRole("button", { name: "Remove Breakout" });
    await userEvent.tab();
    await userEvent.keyboard("{Enter}");
    await userEvent.keyboard(" ");
    expect(onRemove).toHaveBeenCalledTimes(2);
    expect(button).toHaveFocus();
    await userEvent.click(button);
    expect(onRemove).toHaveBeenCalledTimes(3);
  });

  it("plain disabled removal: native disabled on the nested button, the chip undimmed", async () => {
    const onRemove = fn();
    const host = await mount(<Tag label="Breakout" removable onRemove={onRemove} disabled />);
    const button = within(host).getByRole("button", {
      name: "Remove Breakout",
    }) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    expect(chip(host).hasAttribute("aria-disabled")).toBe(false);
    fireEvent.click(button);
    expect(onRemove).not.toHaveBeenCalled();
  });

  it("gated removal (T2): focusable, aria-disabled, the reason as description, no removal", async () => {
    const onRemove = fn();
    const host = await mount(
      <Tag label="Breakout" removable onRemove={onRemove} disabledReason={REASON} />,
    );
    const button = within(host).getByRole("button", { name: "Remove Breakout" });
    expect(button).toHaveAttribute("aria-disabled", "true");
    expect(button).toHaveAccessibleDescription(REASON);
    await userEvent.tab();
    expect(button).toHaveFocus();
    await userEvent.keyboard("{Enter} ");
    expect(onRemove).not.toHaveBeenCalled();
  });

  it("keeps the full label in the DOM and in the remove name when truncated", async () => {
    const label = "Opening range breakout, London session";
    const host = await mount(<Tag label={label} removable onRemove={fn()} />);
    expect(chip(host).querySelector(".cv-tag__label")?.textContent).toBe(label);
    expect(within(host).getByRole("button", { name: `Remove ${label}` })).toBeDefined();
  });

  it("emits the density attribute on the chip and the nested button", async () => {
    const host = await mount(
      <Tag label="Breakout" density="comfortable" removable onRemove={fn()} />,
    );
    expect(chip(host).dataset["density"]).toBe("comfortable");
    expect(within(host).getByRole("button").dataset["density"]).toBe("comfortable");
  });
});

describe("Tag stories", () => {
  it.each(Object.entries(composeStories(stories)))("%s renders", async (_name, Story) => {
    const host = await mount(<Story />);
    expect(host.querySelectorAll(".cv-tag").length).toBeGreaterThan(0);
  });
});
