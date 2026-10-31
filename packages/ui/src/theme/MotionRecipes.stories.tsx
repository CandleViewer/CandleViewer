import { useState, type CSSProperties, type JSX } from "react";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, userEvent, within } from "storybook/test";

/*
 * The motion recipes of E05-D03 section 2, each shown in both modes. A recipe is the pair
 * `--cv-recipe-<name>-safe` / `--cv-recipe-<name>-reduce` in theme.css; the pair is bound directly here, so the
 * two modes sit side by side whatever the toolbar says. The third column binds the resolved
 * `--cv-recipe-<name>`, which follows `data-motion` (the Reduced motion toolbar flips it).
 */

type Kind = "animation" | "transition";
interface Recipe {
  readonly name: string;
  readonly row: string;
  readonly what: string;
  readonly kind: Kind;
  /** What the demo box becomes while "on" (transitions only). */
  readonly on?: CSSProperties;
}

const RECIPES: readonly Recipe[] = [
  {
    name: "panel-in",
    row: "1",
    what: "Panel focus / mount: opacity and translateY(8px)",
    kind: "animation",
  },
  { name: "dialog-scrim-in", row: "2a", what: "Dialog scrim in", kind: "animation" },
  {
    name: "fade-out",
    row: "2a, 2b",
    what: "Dialog and drawer-scrim exit",
    kind: "transition",
    on: { opacity: 0 },
  },
  { name: "drawer-in", row: "2b", what: "Drawer in from the right", kind: "animation" },
  { name: "drawer-in-left", row: "2b", what: "Drawer in from the left", kind: "animation" },
  { name: "drawer-scrim-in", row: "2b", what: "Drawer scrim in", kind: "animation" },
  {
    name: "drawer-out",
    row: "2b",
    what: "Drawer exit",
    kind: "transition",
    on: { transform: "translateX(100%)" },
  },
  { name: "value-flash", row: "3", what: "Value-flash overlay, peak to 0", kind: "animation" },
  { name: "toast-in", row: "4a", what: "Toast enter", kind: "animation" },
  { name: "toast-out", row: "4a", what: "Toast exit", kind: "animation" },
  {
    name: "toast-shift",
    row: "4b",
    what: "Older toasts move to their slots",
    kind: "transition",
    on: { transform: "translateY(var(--space-inset-sm))" },
  },
  { name: "edge-in", row: "5a", what: "Node-graph connection made", kind: "animation" },
  {
    name: "layout-move",
    row: "5b",
    what: "Node-graph auto-layout",
    kind: "transition",
    on: { transform: "translateX(var(--space-inset-lg))" },
  },
  {
    name: "skeleton-sweep",
    row: "6",
    what: "Loading shimmer: 4 sweeps, then static",
    kind: "animation",
  },
  {
    name: "spinner",
    row: "7",
    what: "Busy spinner (the request-bound exception)",
    kind: "animation",
  },
];

const box = (recipe: Recipe, variable: string, on: boolean): CSSProperties => ({
  inlineSize: "var(--size-control-height)",
  blockSize: "var(--size-control-height)",
  background:
    recipe.name === "value-flash"
      ? "var(--color-buy-default)"
      : "var(--color-action-primary-default)",
  borderRadius: "var(--radius-control)",
  ...(recipe.kind === "animation"
    ? { animation: `var(${variable})` }
    : { transition: `var(${variable})`, ...(on ? recipe.on : {}) }),
});

function Cell(props: {
  recipe: Recipe;
  mode: "safe" | "reduce" | "resolved";
  on: boolean;
}): JSX.Element {
  const { recipe, mode, on } = props;
  const variable =
    mode === "resolved" ? `--cv-recipe-${recipe.name}` : `--cv-recipe-${recipe.name}-${mode}`;
  return (
    <td style={{ padding: "var(--space-inset-sm)", overflow: "hidden" }}>
      <div
        aria-hidden="true"
        data-recipe={recipe.name}
        data-mode={mode}
        style={box(recipe, variable, on)}
      />
    </td>
  );
}

