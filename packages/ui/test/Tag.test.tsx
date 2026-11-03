// @vitest-environment jsdom
import { composeStories } from "@storybook/react-vite";
import { act, useState, type JSX } from "react";
import { expect, fireEvent, fn, userEvent, within } from "storybook/test";
import { describe, it } from "vitest";
import { Tag, Tooltip } from "../src/components/index.js";
import * as stories from "../src/components/Tag.stories.js";
import { seriousViolations } from "./axe.js";
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

  it("removeLabel names the remove control for its owning group (CMP-055's 'Remove filter …')", async () => {
    const onRemove = fn();
    const host = await mount(
      <Tag
        label="Account: Sub-1"
        removable
        onRemove={onRemove}
        removeLabel="Remove filter Account: Sub-1"
      />,
    );
    await userEvent.click(
      within(host).getByRole("button", { name: "Remove filter Account: Sub-1" }),
    );
    expect(onRemove).toHaveBeenCalledTimes(1);
    expect(chip(host).querySelector(".cv-tag__label")).toHaveTextContent("Account: Sub-1");
  });

  it("takes removeLabel on a removable chip only (type level)", () => {
    // @ts-expect-error a static chip has no remove control to name
    const onStatic = <Tag label="x" removeLabel="Remove x" />;
    expect(onStatic).toBeDefined();
  });

  it("emits the density attribute on the chip and the nested button", async () => {
    const host = await mount(
      <Tag label="Breakout" density="comfortable" removable onRemove={fn()} />,
    );
    expect(chip(host).dataset["density"]).toBe("comfortable");
    expect(within(host).getByRole("button").dataset["density"]).toBe("comfortable");
  });
});

/** A host that holds a toggle's state, as the Fills tab holds its Type chips (E29-D02:299: all on by default). */
function Held({
  label,
  onChange,
}: {
  label: string;
  onChange?: (p: boolean) => void;
}): JSX.Element {
  const [pressed, setPressed] = useState(true);
  return (
    <Tag
      variant="toggle"
      label={label}
      pressed={pressed}
      onPressedChange={(next) => {
        onChange?.(next);
        setPressed(next);
      }}
    />
  );
}

describe("Tag toggle (CMP-011 `toggle`, E29-S04; E29-D04 §2.9, E29-D02:299)", () => {
  it("is a native button named by its word, its state in aria-pressed, at the control height", async () => {
    const host = await mount(
      <Tag variant="toggle" label="Trade" pressed onPressedChange={fn()} density="compact" />,
    );
    const button = within(host).getByRole("button", { name: "Trade", pressed: true });
    expect(button.tagName).toBe("BUTTON");
    expect(button).toHaveAttribute("type", "button");
    expect(button).toHaveAttribute("aria-pressed", "true");
    expect(button).toHaveClass("cv-tag", "cv-control", "cv-focus-ring");
    expect([button.dataset["cmp"], button.dataset["variant"], button.dataset["density"]]).toEqual([
      "CMP-011",
      "toggle",
      "compact",
    ]);
    expect(button.querySelector("svg")).toBeNull();
  });

  it("an off chip says so in aria-pressed, never through its name", async () => {
    const host = await mount(
      <Tag variant="toggle" label="Funding" pressed={false} onPressedChange={fn()} />,
    );
    expect(within(host).getByRole("button", { name: "Funding", pressed: false })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
  });

  it("Tab reaches it; Space and Enter flip it through its host; the name never changes", async () => {
    const onChange = fn();
    const host = await mount(<Held label="ADL" onChange={onChange} />);
    await userEvent.tab();
    const button = within(host).getByRole("button", { name: "ADL" });
    expect(button).toHaveFocus();
    await userEvent.keyboard(" ");
    expect(button).toHaveAttribute("aria-pressed", "false");
    await userEvent.keyboard("{Enter}");
    expect(button).toHaveAttribute("aria-pressed", "true");
    await userEvent.click(button);
    expect(onChange.mock.calls).toEqual([[false], [true], [false]]);
    expect(button).toHaveAccessibleName("ADL");
    expect(button).toHaveFocus();
  });

  it("keeps the toggle a view choice at the type level: no icon, no removal, never gated or disabled", () => {
    // @ts-expect-error a toggle needs its state and its handler
    const stateless = <Tag variant="toggle" label="x" />;
    // @ts-expect-error a toggle takes no icon (E29-D02:299)
    const withIcon = <Tag variant="toggle" label="x" pressed onPressedChange={fn()} icon="lock" />;
    const gated = (
      // @ts-expect-error a view choice is never gated (E29-D04:390)
      <Tag variant="toggle" label="x" pressed onPressedChange={fn()} disabledReason="r" />
    );
    expect([stateless, withIcon, gated]).toHaveLength(3);
  });

  it("passes the button's attributes through: a CMP-016 Tooltip describes the chip and keeps its name", async () => {
    const host = await mount(
      <Tooltip content="ADL — auto-deleveraged">
        <Tag variant="toggle" label="ADL" pressed onPressedChange={fn()} />
      </Tooltip>,
    );
    const button = within(host).getByRole("button", { name: "ADL", pressed: true });
    const tip = document.querySelector<HTMLElement>('[data-cmp="CMP-016"]');
    expect(tip).not.toBeNull();
    expect(button).toHaveAttribute("aria-describedby", tip?.id);
    expect(button).toHaveAccessibleDescription("ADL — auto-deleveraged");
    expect(button).toHaveAccessibleName("ADL");
    // The Tooltip's focus handler reaches the chip: keyboard focus shows the description at once.
    await act(async () => button.focus());
    expect(tip?.hidden).toBe(false);
  });

  it("takes the button's other attributes, never a name, a press or a state of its own (type level)", () => {
    const described = (
      <Tag variant="toggle" label="x" pressed onPressedChange={fn()} aria-describedby="d" id="i" />
    );
    const renamed = (
      // @ts-expect-error its name is its label, which never changes (E29-D02:299)
      <Tag variant="toggle" label="x" pressed onPressedChange={fn()} aria-label="y" />
    );
    const clicked = (
      // @ts-expect-error its press is onPressedChange
      <Tag variant="toggle" label="x" pressed onPressedChange={fn()} onClick={fn()} />
    );
    const stated = (
      // @ts-expect-error its state is pressed
      <Tag variant="toggle" label="x" pressed onPressedChange={fn()} aria-pressed="mixed" />
    );
    // @ts-expect-error a static chip is a span, so a button attribute would be dropped
    const titled = <Tag label="x" title="t" />;
    // @ts-expect-error a status chip is a span too
    const statusDescribed = <Tag variant="info" label="x" aria-describedby="d" />;
    expect([described, renamed, clicked, stated, titled, statusDescribed]).toHaveLength(6);
  });

  it("the five Type chips have no serious or critical axe violation", async () => {
    const host = await mount(
      <div>
        {["Trade", "ADL", "Liquidation", "Funding", "Settlement"].map((word) => (
          <Held key={word} label={word} />
        ))}
      </div>,
    );
    expect(within(host).getAllByRole("button", { pressed: true })).toHaveLength(5);
    expect(await seriousViolations(host)).toEqual([]);
  });
});

describe("Tag stories", () => {
  it.each(Object.entries(composeStories(stories)))("%s renders", async (_name, Story) => {
    const host = await mount(<Story />);
    expect(host.querySelectorAll(".cv-tag").length).toBeGreaterThan(0);
  });
});
