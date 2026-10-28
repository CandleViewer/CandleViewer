// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest";
import { tabStopAfter, tabbables } from "../src/components/internal/tabbable.js";

afterEach(() => document.body.replaceChildren());

/**
 * One element built node by node, so no markup is parsed: its attributes (a boolean one such as
 * `disabled` takes ""), then its text or its child elements.
 */
const el = (
  tag: string,
  attributes: Readonly<Record<string, string>> = {},
  content: string | readonly HTMLElement[] = [],
): HTMLElement => {
  const element = document.createElement(tag);
  for (const [name, value] of Object.entries(attributes)) element.setAttribute(name, value);
  if (typeof content === "string") element.textContent = content;
  else element.append(...content);
  return element;
};
/** A fresh root in the body that holds `children`, in order. */
const fixture = (...children: HTMLElement[]): HTMLElement => {
  const root = document.body.appendChild(document.createElement("div"));
  root.append(...children);
  return root;
};
const names = (elements: HTMLElement[]): string[] =>
  elements.map((element) => element.dataset["n"] ?? "?");

describe("tabbables", () => {
  it("keeps tab stops in DOM order: links, controls, tabindex 0; contenteditable=false is none", () => {
    const root = fixture(
      el("a", { "data-n": "link", href: "#x" }, "x"),
      el("a", { "data-n": "no-href" }, "y"),
      el("button", { "data-n": "button" }, "b"),
      el("input", { "data-n": "input" }),
      el("input", { "data-n": "hidden-input", type: "hidden" }),
      el("select", { "data-n": "select" }),
      el("textarea", { "data-n": "textarea" }),
      el("div", { "data-n": "zero", tabindex: "0" }),
      el("div", { "data-n": "no-edit", contenteditable: "false" }),
    );
    expect(names(tabbables(root))).toEqual([
      "link",
      "button",
      "input",
      "select",
      "textarea",
      "zero",
    ]);
  });

  it("drops disabled controls, those in a disabled fieldset, and tabindex=-1", () => {
    const root = fixture(
      el("button", { "data-n": "off", disabled: "" }, "a"),
      el("fieldset", { disabled: "" }, [el("input", { "data-n": "in-fieldset" })]),
      el("button", { "data-n": "roving", tabindex: "-1" }, "r"),
      el("button", { "data-n": "t2", "aria-disabled": "true" }, "t2"),
    );
    expect(names(tabbables(root))).toEqual(["t2"]);
  });

  it("drops elements under a hidden or inert ancestor", () => {
    const root = fixture(
      el("div", { hidden: "" }, [el("button", { "data-n": "hidden" }, "h")]),
      el("div", { inert: "" }, [el("button", { "data-n": "inert" }, "i")]),
      el("button", { "data-n": "seen" }, "s"),
    );
    expect(names(tabbables(root))).toEqual(["seen"]);
  });
});

describe("tabStopAfter", () => {
  it("finds the next stop after an element, skipping its own subtree and a given node", () => {
    const root = fixture(
      el("button", { "data-n": "from" }, [el("span", { tabindex: "0", "data-n": "inner" })]),
      el("div", { "data-n": "skip" }, [el("button", { "data-n": "skipped" }, "s")]),
      el("button", { "data-n": "next" }, "n"),
    );
    const from = root.querySelector<HTMLElement>("[data-n=from]");
    const skip = root.querySelector("[data-n=skip]");
    if (from === null) throw new Error("no from");
    expect(tabStopAfter(from, skip)?.dataset["n"]).toBe("next");
    expect(tabStopAfter(from, null)?.dataset["n"]).toBe("skipped");
  });

  it("is undefined when nothing follows", () => {
    const root = fixture(el("button", { "data-n": "only" }, "o"));
    const only = root.querySelector<HTMLElement>("button");
    if (only === null) throw new Error("no button");
    expect(tabStopAfter(only, null)).toBeUndefined();
  });
});
