// @vitest-environment jsdom
import { act, useState, type JSX, type ReactElement } from "react";
import { expect, fireEvent, within } from "storybook/test";
import { afterEach, beforeEach, describe, it, vi } from "vitest";
import {
  Button,
  Checkbox,
  IconButton,
  RadioGroup,
  Slider,
  Tag,
  TextInput,
  Toggle,
} from "../src/components/index.js";
import { mount } from "./theme/mount.js";

/** The T2 reason echo (E09-D09 §2.2 2b, §9.2; CMP-016 `mode="echo"`) on every gateable atom. */
const REASON = "Only the owner can change account settings.";
let clock = Date.UTC(2031, 0, 1);

beforeEach(() => {
  vi.useFakeTimers();
  // A fresh minute per test: CMP-016's 300 ms skip window never carries over.
  clock += 60_000;
  vi.setSystemTime(clock);
});
afterEach(() => {
  vi.useRealTimers();
});

const echoNode = (): HTMLElement | null => document.querySelector<HTMLElement>(".cv-tooltip");
const echo = (): HTMLElement => {
  const node = echoNode();
  if (node === null) throw new Error("no echo node");
  return node;
};

type Gate = { disabledReason: string } | { disabled: true } | Record<string, never>;
const GATED: Gate = { disabledReason: REASON };
const PLAIN: Gate = { disabled: true };
const NONE: Gate = {};

interface Case {
  readonly name: string;
  /** The atom with the gate spread onto it: a T2 reason, plain disabled, or nothing. */
  readonly render: (gate: Gate) => ReactElement;
  readonly trigger: (host: HTMLElement) => HTMLElement;
  /** The echo text for a gated control (IconButton: the name, then the reason; D10). */
  readonly text?: string;
}

const cases: readonly Case[] = [
  {
    name: "Button",
    render: (g) => <Button {...g}>Save</Button>,
    trigger: (h) => within(h).getByRole("button", { name: "Save" }),
  },
  {
    name: "IconButton",
    render: (g) => <IconButton icon="settings" label="Settings" {...g} />,
    trigger: (h) => within(h).getByRole("button", { name: "Settings" }),
    text: `Settings · ${REASON}`,
  },
  {
    name: "Tag remove",
    render: (g) => <Tag label="Breakout" removable onRemove={() => undefined} {...g} />,
    trigger: (h) => within(h).getByRole("button", { name: "Remove Breakout" }),
    text: `Remove Breakout · ${REASON}`,
  },
  {
    name: "Toggle",
    render: (g) => <Toggle label="Alerts" {...g} />,
    trigger: (h) => within(h).getByRole("switch", { name: "Alerts" }),
  },
  {
    name: "Checkbox",
    render: (g) => <Checkbox label="Reduce only" {...g} />,
    trigger: (h) => within(h).getByRole("checkbox", { name: "Reduce only" }),
  },
  {
    name: "RadioGroup (group reason)",
    render: (g) => (
      <RadioGroup
        aria-label="Side"
        value="a"
        options={[
          { value: "a", label: "Long" },
          { value: "b", label: "Short" },
        ]}
        {...g}
      />
    ),
    trigger: (h) => within(h).getByRole("radio", { name: "Long" }),
  },
  {
    name: "RadioGroup (option reason)",
    render: (g) => (
      <RadioGroup
        aria-label="Side"
        value="a"
        options={[
          { value: "a", label: "Long" },
          { value: "b", label: "Short", ...g },
        ]}
      />
    ),
    trigger: (h) => within(h).getByRole("radio", { name: "Short" }),
  },
  {
    name: "Slider",
    render: (g) => (
      <Slider
        aria-label="Leverage"
        value={5}
        min={1}
        max={10}
        step={1}
        onChange={() => undefined}
        {...g}
      />
    ),
    trigger: (h) => within(h).getByRole("slider", { name: "Leverage" }),
  },
  {
    name: "TextInput",
    render: (g) => <TextInput aria-label="Label" {...g} />,
    trigger: (h) => within(h).getByRole("textbox", { name: "Label" }),
  },
];

const hover = async (el: Element): Promise<void> => {
  await act(async () => {
    fireEvent.pointerOver(el);
  });
};
const advance = async (ms: number): Promise<void> => {
  await act(async () => {
    vi.advanceTimersByTime(ms);
  });
};

