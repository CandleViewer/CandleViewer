// @vitest-environment jsdom
import { composeStories } from "@storybook/react-vite";
import { expect } from "storybook/test";
import { describe, it } from "vitest";
import { Kbd, kbdExpansion } from "../src/components/index.js";
import * as stories from "../src/components/Kbd.stories.js";
import { mount } from "./theme/mount.js";

const caps = (host: HTMLElement): string[] =>
  [...host.querySelectorAll(".cv-kbd__cap")].map((c) => c.textContent ?? "");

describe("Kbd (CMP-022)", () => {
  it("renders one kbd cap per key inside an outer kbd, caps hidden, read once", async () => {
    const host = await mount(<Kbd keys={["Ctrl", "Shift", "K"]} />);
    const outer = host.querySelector("kbd.cv-kbd");
    expect(outer?.getAttribute("data-cmp")).toBe("CMP-022");
    expect(caps(host)).toEqual(["Ctrl", "Shift", "K"]);
    expect(outer?.querySelectorAll("kbd.cv-kbd__cap")).toHaveLength(3);
    expect(host.querySelector(".cv-kbd__caps")).toHaveAttribute("aria-hidden", "true");
    expect(host.querySelector(".cv-visually-hidden")).toHaveTextContent(
      /^Control plus Shift plus K$/,
    );
    expect(outer?.textContent).not.toContain("+");
    expect(outer).not.toHaveAttribute("tabindex");
  });

  it.each([[[]], [[""]], [["  ", ""]]])("renders nothing when unbound (%j)", async (keys) => {
    const host = await mount(<Kbd keys={keys} />);
    expect(host).toBeEmptyDOMElement();
  });

  it("renders a digit range as two caps with an en dash", async () => {
    const host = await mount(<Kbd keys={["Alt", "1..9"]} />);
    expect(caps(host)).toEqual(["Alt", "1", "9"]);
    expect(host.querySelector(".cv-kbd__range .cv-kbd__word")).toHaveTextContent(/^–$/);
    expect(host.querySelector(".cv-visually-hidden")).toHaveTextContent(/^Alt plus 1 to 9$/);
  });

  it.each([
    [["Ctrl", "click"], "click", "Control plus click"],
    [["Shift", "wheel"], "wheel", "Shift plus wheel"],
    [["Space", "drag"], "drag", "Space plus drag"],
  ])("renders the pointer chord %j as caps plus the word as text", async (keys, word, spoken) => {
    const host = await mount(<Kbd keys={keys} />);
    expect(caps(host)).toEqual([keys[0]]);
    expect(host.querySelector(".cv-kbd__word")).toHaveTextContent(word);
    expect(host.querySelector(".cv-visually-hidden")).toHaveTextContent(spoken);
  });

  it("takes the keymap's name table over the catalogue's words", () => {
    expect(kbdExpansion(["Ctrl", "Del"], { Del: "Delete" })).toBe("Control plus Delete");
    expect(kbdExpansion(["Ctrl", "K"], { Ctrl: "Command" })).toBe("Command plus K");
  });

  it("can be hidden whole inside a menu item, which carries aria-keyshortcuts", async () => {
    const host = await mount(<Kbd keys={["Ctrl", "S"]} aria-hidden="true" />);
    expect(host.querySelector(".cv-kbd")).toHaveAttribute("aria-hidden", "true");
  });
});

describe("Kbd stories", () => {
  it.each(Object.entries(composeStories(stories)))("%s renders", async (name, Story) => {
    const host = await mount(<Story />);
    expect(host.querySelector(".cv-kbd") === null).toBe(name === "Unbound");
  });
});
