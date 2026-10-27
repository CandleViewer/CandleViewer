// @vitest-environment jsdom
import { act, useRef, type JSX } from "react";
import { expect } from "storybook/test";
import { afterEach, beforeEach, describe, it, vi } from "vitest";
import {
  useAnchoredPosition,
  type AnchoredSide,
} from "../src/components/internal/useAnchoredPosition.js";
import { mount } from "./theme/mount.js";

const floating = vi.hoisted(() => ({
  computePosition: vi.fn(),
  autoUpdate: vi.fn(),
  stop: vi.fn(),
}));

vi.mock("@floating-ui/dom", async (importOriginal) => {
  const real = await importOriginal<typeof import("@floating-ui/dom")>();
  return { ...real, computePosition: floating.computePosition, autoUpdate: floating.autoUpdate };
});

beforeEach(() => {
  floating.stop.mockReset();
  floating.autoUpdate
    .mockReset()
    .mockImplementation((_a: Element, _f: Element, update: () => void) => {
      update();
      return floating.stop;
    });
  // No room above: the flip middleware resolves the top placement to the bottom side.
  floating.computePosition.mockReset().mockResolvedValue({ x: 12, y: 34, placement: "bottom" });
});
afterEach(() => vi.restoreAllMocks());

function Harness({ open, side = "top" }: { open: boolean; side?: AnchoredSide }): JSX.Element {
  const anchor = useRef<HTMLButtonElement>(null);
  const surface = useRef<HTMLDivElement>(null);
  useAnchoredPosition({ open, reference: anchor, floating: surface, side });
  return (
    <>
      <button ref={anchor} type="button">
        Anchor
      </button>
      <div ref={surface} data-testid="surface" style={{ ["--space-inset-xs" as string]: "4px" }} />
    </>
  );
}

const surface = (host: HTMLElement): HTMLElement => {
  const node = host.querySelector<HTMLElement>("[data-testid=surface]");
  if (node === null) throw new Error("no surface");
  return node;
};

describe("useAnchoredPosition", () => {
  it("does nothing while closed: no autoUpdate, so no listener or observer", async () => {
    await mount(<Harness open={false} />);
    expect(floating.autoUpdate).not.toHaveBeenCalled();
    expect(floating.computePosition).not.toHaveBeenCalled();
  });

  it("positions fixed with offset, flip and shift at the space.inset.xs gap, and writes the flipped side", async () => {
    const host = await mount(<Harness open />);
    expect(floating.autoUpdate).toHaveBeenCalledTimes(1);
    const [anchor, node, options] = floating.computePosition.mock.calls[0] as [
      Element,
      Element,
      { strategy: string; placement: string; middleware: { name: string; options: unknown }[] },
    ];
    expect(anchor).toBe(host.querySelector("button"));
    expect(node).toBe(surface(host));
    expect(options.strategy).toBe("fixed");
    expect(options.placement).toBe("top");
    expect(options.middleware.map((m) => m.name)).toEqual(["offset", "flip", "shift"]);
    expect(options.middleware[0]?.options).toBe(4);
    expect(options.middleware[1]?.options).toMatchObject({ padding: 4 });
    expect(options.middleware[2]?.options).toMatchObject({ padding: 4 });
    await act(async () => undefined);
    expect(surface(host).style.left).toBe("12px");
    expect(surface(host).style.top).toBe("34px");
    expect(surface(host).dataset["side"]).toBe("bottom");
    expect(surface(host)).toHaveAttribute("data-positioned");
  });

  it("stops autoUpdate on close and on unmount, and ignores a placement that resolves after close", async () => {
    let resolve: (v: { x: number; y: number; placement: string }) => void = () => undefined;
    floating.computePosition.mockReturnValue(
      new Promise((r) => {
        resolve = r;
      }),
    );
    const host = document.body.appendChild(document.createElement("div"));
    const { createRoot } = await import("react-dom/client");
    const root = createRoot(host);
    await act(async () => root.render(<Harness open />));
    await act(async () => root.render(<Harness open={false} />));
    expect(floating.stop).toHaveBeenCalledTimes(1);
    await act(async () => resolve({ x: 1, y: 2, placement: "top" }));
    expect(surface(host)).not.toHaveAttribute("data-positioned");
    await act(async () => root.render(<Harness open />));
    await act(async () => root.unmount());
    expect(floating.stop).toHaveBeenCalledTimes(2);
  });

  it("falls back to a zero gap when the token is unset, and re-runs when the side changes", async () => {
    const host = await mount(<Harness open side="right" />);
    surface(host).style.removeProperty("--space-inset-xs");
    const call = (i: number): { placement: string; middleware: { options: unknown }[] } =>
      (floating.computePosition.mock.calls[i] as [unknown, unknown, never])[2];
    expect(call(0).placement).toBe("right");
    floating.autoUpdate.mockClear();
    const { createRoot } = await import("react-dom/client");
    const other = document.body.appendChild(document.createElement("div"));
    const root = createRoot(other);
    await act(async () => root.render(<Harness open side="left" />));
    surface(other).style.removeProperty("--space-inset-xs");
    await act(async () => root.render(<Harness open side="bottom" />));
    const last = floating.computePosition.mock.calls.length - 1;
    expect(call(last).placement).toBe("bottom");
    expect(call(last).middleware[0]?.options).toBe(0);
    await act(async () => root.unmount());
  });
});
