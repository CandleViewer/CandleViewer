// @vitest-environment jsdom
import { createRequire } from "node:module";
import { act } from "react";
import { composeStories } from "@storybook/react-vite";
import { expect, fireEvent, fn, within } from "storybook/test";
import { describe, it } from "vitest";
import {
  GLOBAL_ERROR_FALLBACK_COPY as C,
  GlobalErrorAnnouncement,
  GlobalErrorBoundaryFallback,
  type GlobalErrorBoundaryFallbackProps,
} from "../src/components/index.js";
import * as stories from "../src/components/GlobalErrorBoundaryFallback.stories.js";
import { mount } from "./theme/mount.js";

type Axe = {
  run: (context: object, options?: object) => Promise<{ violations: { impact?: string | null }[] }>;
};
const axe = createRequire(createRequire(import.meta.url).resolve("@storybook/addon-a11y"))(
  "axe-core",
) as Axe;

const ID = "00000000-0000-4000-8000-000000000001";
const base = (over: Partial<GlobalErrorBoundaryFallbackProps> = {}) => ({
  correlationId: ID,
  onReload: fn(),
  onCopyDiagnostics: fn(async () => undefined),
  ...over,
});
const button = (host: HTMLElement, name: string) => within(host).getByRole("button", { name });
const names = (host: HTMLElement) =>
  within(host)
    .getAllByRole("button")
    .map((b) => b.textContent);

