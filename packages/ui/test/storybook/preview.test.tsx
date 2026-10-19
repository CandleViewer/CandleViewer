// @vitest-environment jsdom
import { act, useLayoutEffect, type JSX } from "react";
import { createRoot, type Root } from "react-dom/client";
import { composeStory, type Decorator } from "@storybook/react-vite";
import { afterEach, describe, expect, it, vi } from "vitest";
import preview from "../../.storybook/preview.js";

// The generated token CSS exists only after `build:tokens`; test/tokens-build checks those bundles.
vi.mock("../../.storybook/theme-bundles.js", () => ({}));

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
const rootData = document.documentElement.dataset;
let root: Root | undefined;
let mounts = 0;

function Probe(): JSX.Element {
  useLayoutEffect(() => void (mounts += 1), []);
  return <p>story</p>;
}

async function show(Story: () => JSX.Element): Promise<HTMLElement> {
  const host = document.body.appendChild(document.createElement("div"));
  root = createRoot(host);
  await act(async () => root?.render(<Story />));
  return host;
}

afterEach(async () => {
  await act(async () => root?.unmount());
  document.body.replaceChildren();
  mounts = 0;
});

describe("Storybook preview", () => {
  it("paints surface.app and drives the theme runtime from the toolbars, never remounting", async () => {
    const Story = composeStory(
      { render: () => <Probe /> },
      { title: "Foundations/Probe" },
      preview,
    );
    await show(Story);
    const { style } = document.body;
    expect([style.getPropertyValue("background-color"), style.getPropertyValue("color")]).toEqual([
      "var(--color-surface-app)",
      "var(--color-text-primary)",
    ]);
    expect([rootData["theme"], rootData["density"], rootData["motion"]]).toEqual([
      "dark",
      "compact",
      "safe",
    ]);
    const switches = [
      ["theme", "high-contrast", "theme", "high-contrast"],
      ["density", "comfortable", "density", "comfortable"],
      ["motion", "on", "motion", "reduce"],
    ] as const;
    for (const [global, value, attribute, expected] of switches) {
      Story.globals[global] = value; // what a toolbar click does: new globals, same story
      await act(async () => root?.render(<Story />));
      expect(rootData[attribute]).toBe(expected);
    }
    expect(mounts).toBe(1);
  });

  it("leaves the body's surface to the last story mounted, then clears it", async () => {
    const Story = composeStory(
      { render: () => <Probe /> },
      { title: "Foundations/Probe" },
      preview,
    );
    const { style } = document.body;
    const surface = () => [
      style.getPropertyValue("background-color"),
      style.getPropertyValue("color"),
    ];
    const roots = [1, 2].map(() =>
      createRoot(document.body.appendChild(document.createElement("div"))),
    );
    for (const each of roots) await act(async () => each.render(<Story />));
    await act(async () => roots[0]?.unmount());
    expect(surface()).toEqual(["var(--color-surface-app)", "var(--color-text-primary)"]);
    await act(async () => roots[1]?.unmount());
    expect(surface()).toEqual(["", ""]);
  });

  it("paints a docs page's inline story on its own root and leaves the page's body alone", async () => {
    // composeStory renders in the story view; an outermost decorator puts the chain in docs mode,
    // as a docs page's inline story is (Storybook's renderStoryToElement).
    const asDocs: Decorator = (Inner) => <Inner viewMode="docs" />;
    const decorators = [preview.decorators ?? []].flat();
    const Story = composeStory(
      { render: () => <Probe /> },
      { title: "Foundations/Probe" },
      { ...preview, decorators: [...decorators, asDocs] },
    );
    const host = await show(Story);
    const surface = host.querySelector("p")?.parentElement;
    expect(surface?.parentElement).toBe(host); // the wrapper is the story's root element
    expect([surface?.style.backgroundColor, surface?.style.color]).toEqual([
      "var(--color-surface-app)",
      "var(--color-text-primary)",
    ]);
    const { style } = document.body;
    expect([style.getPropertyValue("background-color"), style.getPropertyValue("color")]).toEqual([
      "",
      "",
    ]);
    expect(mounts).toBe(1);
  });

  it("fails a story on serious and critical axe violations, never on moderate or minor", () => {
    const gate = { test: "error", options: { impactLevels: ["critical", "serious"] } };
    expect(preview.parameters?.["a11y"]).toEqual(gate);
  });
});
