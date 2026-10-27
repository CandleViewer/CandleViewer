/**
 * E10-S04 (#306) slice 6: the CMP-091 panel and route boundaries. apps/web has no Storybook, so each
 * drawn state (panel, route, repeated) is rendered and axe-checked here; #267's CMP-091 brings the stories.
 */
import { createRequire } from "node:module";
import { StrictMode } from "react";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { createMemoryRouter } from "react-router";
import { RouterProvider } from "react-router/dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { PanelErrorBoundary } from "../../../src/features/system-states/PanelErrorBoundary";
import {
  createCrashGuard,
  setCrashGuardForTests,
} from "../../../src/features/system-states/crashGuard";
import { CRASH_COPY } from "../../../src/features/system-states/copy";
import { RouteErrorElement } from "../../../src/routes/RouteErrorElement";
import { buildDiagnostics, installCrashReporter } from "../../../src/shell/crash/reportCrash";

const axe = createRequire(createRequire(import.meta.url).resolve("@axe-core/playwright"))(
  "axe-core",
) as { run: (el: Element, o?: object) => Promise<{ violations: { impact?: string | null }[] }> };

// a bearer-shaped secret and a shapeless marker, built at run time; neither may reach the DOM
const SECRET = ["Bearer ", "eyJ", "x".repeat(24)].join("");
const RAW = ["raw", "error", "text"].join("-");
const ID = "00000000-0000-4000-8000-000000000001";
let uninstall: () => void = () => undefined;
let failing = true;
let throwPrimitive = false;

function Bomb(): JSX.Element {
  if (failing && throwPrimitive) throw `${RAW} primitive`; // a thrown non-Error is the case under test
  if (failing) throw new Error(`${RAW} ${SECRET}`);
  return <p>panel content</p>;
}
const heading = (name: string) => screen.findByRole("heading", { name });
const button = (name: string) => screen.getByRole("button", { name });

async function expectCleanDom(): Promise<void> {
  expect(document.body.textContent).not.toMatch(new RegExp(`${RAW}|eyJ`));
  const res = await axe.run(document.body, { rules: { "color-contrast": { enabled: false } } });
  expect(res.violations.filter((v) => v.impact === "serious" || v.impact === "critical")).toEqual(
    [],
  );
}

function panelTree(onReloadApp?: () => void): JSX.Element {
  return (
    <>
      <button type="button">survivor</button>
      <PanelErrorBoundary id="test-panel" onReloadApp={onReloadApp}>
        <Bomb />
      </PanelErrorBoundary>
    </>
  );
}
const renderPanel = (onReloadApp?: () => void) => render(panelTree(onReloadApp));