describe.each(cases)("$name: T2 reason echo", ({ render, trigger, text = REASON }) => {
  it("hover shows the echo with the reason after the delay", async () => {
    const control = trigger(await mount(render(GATED)));
    expect(echo().hidden).toBe(true);
    await hover(control);
    await advance(300);
    expect(echo().hidden).toBe(false);
    expect(echo()).toHaveTextContent(text);
  });

  it("keyboard focus shows it at once; aria-hidden, and the description is the reason, unchanged", async () => {
    const control = trigger(await mount(render(GATED)));
    await act(async () => control.focus());
    expect(echo().hidden).toBe(false);
    expect(echo()).toHaveAttribute("aria-hidden", "true");
    expect(echo()).toHaveAttribute("data-mode", "echo");
    expect(control).toHaveAttribute("aria-disabled", "true");
    expect(control).toHaveAccessibleDescription(REASON);
    expect(control.getAttribute("aria-describedby")?.split(" ")).not.toContain(echo().id);
  });

  it("Esc hides it and keeps focus on the control", async () => {
    const control = trigger(await mount(render(GATED)));
    await act(async () => control.focus());
    await act(async () => {
      fireEvent.keyDown(control, { key: "Escape" });
    });
    expect(echo().hidden).toBe(true);
    expect(control).toHaveFocus();
  });

  it("a control with no reason, or a plain-disabled one, echoes no reason", async () => {
    await mount(
      <>
        {render(NONE)}
        {render(PLAIN)}
      </>,
    );
    const nodes = [...document.querySelectorAll(".cv-tooltip")];
    expect(nodes.every((n) => !n.textContent?.includes(REASON))).toBe(true);
  });
});

describe.each(cases.filter((c) => c.text === undefined))("$name: not gated", ({ render }) => {
  it("renders no echo node at all", async () => {
    await mount(
      <>
        {render(NONE)}
        {render(PLAIN)}
      </>,
    );
    expect(echoNode()).toBeNull();
  });
});

describe("RadioGroup: a group reason and an option reason", () => {
  it("a non-first row echoes the group reason, then its own, joined by ' · '", async () => {
    const own = "Skip confirmation is unavailable for LIVE market orders.";
    const host = await mount(
      <RadioGroup
        aria-label="Confirm"
        value="a"
        options={[
          { value: "a", label: "Always" },
          { value: "b", label: "Skip", disabledReason: own },
        ]}
        disabledReason={REASON}
      />,
    );
    const row = within(host).getByRole("radio", { name: "Skip" });
    await hover(row);
    await advance(300);
    const shownEcho = [...document.querySelectorAll<HTMLElement>(".cv-tooltip")].find(
      (n) => !n.hidden,
    );
    expect(shownEcho).toHaveTextContent(`${REASON} · ${own}`);
    expect(shownEcho).toHaveAttribute("aria-hidden", "true");
    // The description wiring is unchanged: a non-first row reads its own reason only.
    expect(row).toHaveAccessibleDescription(own);
  });
});

describe("IconButton name echo (D10)", () => {
  it("an enabled button echoes its name only; plain disabled has none", async () => {
    const host = await mount(
      <>
        <IconButton icon="settings" label="Settings" />
        <IconButton icon="close" label="Close" disabled />
      </>,
    );
    const nodes = document.querySelectorAll(".cv-tooltip");
    expect(nodes).toHaveLength(1);
    const settings = within(host).getByRole("button", { name: "Settings" });
    await act(async () => settings.focus());
    expect(echo().hidden).toBe(false);
    expect(echo()).toHaveTextContent(/^Settings$/);
    expect(echo()).toHaveAttribute("aria-hidden", "true");
    expect(settings).not.toHaveAttribute("aria-describedby");
    expect(settings).toHaveAccessibleName("Settings");
  });

  it("a gate lifted while focused keeps the same focused control and drops the echo", async () => {
    let lift: () => void = () => undefined;
    function Host(): JSX.Element {
      const [reason, set] = useState<string | undefined>(REASON);
      lift = () => set(undefined);
      return <Button {...(reason === undefined ? {} : { disabledReason: reason })}>Save</Button>;
    }
    const host = await mount(<Host />);
    const button = within(host).getByRole("button", { name: "Save" });
    await act(async () => button.focus());
    expect(echo().hidden).toBe(false);
    await act(async () => lift());
    expect(within(host).getByRole("button", { name: "Save" })).toBe(button);
    expect(button).toHaveFocus();
    expect(button).not.toHaveAttribute("aria-disabled");
    expect(echoNode()).toBeNull();
  });
});
