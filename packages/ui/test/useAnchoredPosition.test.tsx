// @vitest-environment jsdom
import type * as FloatingUi from "@floating-ui/dom";
import { act, useRef, type JSX } from "react";
import { expect } from "storybook/test";
import { afterEach, beforeEach, describe, it, vi } from "vitest";
import {
  pointAnchor,
  useAnchoredPosition,
  type AnchoredAlign,
  type AnchoredSide,
} from "../src/components/internal/useAnchoredPosition.js";
import { mount } from "./theme/mount.js";

const floating = vi.hoisted(() => ({
  computePosition: vi.fn(),
  autoUpdate: vi.fn(),
  stop: vi.fn(),
}));

vi.mock("@floating-ui/dom", async (importOriginal) => {
  const real = await importOriginal<typeof FloatingUi>();
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

function Harness({
  open,
  side = "top",
  fit,
}: {
  open: boolean;
  side?: AnchoredSide;
  fit?: boolean;
}): JSX.Element {
  const anchor = useRef<HTMLButtonElement>(null);
  const surface = useRef<HTMLDivElement>(null);
  useAnchoredPosition({
    open,
    reference: anchor,
    floating: surface,
    side,
    ...(fit ? { fit } : {}),
  });
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

  it("fit (CMP-017): adds size after shift and writes the anchor width and the room left", async () => {
    const host = await mount(<Harness open side="bottom" fit />);
    const [, , options] = floating.computePosition.mock.calls[0] as [
      Element,
      Element,
      { middleware: { name: string; options: { padding?: number; apply?: unknown } }[] },
    ];
    expect(options.middleware.map((m) => m.name)).toEqual(["offset", "flip", "shift", "size"]);
    const sized = options.middleware[3]?.options;
    expect(sized?.padding).toBe(4);
    const apply = sized?.apply as (state: {
      rects: { reference: { width: number } };
      availableHeight: number;
    }) => void;
    apply({ rects: { reference: { width: 96 } }, availableHeight: 240 });
    expect(surface(host).style.getPropertyValue("--cv-anchor-width")).toBe("96px");
    expect(surface(host).style.getPropertyValue("--cv-available-height")).toBe("240px");
    apply({ rects: { reference: { width: 96 } }, availableHeight: -8 });
    expect(surface(host).style.getPropertyValue("--cv-available-height")).toBe("0px");
  });

  it("fit: the custom properties are removed on close", async () => {
    const { createRoot } = await import("react-dom/client");
    const host = document.body.appendChild(document.createElement("div"));
    const root = createRoot(host);
    await act(async () => root.render(<Harness open fit />));
    const [, , options] = floating.computePosition.mock.calls[0] as [
      Element,
      Element,
      { middleware: { options: { apply?: unknown } }[] },
    ];
    const apply = options.middleware[3]?.options.apply as (state: {
      rects: { reference: { width: number } };
      availableHeight: number;
    }) => void;
    apply({ rects: { reference: { width: 96 } }, availableHeight: 240 });
    await act(async () => root.render(<Harness open={false} fit />));
    expect(surface(host).style.getPropertyValue("--cv-anchor-width")).toBe("");
    expect(surface(host).style.getPropertyValue("--cv-available-height")).toBe("");
    await act(async () => root.unmount());
  });

  it("a failed measurement still marks the surface placed, so it is never stuck invisible", async () => {
    floating.computePosition.mockRejectedValue(new Error("no layout"));
    const host = await mount(<Harness open />);
    await act(async () => undefined);
    expect(surface(host)).toHaveAttribute("data-positioned");
  });

  it("a missing anchor marks the surface placed and attaches nothing", async () => {
    function NoAnchor(): JSX.Element {
      const anchor = useRef<HTMLButtonElement>(null);
      const node = useRef<HTMLDivElement>(null);
      useAnchoredPosition({ open: true, reference: anchor, floating: node, side: "bottom" });
      return <div ref={node} data-testid="surface" />;
    }
    const host = await mount(<NoAnchor />);
    expect(surface(host)).toHaveAttribute("data-positioned");
    expect(floating.autoUpdate).not.toHaveBeenCalled();
  });

  it("align start places the surface on the anchor's start edge (a submenu, a context menu)", async () => {
    function Aligned({ align }: { align: AnchoredAlign }): JSX.Element {
      const anchor = useRef<HTMLButtonElement>(null);
      const node = useRef<HTMLDivElement>(null);
      useAnchoredPosition({ open: true, reference: anchor, floating: node, side: "right", align });
      return (
        <>
          <button ref={anchor} type="button">
            Anchor
          </button>
          <div ref={node} />
        </>
      );
    }
    floating.computePosition.mockResolvedValue({ x: 0, y: 0, placement: "left-start" });
    const host = await mount(<Aligned align="start" />);
    const placement = (i: number): string =>
      (floating.computePosition.mock.calls[i] as [unknown, unknown, { placement: string }])[2]
        .placement;
    expect(placement(0)).toBe("right-start");
    await act(async () => undefined);
    expect(host.querySelector("div")?.dataset["side"]).toBe("left");
    await mount(<Aligned align="center" />);
    expect(placement(1)).toBe("right");
  });

  it("a point anchor is a zero-size virtual reference at the pointer", async () => {
    const point = pointAnchor(40, 60);
    expect(point.getBoundingClientRect()).toEqual({
      x: 40,
      y: 60,
      width: 0,
      height: 0,
      top: 60,
      left: 40,
      right: 40,
      bottom: 60,
    });
    function AtPoint(): JSX.Element {
      const anchor = useRef(point);
      const node = useRef<HTMLDivElement>(null);
      useAnchoredPosition({
        open: true,
        reference: anchor,
        floating: node,
        side: "bottom",
        align: "start",
      });
      return <div ref={node} />;
    }
    await mount(<AtPoint />);
    const [reference, , options] = floating.computePosition.mock.calls[0] as [
      unknown,
      unknown,
      { placement: string },
    ];
    expect(reference).toBe(point);
    expect(options.placement).toBe("bottom-start");
  });
});