beforeEach(() => {
  failing = true;
  throwPrimitive = false;
  setCrashGuardForTests(createCrashGuard(() => Date.now()));
  uninstall = installCrashReporter({
    version: "t",
    target: undefined,
    newId: () => ID,
    now: () => 0,
  });
  vi.spyOn(console, "error").mockImplementation(() => undefined);
});
afterEach(() => {
  uninstall();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("PanelErrorBoundary", () => {
  it("replaces only the failed panel, reports once, restores focus, shows no raw error", async () => {
    renderPanel();
    const h = await heading(CRASH_COPY.panel.heading);
    expect(h.tagName).toBe("H2");
    expect(h).toHaveFocus(); // the crash dropped focus to the body
    expect(screen.getByRole("region", { name: CRASH_COPY.panel.heading })).toBeInTheDocument();
    expect(button("survivor")).toBeEnabled();
    expect(screen.getByText(ID)).toBeInTheDocument();
    expect(buildDiagnostics().metrics.shell_crash_total.panel).toBe(1);
    await expectCleanDom();
  });

  it("Reload panel re-mounts the child", async () => {
    renderPanel();
    failing = false;
    fireEvent.click(await screen.findByRole("button", { name: CRASH_COPY.panel.reload }));
    expect(await screen.findByText("panel content")).toBeInTheDocument();
  });

  it("stops reloading on the third crash at 2:00 and offers Reload app", async () => {
    vi.useFakeTimers();
    const reloadApp = vi.fn();
    renderPanel(reloadApp);
    for (let i = 0; i < 2; i += 1) {
      act(() => vi.advanceTimersByTime(60_000));
      fireEvent.click(button(CRASH_COPY.panel.reload));
    }
    expect(screen.getByRole("heading", { name: CRASH_COPY.panel.repeatedHeading })).toBeVisible();
    expect(screen.getByText(CRASH_COPY.repeatedReason)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: CRASH_COPY.panel.reload })).toBeNull();
    fireEvent.click(button(CRASH_COPY.reloadApp));
    expect(reloadApp).toHaveBeenCalledOnce();
    vi.useRealTimers();
    await expectCleanDom();
  });

  it("announces the fallback through an alert region pre-rendered empty", async () => {
    failing = false;
    const { rerender } = renderPanel();
    expect(screen.getByRole("alert")).toBeEmptyDOMElement();
    failing = true;
    rerender(panelTree());
    const alert = screen.getByRole("alert");
    expect(within(alert).getByRole("heading", { name: CRASH_COPY.panel.heading })).toBeVisible();
  });

  it("still renders the fallback when the reporter throws", async () => {
    uninstall();
    uninstall = installCrashReporter({
      version: "t",
      target: undefined,
      newId: () => {
        throw new Error("reporter down");
      },
    });
    renderPanel();
    expect(await heading(CRASH_COPY.panel.heading)).toBeVisible();
    expect(screen.getByText("unavailable")).toBeInTheDocument();
  });

  it("Copy diagnostics writes the redacted payload", async () => {
    const writeText = vi.fn(async () => undefined);
    vi.stubGlobal("navigator", { clipboard: { writeText } });
    renderPanel();
    await heading(CRASH_COPY.panel.heading);
    fireEvent.click(button(CRASH_COPY.copyDiagnostics));
    expect(await screen.findByText(CRASH_COPY.copied)).toBeInTheDocument();
    const text = String(writeText.mock.calls[0]?.at(0));
    expect(JSON.parse(text)).toEqual(buildDiagnostics());
    expect(text).toContain(ID);
    expect(text).not.toContain("eyJ");
  });
});

describe("RouteErrorElement (route boundary)", () => {
  function renderRoute(id: string, strict = false): void {
    const routes = [{ id, path: "/t", element: <Bomb />, errorElement: <RouteErrorElement /> }];
    const app = <RouterProvider router={createMemoryRouter(routes, { initialEntries: ["/t"] })} />;
    render(strict ? <StrictMode>{app}</StrictMode> : app);
  }

  it("renders the route fallback in one main, inside its alert region, reported once", async () => {
    renderRoute("R-T1");
    expect((await heading(CRASH_COPY.route.heading)).tagName).toBe("H1");
    expect(screen.getAllByRole("main")).toHaveLength(1);
    const alert = within(screen.getByRole("main")).getByRole("alert");
    expect(within(alert).getByRole("heading", { name: CRASH_COPY.route.heading })).toBeVisible();
    expect(button(CRASH_COPY.reloadApp)).toBeInTheDocument();
    expect(buildDiagnostics().metrics.shell_crash_total.route).toBe(1);
    await expectCleanDom();
  });

  it("Reload page re-renders the route", async () => {
    renderRoute("R-T2");
    failing = false;
    fireEvent.click(await screen.findByRole("button", { name: CRASH_COPY.route.reload }));
    expect(await screen.findByText("panel content")).toBeInTheDocument();
  });

  it("counts a thrown primitive once under StrictMode", async () => {
    throwPrimitive = true;
    const guard = createCrashGuard(() => Date.now());
    const record = vi.spyOn(guard, "record");
    setCrashGuardForTests(guard);
    renderRoute("R-T3", true);
    await heading(CRASH_COPY.route.heading);
    expect(record).toHaveBeenCalledOnce();
    expect(buildDiagnostics().metrics.shell_crash_total.route).toBe(1);
  });

  it("keeps counting across Reload page: the third crash shows the repeated state", async () => {
    renderRoute("R-T4");
    for (let i = 0; i < 2; i += 1) {
      fireEvent.click(await screen.findByRole("button", { name: CRASH_COPY.route.reload }));
    }
    expect(await heading(CRASH_COPY.route.repeatedHeading)).toBeVisible();
    expect(screen.queryByRole("button", { name: CRASH_COPY.route.reload })).toBeNull();
    expect(button(CRASH_COPY.reloadApp)).toBeInTheDocument();
  });
});
