/**
 * E16-S03 (#485): SCR-141's registration in SCR-140 (#485/#486 BQ-6, BQ-14; D03 §2, §10; KB-09) and who reaches it
 * (D03 §1.4; E16-D06 §20.3 (i)). The page draws "Retention policy" only while the editor is registered; it opens the
 * real dialog and closing returns focus to it. SCR-141 has no route: its host, R-340, is the owner's, refused to
 * anyone else with a 404 by the route guard (C-12.4). Over the page's stubbed `apiFetch` and fake socket.
 */
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

const { apiFetch } = vi.hoisted(() => ({
  apiFetch: vi.fn<(url: string, init?: RequestInit) => Promise<Response>>(),
}));
vi.mock("../../../../src/lib/http/csrfFetch", () => ({ apiFetch }));

import { RecorderScreen } from "../../../../src/features/recorder/RecorderScreen";
import { registerRetentionEditor } from "../../../../src/features/recorder/retention/register";
import { ROUTE_MANIFEST } from "../../../../src/routes/manifest";
import { NOW } from "../gridFixtures";
import { fakeSocket, frameOf, router } from "../screenFixtures";
import { POLICIES_DEFAULTS } from "./fixtures";

const json = (status: number, body?: unknown): Response =>
  new Response(body === undefined ? null : JSON.stringify(body), { status });
const flush = () => act(async () => void (await vi.advanceTimersByTimeAsync(0)));

beforeAll(() => {
  Element.prototype.scrollIntoView = vi.fn();
});
beforeEach(() => {
  vi.useFakeTimers({
    toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval", "Date", "performance"],
    now: NOW,
  });
  apiFetch.mockImplementation(
    router((method, url) =>
      url.includes("/recording/retention-policies") ? json(200, POLICIES_DEFAULTS) : undefined,
    ),
  );
});
afterEach(() => {
  apiFetch.mockReset();
  vi.useRealTimers();
});

async function mountPage() {
  const clock = { now: NOW };
  const socket = fakeSocket(clock);
  const view = render(<RecorderScreen data={socket.options} instruments={[]} />);
  await flush();
  socket.push(frameOf());
  act(() => socket.step(0));
  await flush();
  return view;
}

describe("SCR-141 in SCR-140 (BQ-6)", { timeout: 30_000 }, () => {
  it("'Retention policy' appears once registered, opens the editor, and focus returns to it on close", async () => {
    await mountPage();
    expect(screen.queryByRole("button", { name: "Retention policy" })).toBeNull();
    let off = (): void => undefined;
    act(() => {
      off = registerRetentionEditor();
    });
    const entry = screen.getByRole("button", { name: "Retention policy" });
    act(() => entry.focus());
    fireEvent.click(entry);
    await flush();
    const dialog = screen.getByRole("dialog", { name: "Retention policy" });
    expect(
      within(dialog).getByRole("spinbutton", { name: "Trades Retention (days)" }),
    ).toHaveFocus();
    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(entry).toHaveFocus();
    act(() => off());
    expect(screen.queryByRole("button", { name: "Retention policy" })).toBeNull();
  });
});

describe("who reaches SCR-141 (D03 §1.4; E16-D06 §20.3 (i))", () => {
  it("SCR-141 has no route of its own; its host R-340 is the owner's and refuses anyone else with a 404", () => {
    expect(ROUTE_MANIFEST.filter((route) => route.path.includes("retention"))).toEqual([]);
    const host = ROUTE_MANIFEST.find((route) => route.id === "R-340");
    expect(host?.path).toBe("/admin/recorder");
    expect(host?.access).toEqual({ roles: ["owner"], denyAs: "404" });
  });
});
