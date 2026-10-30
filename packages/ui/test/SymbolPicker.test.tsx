// @vitest-environment jsdom
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { composeStories } from "@storybook/react-vite";
import {
  act,
  createRef,
  useState,
  type JSX,
  type KeyboardEvent as ReactKeyboardEvent,
} from "react";
import { createRoot } from "react-dom/client";
import { expect, fireEvent, fn, userEvent, within } from "storybook/test";
import { describe, it } from "vitest";
import { Popover, SymbolPicker, TextInput, type SymbolPickerProps } from "../src/index.js";
import * as moleculeStories from "../src/components/AllMolecules.stories.js";
import * as stories from "../src/components/SymbolPicker.stories.js";
import { seriousViolations } from "./axe.js";
import { find, loadCss } from "./css-contract.js";
import { mount } from "./theme/mount.js";

const at = (over: Partial<SymbolPickerProps> = {}): SymbolPickerProps => ({
  value: "BTCUSDT",
  onOpen: fn(),
  ...over,
});
const page = (): ReturnType<typeof within> => within(document.body);
const trigger = (): HTMLElement => page().getByRole("button", { name: /^Symbol: / });
const chip = (host: HTMLElement): Element | null => host.querySelector(".cv-symbolpicker__chip");

describe("SymbolPicker (CMP-219, E08-D05 A-D05-4)", () => {
  it("is a button that opens a dialog, not a combobox, named from the value it draws", async () => {
    const host = await mount(<SymbolPicker {...at({ interval: "1 minute" })} />);
    const button = trigger();
    expect([button.tagName, button.getAttribute("type")]).toEqual(["BUTTON", "button"]);
    expect(button).toHaveAccessibleName("Symbol: BTCUSDT, 1 minute");
    expect([button.getAttribute("aria-haspopup"), button.getAttribute("aria-expanded")]).toEqual([
      "dialog",
      "false",
    ]);
    // The visible text is the value alone, inside the name (WCAG 2.5.3); the chevron is decorative.
    expect([button.textContent, button.getAttribute("aria-labelledby")]).toEqual(["BTCUSDT", null]);
    expect(page().queryByRole("combobox")).toBeNull();
    expect(button.querySelector("svg")).toHaveAttribute("aria-hidden", "true");
    expect(host.firstElementChild).toHaveAttribute("data-cmp", "CMP-219");
    expect(button).not.toHaveAttribute("aria-describedby");
  });

  it("without an interval (or a blank one) the name is the value alone", async () => {
    await mount(
      <>
        <SymbolPicker {...at()} />
        <SymbolPicker {...at({ value: "ETHUSDT", interval: " " })} />
      </>,
    );
    expect(page().getByRole("button", { name: "Symbol: BTCUSDT" })).toBeVisible();
    expect(page().getByRole("button", { name: "Symbol: ETHUSDT" })).toBeVisible();
  });

  it("a click, Enter and Space each call onOpen; a delisted value still opens", async () => {
    const onOpen = fn();
    await mount(<SymbolPicker {...at({ onOpen, delisted: true })} />);
    await userEvent.click(trigger());
    expect(trigger()).toHaveFocus();
    await userEvent.keyboard("{Enter}");
    await userEvent.keyboard(" ");
    expect(onOpen).toHaveBeenCalledTimes(3);
    expect(trigger()).not.toHaveAttribute("aria-disabled");
  });

  it("keeps the Enter and Space it handles from the shell's window keymap; the host's onKeyDown runs first", async () => {
    const seen: string[] = [];
    const listen = (event: KeyboardEvent): void => {
      const chord = `${event.ctrlKey ? "Ctrl+" : ""}${event.altKey ? "Alt+" : ""}${event.metaKey ? "Meta+" : ""}`;
      seen.push(`${chord}${event.key === " " ? "Space" : event.key}`);
    };
    // The host's handler runs before the trigger stops anything, so it never sees a stopped event.
    const stopped: boolean[] = [];
    const onKeyDown = (event: ReactKeyboardEvent<HTMLButtonElement>): void => {
      stopped.push(event.isPropagationStopped());
    };
    await mount(<SymbolPicker {...at({ onKeyDown })} />);
    window.addEventListener("keydown", listen);
    try {
      for (const init of [
        { key: "Enter" },
        { key: " " },
        { key: "/" },
        { key: "Enter", ctrlKey: true },
        { key: "Enter", altKey: true },
        { key: " ", metaKey: true },
      ])
        await act(async () => void fireEvent.keyDown(trigger(), init));
    } finally {
      window.removeEventListener("keydown", listen);
    }
    expect(seen).toEqual(["/", "Ctrl+Enter", "Alt+Enter", "Meta+Space"]);
    expect(stopped).toEqual([false, false, false, false, false, false]);
  });

  it("keeps the button's role: role is no prop, and one passed past the type never lands", async () => {
    // @ts-expect-error -- `role` is left out of the props: the trigger is a button (A-D05-4), never a combobox.
    await mount(<SymbolPicker {...at()} role="combobox" />);
    expect(page().queryByRole("combobox")).toBeNull();
    expect(trigger()).not.toHaveAttribute("role");
  });

  it("drops a host's aria-labelledby, aria-disabled, aria-pressed, disabled and style at run time (CR-ORCH-5028-4)", async () => {
    // Left out by type too; a JavaScript or spread caller still reaches the props, and none may land.
    const passed = { "aria-labelledby": "x", "aria-disabled": true, "aria-pressed": true };
    const more = { disabled: true, style: { display: "none" } };
    await mount(<SymbolPicker {...at()} {...(passed as object)} {...(more as object)} />);
    expect(trigger()).toHaveAccessibleName("Symbol: BTCUSDT"); // WCAG 2.5.3: the drawn value names it
    for (const name of [...Object.keys(passed), ...Object.keys(more)])
      expect(trigger()).not.toHaveAttribute(name);
  });

  it("CMP-039's ring and a control-height target: 24 px compact, 32 comfortable (CR-ORCH-5028-3)", async () => {
    await mount(<SymbolPicker {...at()} />);
    expect(trigger()).toHaveClass("cv-control", "cv-focus-ring", "cv-symbolpicker__trigger");
    // jsdom lays nothing out: `.cv-control` holds the box at the density's control height, 24 or 32 px.
    const control = find(loadCss("controls.css").normal, ".cv-control", "min-height");
    expect(control).toContain("min-height: var(--size-control-height)");
    expect(control).toContain("min-width: var(--size-control-height)");
    const tokens = JSON.parse(
      readFileSync(resolve(import.meta.dirname, "../tokens/primitives.tokens.json"), "utf8"),
    ) as Record<string, { $value: string }>;
    expect([
      tokens["size.control.compact"]?.$value,
      tokens["size.control.comfortable"]?.$value,
    ]).toEqual(["24", "32"]);
  });

  it("forwards its ref to the button, for CMP-221's roving toolbar (a ref object or a callback)", async () => {
    const ref = createRef<HTMLButtonElement>();
    const roving: (HTMLElement | null)[] = [];
    await mount(
      <>
        <SymbolPicker {...at()} ref={ref} />
        <SymbolPicker {...at({ value: "ETHUSDT" })} ref={(node) => void roving.push(node)} />
      </>,
    );
    expect(ref.current).toBe(page().getByRole("button", { name: "Symbol: BTCUSDT" }));
    expect(roving).toEqual([page().getByRole("button", { name: "Symbol: ETHUSDT" })]);
  });

  it.each([
    ["recording", "Recording"],
    ["not-recorded", "Not recorded"],
  ] as const)(
    "recording=%s: the chip says %j beside the button and describes it",
    async (recording, words) => {
      const host = await mount(<SymbolPicker {...at({ recording })} />);
      expect(trigger()).toHaveAccessibleDescription(words);
      expect(trigger().contains(chip(host))).toBe(false);
      expect(chip(host)).toHaveTextContent(words);
      expect(chip(host)).toHaveAttribute("data-marker", recording);
      // One dot: symbolpicker.css fills it by the marker.
      expect(host.querySelectorAll(".cv-symbolpicker__dot")).toHaveLength(1);
    },
  );

  it("recording unknown (the default) shows no chip and no description: unknown is never 'not recorded'", async () => {
    const host = await mount(<SymbolPicker {...at({ recording: "unknown" })} />);
    expect([chip(host), trigger().getAttribute("aria-describedby")]).toEqual([null, null]);
    expect(host).not.toHaveTextContent(/record/i);
  });

  it("delisted: the value struck, the delisted chip in the recording chip's place, one marker only", async () => {
    const host = await mount(
      <SymbolPicker {...at({ value: "LUNAUSDT", delisted: true, recording: "recording" })} />,
    );
    expect(trigger()).toHaveAttribute("data-delisted");
    expect(trigger()).toHaveAccessibleName("Symbol: LUNAUSDT");
    expect(trigger()).toHaveAccessibleDescription("Delisted by the exchange");
    expect(host.querySelectorAll(".cv-symbolpicker__chip")).toHaveLength(1);
    expect(chip(host)).toHaveAttribute("data-marker", "delisted");
    expect(chip(host)?.querySelector("svg")).toHaveAttribute("aria-hidden", "true");
    expect(host.querySelector(".cv-symbolpicker__dot")).toBeNull();
  });

  it("passes a host's id, tabIndex (CMP-221's roving stop), aria-controls and description; sets density", async () => {
    const host = await mount(
      <>
        <span id="hint">Press slash on a chart.</span>
        <SymbolPicker
          {...at({ recording: "not-recorded", density: "comfortable" })}
          id="chart-1-symbol"
          tabIndex={-1}
          aria-controls="chart-1-switcher"
          aria-describedby="hint"
        />
      </>,
    );
    const button = trigger();
    expect([button.id, button.tabIndex, button.getAttribute("aria-controls")]).toEqual([
      "chart-1-symbol",
      -1,
      "chart-1-switcher",
    ]);
    expect(button).toHaveAccessibleDescription("Press slash on a chart. Not recorded");
    expect(host.querySelector('[data-cmp="CMP-219"]')).toHaveAttribute(
      "data-density",
      "comfortable",
    );
  });

  it("axe: no serious or critical violation at rest, recording, not recorded, delisted and expanded", async () => {
    const host = await mount(
      <>
        <SymbolPicker {...at()} />
        <SymbolPicker {...at({ recording: "recording" })} />
        <SymbolPicker {...at({ recording: "not-recorded" })} />
        <SymbolPicker {...at({ value: "LUNAUSDT", delisted: true })} />
        <SymbolPicker {...at({ expanded: true })} />
      </>,
    );
    expect(await seriousViolations(host)).toEqual([]);
  });
});

