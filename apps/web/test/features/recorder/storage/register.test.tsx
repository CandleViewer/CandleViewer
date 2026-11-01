/**
 * E16-S04 (#486): SCR-142's registration in SCR-140 (#485/#486 BQ-6, BQ-14; E16-D04 §2, BQ-6 RULED: a section of
 * `/admin/recorder`; E16-D06 FM-14, §20.3 (i)) and who reaches it. The page draws "Storage details" and the section
 * only while the panel is registered; "Storage details" lands on the section's heading; the page hands the section
 * its retention and suggested-action hand-offs; R-340 is the Owner's, refused to anyone else with a 404 by the route
 * guard (C-12.4). Over the page's stubbed `apiFetch` and fake socket.
 */
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

const { apiFetch } = vi.hoisted(() => ({
  apiFetch: vi.fn<(url: string, init?: RequestInit) => Promise<Response>>(),
}));
vi.mock("../../../../src/lib/http/csrfFetch", () => ({ apiFetch }));

import {
  registerRecorderExtensions,
  type RetentionEditorProps,
} from "../../../../src/features/recorder/extensions";
import { RecorderScreen } from "../../../../src/features/recorder/RecorderScreen";
import { registerStoragePanel } from "../../../../src/features/recorder/storage/register";
import { ROUTE_MANIFEST } from "../../../../src/routes/manifest";
import { healthDegraded } from "../fixtures";
import { NOW } from "../gridFixtures";
import { fakeSocket, frameOf, router } from "../screenFixtures";

const json = (status: number, body?: unknown): Response =>
  new Response(body === undefined ? null : JSON.stringify(body), { status });
const flush = () => act(async () => void (await vi.advanceTimersByTimeAsync(0)));
let reported: unknown[] = [];
const onAnalytics = (event: Event): void => void reported.push((event as CustomEvent).detail);

beforeAll(() => {
  Element.prototype.scrollIntoView = vi.fn();
});
beforeEach(() => {
  vi.useFakeTimers({
    toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval", "Date", "performance"],
    now: NOW,
  });
  reported = [];
  window.addEventListener("cv:analytics", onAnalytics);
  apiFetch.mockImplementation(
    router((_, url) => (url.endsWith("/admin/health") ? json(200, healthDegraded) : undefined)),
  );
});
afterEach(() => {
  window.removeEventListener("cv:analytics", onAnalytics);
  apiFetch.mockReset();
  vi.useRealTimers();
});

async function mountPage(storage: Parameters<typeof frameOf>[1] = {}) {
  const clock = { now: NOW };
  const socket = fakeSocket(clock);
  const view = render(
    <MemoryRouter>
      <RecorderScreen data={socket.options} instruments={[]} />
    </MemoryRouter>,
  );
  await flush();
  socket.push(frameOf({}, storage));
  act(() => socket.step(0));
  await flush();
  return view;
}
const section = () => screen.queryByRole("region", { name: "Storage and database" });

describe("SCR-142 in SCR-140 (BQ-6, BQ-14)", { timeout: 30_000 }, () => {
  it("appears once registered: 'Storage details' lands on its heading; it reads its own sample", async () => {
    await mountPage();
    expect(screen.queryByRole("button", { name: "Storage details" })).toBeNull();
    expect(section()).toBeNull();
    // The registration is undone even when an assertion fails, so no case leaks into the next (C-486P3-13).
    const registration = { off: (): void => undefined };
    try {
      act(() => {
        registration.off = registerStoragePanel();
      });
      await flush();
      const host = section();
      expect(host).not.toBeNull();
      expect(within(host as HTMLElement).getByRole("heading", { level: 2 })).toHaveAttribute(
        "id",
        "cv-recorder-storage",
      );
      fireEvent.click(screen.getByRole("button", { name: "Storage details" }));
      expect(screen.getByRole("heading", { level: 2, name: "Storage and database" })).toHaveFocus();
      expect(apiFetch.mock.calls.map(([url]) => url)).toContain("/api/v1/admin/health");
      expect(reported).toEqual([
        { name: "recorder.screen_viewed" },
        { name: "storage.panel_viewed" },
      ]);
      act(() => registration.off());
      expect(section()).toBeNull();
      expect(screen.queryByRole("button", { name: "Storage details" })).toBeNull();
    } finally {
      act(() => registration.off()); // a second call removes nothing
    }
  });

  it("the page hands the section its rows' history: growth 0 reads Steady there too (C-486P3-02)", async () => {
    const off = registerStoragePanel();
    try {
      // The rows started days ago (the page's own fixture); the recorder grows by nothing.
      await mountPage({ daily_growth_bytes: 0 });
      const host = section() as HTMLElement;
      expect(host).toHaveTextContent("Steady · usage is not growing");
      expect(document.body).not.toHaveTextContent("Too early to project");
    } finally {
      act(() => off());
    }
  });

  it("the page hands over SCR-141: Shorten retention opens the registered editor", async () => {
    const editor = vi.fn((props: RetentionEditorProps) =>
      props.open ? <p>retention editor open</p> : null,
    );
    const offEditor = registerRecorderExtensions({ RetentionEditor: editor });
    const offPanel = registerStoragePanel();
    try {
      await mountPage({ level: 1, used_bytes: 161e9 });
      const host = section() as HTMLElement;
      expect(host).toHaveTextContent("Recording pauses before trading is affected.");
      fireEvent.click(within(host).getByRole("button", { name: "Shorten retention" }));
      expect(screen.getByText("retention editor open")).toBeVisible();
    } finally {
      act(() => {
        offPanel();
        offEditor();
      });
    }
  });
});

describe("who reaches SCR-142 (D04 §9; E16-D06 §20.3 (i))", () => {
  it("SCR-142 has no route of its own; its host R-340 is the owner's and refuses anyone else with a 404", () => {
    expect(ROUTE_MANIFEST.filter((route) => route.path.includes("storage"))).toEqual([]);
    const host = ROUTE_MANIFEST.find((route) => route.id === "R-340");
    expect(host?.path).toBe("/admin/recorder");
    expect(host?.access).toEqual({ roles: ["owner"], denyAs: "404" });
  });
});