function Recipes(): JSX.Element {
  const [run, setRun] = useState(0);
  const [on, setOn] = useState(false);
  return (
    <section
      aria-label="Motion recipes"
      style={{
        background: "var(--color-surface-app)",
        color: "var(--color-text-primary)",
        fontFamily: "var(--font-family-ui), system-ui, sans-serif",
        padding: "var(--space-inset-md)",
      }}
    >
      <p>
        Each recipe is a pair of custom properties in theme.css; the reduce value is literally none.
      </p>
      <p style={{ display: "flex", gap: "var(--space-inset-sm)" }}>
        <button type="button" onClick={() => setRun((n) => n + 1)}>
          Replay animations
        </button>
        <button type="button" aria-pressed={on} onClick={() => setOn((v) => !v)}>
          Toggle transitions
        </button>
      </p>
      <table key={run} style={{ borderCollapse: "collapse" }}>
        <thead>
          <tr>
            <th scope="col">Recipe</th>
            <th scope="col">E05-D03 row</th>
            <th scope="col">Safe</th>
            <th scope="col">Reduce</th>
            <th scope="col">Resolved (follows data-motion)</th>
          </tr>
        </thead>
        <tbody>
          {RECIPES.map((recipe) => (
            <tr key={recipe.name}>
              <th scope="row" style={{ textAlign: "start" }}>
                {recipe.name}
                <br />
                <small style={{ color: "var(--color-text-secondary)" }}>{recipe.what}</small>
              </th>
              <td>{recipe.row}</td>
              <Cell recipe={recipe} mode="safe" on={on} />
              <Cell recipe={recipe} mode="reduce" on={on} />
              <Cell recipe={recipe} mode="resolved" on={on} />
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

const meta: Meta = {
  title: "Foundations/Motion recipes",
  parameters: { layout: "fullscreen" },
};
export default meta;
type Story = StoryObj;

const cell = (root: HTMLElement, name: string, mode: string): HTMLElement => {
  const found = root.querySelector<HTMLElement>(`[data-recipe="${name}"][data-mode="${mode}"]`);
  if (found === null) throw new Error(`no ${mode} cell for ${name}`);
  return found;
};

/**
 * Per recipe: the safe value is a real animation or transition and the reduce value is `none`. Read from the
 * pair itself, not the cells' computed style, so the check holds whatever `data-motion` the host sets (the VR
 * capture emulates OS reduce, which stops every animation on the page).
 */
export const SafeAndReduce: Story = {
  render: () => <Recipes />,
  play: async ({ canvasElement }) => {
    const root = getComputedStyle(canvasElement.ownerDocument.documentElement);
    for (const recipe of RECIPES) {
      cell(canvasElement, recipe.name, "safe");
      const safe = root.getPropertyValue(`--cv-recipe-${recipe.name}-safe`).trim();
      const reduce = root.getPropertyValue(`--cv-recipe-${recipe.name}-reduce`).trim();
      await expect(safe, recipe.name).not.toBe("");
      await expect(safe, recipe.name).not.toBe("none");
      await expect(reduce, recipe.name).toBe("none");
    }
  },
};

/** The resolved variable follows `data-motion`: the safe value under safe, none under reduce, and back. */
export const ResolvedFollowsDataMotion: Story = {
  render: () => <Recipes />,
  play: async ({ canvasElement }) => {
    const root = document.documentElement;
    const before = root.getAttribute("data-motion");
    const names = (mode: string): (string | undefined)[] =>
      RECIPES.filter((r) => r.kind === "animation").map(
        (r) => getComputedStyle(cell(canvasElement, r.name, mode)).animationName,
      );
    try {
      root.setAttribute("data-motion", "safe");
      await expect(names("resolved")).toEqual(names("safe"));
      root.setAttribute("data-motion", "reduce");
      await expect(names("resolved").every((n) => n === "none")).toBe(true);
      await expect(getComputedStyle(root).getPropertyValue("--cv-motion-scale").trim()).toBe("0");
      root.setAttribute("data-motion", "safe");
      await expect(getComputedStyle(root).getPropertyValue("--cv-motion-scale").trim()).toBe("1");
    } finally {
      if (before === null) root.removeAttribute("data-motion");
      else root.setAttribute("data-motion", before);
    }
    await userEvent.click(
      within(canvasElement).getByRole("button", { name: "Toggle transitions" }),
    );
    await expect(
      within(canvasElement).getByRole("button", { name: "Toggle transitions" }),
    ).toHaveAttribute("aria-pressed", "true");
  },
};

const G1_CLASSES = [
  "cv-toast",
  "cv-dialog__scrim",
  "cv-drawer",
  "cv-drawer__scrim",
  "cv-select__popup",
];

/**
 * E05-D03 G-1: the four components that gated their entrance on the OS query follow `data-motion` only. Under
 * an explicit `safe` they animate, under `reduce` they do not, whatever the OS says.
 */
export const EntranceFollowsDataMotion: Story = {
  render: () => (
    <section aria-label="Entrance motion" style={{ color: "var(--color-text-primary)" }}>
      <p>Components whose entrance follows data-motion (decorative specimens).</p>
      {G1_CLASSES.map((name) => (
        <div
          key={name}
          aria-hidden="true"
          className={name}
          data-g1={name}
          style={{ position: "static" }}
        />
      ))}
    </section>
  ),
  play: async ({ canvasElement }) => {
    const root = document.documentElement;
    const before = root.getAttribute("data-motion");
    const animated = (): Record<string, string> =>
      Object.fromEntries(
        G1_CLASSES.map((name) => [
          name,
          getComputedStyle(canvasElement.querySelector(`[data-g1="${name}"]`) as Element)
            .animationName,
        ]),
      );
    try {
      root.setAttribute("data-motion", "safe");
      for (const [name, animation] of Object.entries(animated())) {
        await expect(animation, name).not.toBe("none");
      }
      root.setAttribute("data-motion", "reduce");
      for (const [name, animation] of Object.entries(animated())) {
        await expect(animation, name).toBe("none");
      }
    } finally {
      if (before === null) root.removeAttribute("data-motion");
      else root.setAttribute("data-motion", before);
    }
  },
};
