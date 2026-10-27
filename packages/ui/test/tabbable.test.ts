// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest";
import { tabStopAfter, tabbables } from "../src/components/internal/tabbable.js";

afterEach(() => document.body.replaceChildren());

const html = (markup: string): HTMLElement => {
  const root = document.body.appendChild(document.createElement("div"));
  root.innerHTML = markup;
  return root;
};
const names = (elements: HTMLElement[]): string[] =>
  elements.map((element) => element.dataset["n"] ?? "?");

describe("tabbables", () => {
  it("keeps tab stops in DOM order: links, controls, tabindex 0; contenteditable=false is none", () => {
    const root = html(`
      <a data-n="link" href="#x">x</a><a data-n="no-href">y</a>
      <button data-n="button">b</button><input data-n="input" />
      <input data-n="hidden-input" type="hidden" />
      <select data-n="select"></select><textarea data-n="textarea"></textarea>
      <div data-n="zero" tabindex="0"></div>
      <div data-n="no-edit" contenteditable="false"></div>`);
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
    const root = html(`
      <button data-n="off" disabled>a</button>
      <fieldset disabled><input data-n="in-fieldset" /></fieldset>
      <button data-n="roving" tabindex="-1">r</button>
      <button data-n="t2" aria-disabled="true">t2</button>`);
    expect(names(tabbables(root))).toEqual(["t2"]);
  });

  it("drops elements under a hidden or inert ancestor", () => {
    const root = html(`
      <div hidden><button data-n="hidden">h</button></div>
      <div inert><button data-n="inert">i</button></div>
      <button data-n="seen">s</button>`);
    expect(names(tabbables(root))).toEqual(["seen"]);
  });
});

describe("tabStopAfter", () => {
  it("finds the next stop after an element, skipping its own subtree and a given node", () => {
    const root = html(`
      <button data-n="from"><span tabindex="0" data-n="inner"></span></button>
      <div data-n="skip"><button data-n="skipped">s</button></div>
      <button data-n="next">n</button>`);
    const from = root.querySelector<HTMLElement>("[data-n=from]");
    const skip = root.querySelector("[data-n=skip]");
    if (from === null) throw new Error("no from");
    expect(tabStopAfter(from, skip)?.dataset["n"]).toBe("next");
    expect(tabStopAfter(from, null)?.dataset["n"]).toBe("skipped");
  });

  it("is undefined when nothing follows", () => {
    const root = html(`<button data-n="only">o</button>`);
    const only = root.querySelector<HTMLElement>("button");
    if (only === null) throw new Error("no button");
    expect(tabStopAfter(only, null)).toBeUndefined();
  });
});