describe("GlobalErrorBoundaryFallback (CMP-091)", () => {
  it("panel: an h2-named region with Reload panel, Remove panel, Copy diagnostics and the error id", async () => {
    const host = await mount(<GlobalErrorBoundaryFallback {...base({ onRemovePanel: fn() })} />);
    const h = within(host).getByRole("heading", { name: C.panel.heading });
    expect(h.tagName).toBe("H2");
    expect(within(host).getByRole("region", { name: C.panel.heading })).toBeInTheDocument();
    expect(within(host).queryByRole("alert")).toBeNull();
    expect(names(host)).toEqual([C.panel.reload, C.removePanel, C.copyDiagnostics]);
    expect(within(host).getByText(ID).tagName).toBe("CODE");
  });

  it("route: an h1 with Reload page, Reload app, safe mode where offered", async () => {
    const host = await mount(
      <GlobalErrorBoundaryFallback
        {...base({ scope: "route", onReloadApp: fn(), onSafeMode: fn() })}
      />,
    );
    expect(within(host).getByRole("heading", { name: C.route.heading }).tagName).toBe("H1");
    expect(names(host)).toEqual([C.route.reload, C.reloadApp, C.safeMode, C.copyDiagnostics]);
  });

  it("app: its own alert, Reload app as the reload, still offered when repeated", async () => {
    const onReload = fn();
    const host = await mount(
      <GlobalErrorBoundaryFallback {...base({ scope: "app", repeated: true, onReload })} />,
    );
    const alert = within(host).getByRole("alert");
    expect(within(alert).getByRole("heading", { name: C.app.repeatedHeading }).tagName).toBe("H1");
    fireEvent.click(button(host, C.app.reload));
    expect(onReload).toHaveBeenCalledOnce();
  });

  it("app: the alert holds the static lead only; Copy and Technical detail never change it", async () => {
    const host = await mount(
      <GlobalErrorBoundaryFallback {...base({ scope: "app", details: "d" })} />,
    );
    const alert = within(host).getByRole("alert");
    const before = alert.textContent;
    expect(within(host).getByRole("status")).toBeEmptyDOMElement();
    await act(async () => button(host, C.copyDiagnostics).click());
    await act(async () => button(host, C.technicalDetail).click());
    expect(within(host).getByRole("status")).toHaveTextContent(C.copied);
    expect(within(host).getByText("d")).toBeVisible();
    expect(alert.textContent).toBe(before);
    expect(within(alert).queryByRole("button")).toBeNull();
  });

  it("panel and route render no alert of their own", async () => {
    for (const scope of ["panel", "route"] as const) {
      const host = await mount(<GlobalErrorBoundaryFallback {...base({ scope })} />);
      expect(within(host).queryByRole("alert")).toBeNull();
    }
  });

  it("the announcement is the scope's heading, visually hidden", async () => {
    const host = await mount(
      <>
        <GlobalErrorAnnouncement scope="panel" />
        <GlobalErrorAnnouncement scope="route" repeated />
      </>,
    );
    const spans = host.querySelectorAll(".cv-visually-hidden");
    expect([...spans].map((n) => n.textContent)).toEqual([
      C.panel.heading,
      C.route.repeatedHeading,
    ]);
  });

  it("repeated panel: no reload, the reason, Reload app as the way out", async () => {
    const onReloadApp = fn();
    const host = await mount(
      <GlobalErrorBoundaryFallback {...base({ repeated: true, onReloadApp })} />,
    );
    expect(within(host).getByRole("heading", { name: C.panel.repeatedHeading })).toBeVisible();
    expect(within(host).getByText(C.repeatedReason)).toBeInTheDocument();
    expect(within(host).queryByRole("button", { name: C.panel.reload })).toBeNull();
    fireEvent.click(button(host, C.reloadApp));
    expect(onReloadApp).toHaveBeenCalledOnce();
  });

  it("focuses the heading when focus was on the body", async () => {
    const host = await mount(<GlobalErrorBoundaryFallback {...base()} />);
    expect(within(host).getByRole("heading")).toHaveFocus();
  });

  it("leaves focus where it is when the crash did not drop it", async () => {
    const other = document.body.appendChild(document.createElement("button"));
    other.focus();
    await mount(<GlobalErrorBoundaryFallback {...base()} />);
    expect(other).toHaveFocus();
  });

  it("Technical detail is an APG disclosure over the details string, text only", async () => {
    const details = "<b>not markup</b> line";
    const host = await mount(<GlobalErrorBoundaryFallback {...base({ details })} />);
    const toggle = button(host, C.technicalDetail);
    const panel = document.getElementById(toggle.getAttribute("aria-controls") ?? "");
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(panel).not.toBeVisible();
    expect(host.textContent).not.toContain("line");
    await act(async () => toggle.click());
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(within(host).getByText(details)).toBeVisible();
    expect(host.querySelector("b")).toBeNull();
  });

  it("renders no disclosure without details", async () => {
    const host = await mount(<GlobalErrorBoundaryFallback {...base()} />);
    expect(within(host).queryByRole("button", { name: C.technicalDetail })).toBeNull();
  });

  it("reports the copy result: copied, a rejection, a throw", async () => {
    const host = await mount(<GlobalErrorBoundaryFallback {...base()} />);
    await act(async () => button(host, C.copyDiagnostics).click());
    expect(within(host).getByText(C.copied)).toBeInTheDocument();
    for (const onCopyDiagnostics of [
      fn(async () => Promise.reject(new Error("denied"))),
      fn((): Promise<void> => {
        throw new Error("sync");
      }),
    ]) {
      const h = await mount(<GlobalErrorBoundaryFallback {...base({ onCopyDiagnostics })} />);
      await act(async () => button(h, C.copyDiagnostics).click());
      expect(within(h).getByText(C.copyFailed)).toBeInTheDocument();
    }
  });

  it("renders the protection note only when the host passes it", async () => {
    const note = "Positions are protected by native stops.";
    const host = await mount(<GlobalErrorBoundaryFallback {...base({ protectionNote: note })} />);
    expect(within(host).getByText(note)).toBeInTheDocument();
  });

  const composed = composeStories(stories);
  it.each(Object.entries(composed))(
    "%s has no serious or critical axe violations",
    async (_name, Story) => {
      const host = await mount(<Story />);
      await Story.play?.({ canvasElement: host } as never);
      const { violations } = await axe.run(host, {
        rules: { "color-contrast": { enabled: false } },
      });
      expect(violations.filter((v) => v.impact === "serious" || v.impact === "critical")).toEqual(
        [],
      );
    },
  );
});