describe("SymbolPicker as a CMP-017 Popover's anchor", () => {
  it("takes the Popover's state and toggle, so its host wires none: a press opens it, the next closes it", async () => {
    const onOpen = fn();
    await mount(
      <Popover heading="Change symbol and interval" anchor={<SymbolPicker {...at({ onOpen })} />}>
        <TextInput aria-label="Search symbols" />
      </Popover>,
    );
    expect(trigger()).toHaveAttribute("aria-expanded", "false");
    await act(async () => userEvent.click(trigger()));
    const dialog = page().getByRole("dialog", { name: "Change symbol and interval" });
    expect([
      trigger().getAttribute("aria-expanded"),
      trigger().getAttribute("aria-controls"),
    ]).toEqual(["true", dialog.id]);
    expect(within(dialog).getByRole("textbox")).toHaveFocus();
    // A press on the open trigger closes it (CMP-017's toggle), and focus stays on the trigger.
    await act(async () => userEvent.click(trigger()));
    expect([dialog.hidden, trigger().getAttribute("aria-expanded")]).toEqual([true, "false"]);
    expect(trigger()).toHaveFocus();
    expect(onOpen).toHaveBeenCalledTimes(2);
  });

  it("onOpen runs before the Popover's toggle: a controlled host that opens in onOpen still closes on the next press (CR-B2BD-02)", async () => {
    function Controlled(): JSX.Element {
      const [open, setOpen] = useState(false);
      return (
        <Popover
          heading="Change symbol and interval"
          open={open}
          onOpenChange={setOpen}
          anchor={<SymbolPicker {...at({ onOpen: () => setOpen(true) })} />}
        >
          <TextInput aria-label="Search symbols" />
        </Popover>
      );
    }
    await mount(<Controlled />);
    await act(async () => userEvent.click(trigger()));
    const dialog = page().getByRole("dialog", { name: "Change symbol and interval" });
    expect(dialog.hidden).toBe(false);
    // onOpen's `true`, then the toggle's `false`: the last write wins, so the press closes it.
    await act(async () => userEvent.click(trigger()));
    expect([dialog.hidden, trigger().getAttribute("aria-expanded")]).toEqual([true, "false"]);
  });

  it("the Popover's state wins over a host's expanded; any other host's expanded sets aria-expanded", async () => {
    await mount(
      <>
        <Popover
          heading="Change symbol and interval"
          defaultOpen
          anchor={<SymbolPicker {...at({ expanded: false })} />}
        >
          <TextInput aria-label="Search symbols" />
        </Popover>
        <SymbolPicker {...at({ value: "ETHUSDT", expanded: true })} />
        <Popover
          heading="Closed"
          anchor={<SymbolPicker {...at({ value: "SOLUSDT", expanded: true })} />}
        >
          <TextInput aria-label="Search" />
        </Popover>
      </>,
    );
    for (const name of ["Symbol: BTCUSDT", "Symbol: ETHUSDT"])
      expect(page().getByRole("button", { name })).toHaveAttribute("aria-expanded", "true");
    // Both ways (CR-ORCH-5028-2): a closed Popover's `false` wins over a host's `expanded`.
    expect(page().getByRole("button", { name: "Symbol: SOLUSDT" })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
  });

  it("the Expanded story's host passes no expanded: Esc closes it, focus returns, a press reopens it", async () => {
    const { Expanded } = composeStories(stories);
    await mount(<Expanded />);
    const dialog = page().getByRole("dialog", { name: "Change symbol and interval" });
    expect(trigger()).toHaveAttribute("aria-controls", dialog.id);
    expect(within(dialog).getByRole("textbox")).toHaveFocus();
    await act(
      async () => void fireEvent.keyDown(within(dialog).getByRole("textbox"), { key: "Escape" }),
    );
    expect([dialog.hidden, trigger().getAttribute("aria-expanded")]).toEqual([true, "false"]);
    expect(trigger()).toHaveFocus();
    await act(async () => userEvent.keyboard("{Enter}"));
    expect([dialog.hidden, trigger().getAttribute("aria-expanded")]).toEqual([false, "true"]);
  });
});

/**
 * axe's label-content-name-mismatch (WCAG 2.5.3) runs in CI's Chromium only: jsdom has no layout to tell what is on
 * screen. Here the words drawn in each trigger (its text outside `.cv-visually-hidden`, joined as axe joins it, then
 * letters and digits only, lower case) must be one run of its name's words, in order, in every story.
 */
const onScreen = (node: Node): string =>
  [...node.childNodes]
    .map((child) => {
      if (child.nodeType === Node.TEXT_NODE) return child.nodeValue ?? "";
      if (!(child instanceof Element) || child.matches(".cv-visually-hidden")) return "";
      return onScreen(child);
    })
    .join("");
const words = (text: string): string[] =>
  text
    .normalize("NFKD")
    .toLowerCase()
    .replace(/[^\p{L}\p{N}]+/gu, " ")
    .split(" ")
    .filter(Boolean);

/** The trigger buttons `ui` draws ("Symbol: …"; a page's other buttons are not this check's), each "" when held. */
const drawn = async (ui: JSX.Element): Promise<string[]> => {
  const host = document.body.appendChild(document.createElement("div"));
  const root = createRoot(host);
  await act(async () => root.render(ui));
  try {
    const names = new Map<Element, string>();
    within(host).queryAllByRole("button", {
      name: (name, element) => {
        if (name.startsWith("Symbol: ")) names.set(element, name);
        return true;
      },
    });
    return [...names].map(([button, name]) => {
      const [seen, all] = [words(onScreen(button)), words(name)];
      const held = all.some((_, from) => seen.every((word, i) => all[from + i] === word));
      return seen.length > 0 && held ? "" : `"${onScreen(button)}" ≠ "${name}"`;
    });
  } finally {
    await act(async () => root.unmount());
    host.remove();
  }
};

it("every story's trigger holds the words it draws, in order, in its name (label-content-name-mismatch)", async () => {
  const found: string[] = [];
  for (const [name, Story] of Object.entries(composeStories(stories))) {
    const checked = await drawn(<Story />);
    expect(checked.length, name).toBeGreaterThan(0);
    found.push(...checked.filter(Boolean).map((miss) => `${name}: ${miss}`));
  }
  expect(found).toEqual([]);
  // The check bites: a label holding the symbol alone, beside a value drawn with its chip, is a mismatch.
  const misnamed = await drawn(
    <button type="button" aria-label="Symbol: BTCUSDT">
      BTCUSDT Recording
    </button>,
  );
  expect(misnamed).toEqual(['"BTCUSDT Recording" ≠ "Symbol: BTCUSDT"']);
});

it("the theme x density matrix (15 §0.3 rule 7) holds B02's five triggers, each naming the words it draws", async () => {
  // The matrix draws one page in every theme and density: its first story holds every cell the others do.
  const { DarkCompact } = composeStories(moleculeStories);
  expect(await drawn(<DarkCompact />)).toEqual(["", "", "", "", ""]);
});

// One test: each story's play in turn (the storybook project runs them in Chromium); the theme and density stories
// are skipped, as their plays wait on the preview's theme runtime, which only that project loads.
it("runs each SymbolPicker story's play function", { timeout: 20_000 }, async () => {
  for (const [name, Story] of Object.entries(composeStories(stories))) {
    if (Story.globals["theme"] !== undefined || Story.globals["density"] !== undefined) continue;
    const canvasElement = document.body.appendChild(document.createElement("div"));
    await expect(Story.run({ canvasElement }), name).resolves.toBeUndefined();
    canvasElement.remove();
  }
});
