// @vitest-environment jsdom
import { expect, userEvent, within } from "storybook/test";
import { describe, it, vi } from "vitest";
import {
  PREVIEW_TILE_CONTRAST_PAIRS,
  PREVIEW_TILE_COPY,
  PreviewTile,
  type PreviewTileProps,
} from "../src/components/index.js";
import { seriousViolations } from "./axe.js";
import { mount } from "./theme/mount.js";

const LABEL = "Preview: BTCUSDT 1 minute, logarithmic scale, UTC";
const tile = (props: Partial<PreviewTileProps> = {}) => <PreviewTile label={LABEL} {...props} />;
const [BODY, SECONDARY] = PREVIEW_TILE_CONTRAST_PAIRS.pairs;
const root = (host: HTMLElement): HTMLElement =>
  host.querySelector<HTMLElement>('[data-cmp="CMP-228"]') ?? host;

describe("PreviewTile (CMP-228)", () => {
  it("live: one img named by the configuration, never focusable, no live region", async () => {
    const host = await mount(tile({ children: <span>bars</span> }));
    const img = within(host).getByRole("img", { name: LABEL });
    expect(img).toHaveAttribute("aria-live", "off");
    expect(img).not.toHaveAttribute("tabindex");
    expect(root(host).dataset["state"]).toBe("live");
    expect(root(host).dataset["kind"]).toBe("candles");
    expect(img).toHaveTextContent("bars");
  });

  it("Tab passes the tile: it is not interactive", async () => {
    const host = await mount(
      <>
        <button type="button">Before</button>
        {tile({ kind: "theme" })}
        <button type="button">After</button>
      </>,
    );
    within(host).getByRole("button", { name: "Before" }).focus();
    await userEvent.tab();
    expect(within(host).getByRole("button", { name: "After" })).toHaveFocus();
  });

  it("sample: the visible 'not this chart' line outside the image", async () => {
    const host = await mount(tile({ source: "sample" }));
    expect(root(host).dataset["state"]).toBe("sample");
    const note = within(host).getByText(PREVIEW_TILE_COPY.sample);
    expect(within(host).getByRole("img")).not.toContainElement(note);
  });

  it("empty: named 'Preview unavailable', the reason in visible text, the host image dropped", async () => {
    const host = await mount(tile({ status: "empty", children: <span>host image</span> }));
    const img = within(host).getByRole("img", { name: PREVIEW_TILE_COPY.unavailable });
    expect(img).toHaveTextContent(PREVIEW_TILE_COPY.empty);
    expect(img).toHaveAccessibleDescription(PREVIEW_TILE_COPY.empty);
    expect(img).not.toHaveTextContent("host image");
    expect(root(host).dataset["state"]).toBe("empty");
  });

  it("error: named 'Preview unavailable', glyph plus words, never a spinner", async () => {
    const host = await mount(tile({ status: "error", errorText: "Chart failed" }));
    const img = within(host).getByRole("img", { name: PREVIEW_TILE_COPY.unavailable });
    expect(img).toHaveTextContent("Chart failed");
    expect(img).toHaveAccessibleDescription("Chart failed");
    expect(img.querySelector("svg")).not.toBeNull();
    expect(host.querySelector('[role="progressbar"], [role="status"]')).toBeNull();
  });

  it("ladder: the value as text; an array is the collapsed form joined by ' · '", async () => {
    const one = await mount(tile({ kind: "ladder", value: "2.500 BTC", caption: "Total qty" }));
    expect(within(one).getByRole("img")).toHaveTextContent("2.500 BTC");
    expect(within(one).getByRole("img")).not.toHaveAttribute("aria-describedby");
    expect(within(one).getByText("Total qty").tagName).toBe("P");
    document.body.replaceChildren();
    const many = await mount(tile({ kind: "ladder", value: ["2.500 BTC", "64,180.2"] }));
    expect(root(many).dataset["state"]).toBe("collapsed");
    expect(within(many).getByRole("img")).toHaveTextContent("2.500 BTC · 64,180.2");
  });

  it("theme: the built-in sample rows say bid, ask and position in words beside the swatches", async () => {
    const host = await mount(tile({ kind: "theme" }));
    const img = within(host).getByRole("img");
    for (const text of Object.values(PREVIEW_TILE_COPY.themeSample))
      expect(img).toHaveTextContent(text);
    const { bid, ask, position } = PREVIEW_TILE_COPY.themeSample;
    expect(img).toHaveAccessibleDescription(`${bid} ${ask} ${position}`);
    expect(img.querySelectorAll('[data-cmp="CMP-031"][aria-hidden="true"]')).toHaveLength(2);
  });

  it("tokenOverrides: scoped custom properties on the frame only; bad names are dropped", async () => {
    const host = await mount(
      tile({
        tokenOverrides: { "color.surface.sunken": "#101010", "bad name": "x", "--raw": "y" },
      }),
    );
    const frame = within(host).getByRole("img");
    expect(frame.style.getPropertyValue("--color-surface-sunken")).toBe("#101010");
    expect(frame.getAttribute("style")).not.toMatch(/bad|raw/);
    expect(root(host).getAttribute("style")).toBeNull();
  });

  it("warns in text plus a glyph when the overridden body text is below 4.5:1", async () => {
    const host = await mount(
      tile({ tokenOverrides: { [BODY.text]: "#777777", [BODY.surface]: "#ffffff" } }),
    );
    const warning = within(host).getByText(/^Low contrast:/);
    expect(warning).toHaveTextContent("4.48:1, below 4.5:1");
    expect(warning.querySelector("svg")).not.toBeNull();
  });

  it("warns on the secondary (reason) text pair too, at its lower ratio", async () => {
    const host = await mount(
      tile({
        status: "empty",
        tokenOverrides: {
          [BODY.text]: "#000000",
          [SECONDARY.text]: "#888888",
          [SECONDARY.surface]: "#ffffff",
        },
      }),
    );
    expect(within(host).getByText(/^Low contrast:/)).toHaveTextContent("3.54:1");
  });

  it("a one-sided override is measured against the theme's computed value", async () => {
    const theme: Record<string, string> = {
      "--color-text-primary": " #777777",
      "--color-text-secondary": "#777777",
      "--color-surface-sunken": "#ffffff",
    };
    const spy = vi.spyOn(window, "getComputedStyle").mockReturnValue({
      getPropertyValue: (name: string) => theme[name] ?? "",
    } as CSSStyleDeclaration);
    try {
      const host = await mount(tile({ tokenOverrides: { [BODY.surface]: "#fff" } }));
      expect(within(host).getByText(/^Low contrast:/)).toHaveTextContent("4.48:1");
    } finally {
      spy.mockRestore();
    }
  });

  it("no warning at 4.5:1 or above, or when a side is not an opaque hex", async () => {
    for (const text of ["#767676", "var(--x)", "#77777780"]) {
      const host = await mount(
        tile({ tokenOverrides: { [BODY.text]: text, [BODY.surface]: "#fff" } }),
      );
      expect(within(host).queryByText(/^Low contrast:/)).toBeNull();
    }
    const unrelated = await mount(tile({ tokenOverrides: { "color.border.default": "#fff" } }));
    expect(within(unrelated).queryByText(/^Low contrast:/)).toBeNull();
  });

  it("takes every string as a prop", async () => {
    const host = await mount(tile({ source: "sample", sampleText: "Beispiel" }));
    expect(within(host).getByText("Beispiel")).toBeTruthy();
  });

  it("axe: no serious or critical violations across the states", async () => {
    const host = await mount(
      <>
        {tile({ source: "sample", caption: "Changes: log" })}
        {tile({ status: "empty" })}
        {tile({ status: "error" })}
        {tile({
          kind: "theme",
          tokenOverrides: { "color.text.primary": "#777", "color.surface.sunken": "#888" },
        })}
        {tile({ kind: "ladder", value: ["1", "2"] })}
      </>,
    );
    expect(await seriousViolations(host)).toEqual([]);
  });
});
