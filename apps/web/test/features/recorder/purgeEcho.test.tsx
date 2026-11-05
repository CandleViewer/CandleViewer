/**
 * E16-S01 PR 3, S-5347-01: the purge's `confirm_symbol` is the typed field's text exactly as typed (CMP-044's
 * `ConfirmMeta.typedValue`), never the Symbol select's value, so the server's echo check is a check (`22`
 * `purgeRecordedData`; E16-D04 §7; E16-D06 §20.3 (ii)). CMP-044 is stubbed here to hand over a text the real one
 * never accepts; the server's `422 purge_confirmation_mismatch` is then the T4 with its code (§16.4 row 11). A
 * stubbed `apiFetch` (no network, C-13.5).
 */
import { act, fireEvent, render, screen } from "@testing-library/react";
import type * as Ui from "@candleviewer/ui";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const { apiFetch } = vi.hoisted(() => ({
  apiFetch: vi.fn<(url: string, init?: RequestInit) => Promise<Response>>(),
}));
vi.mock("../../../src/lib/http/csrfFetch", () => ({ apiFetch }));
vi.mock("@candleviewer/ui", async (importOriginal) => {
  const ui = await importOriginal<typeof Ui>();
  const { createElement } = await import("react");
  /** CMP-044 reduced to its contract: the body, and a confirm whose meta carries a typed text of its own. */
  const ConfirmDialog = (props: Ui.ConfirmDialogProps) =>
    props.open
      ? createElement(
          "div",
          { role: "dialog", "aria-label": props.title },
          props.children,
          props.failure === undefined ? null : createElement("p", null, props.failure.message),
          createElement(
            "button",
            {
              type: "button",
              onClick: () =>
                props.onConfirm({
                  variant: "typed",
                  gate: "typed",
                  elapsedMs: 500,
                  typedValue: "adausdt",
                }),
            },
            "Confirm as typed",
          ),
        )
      : null;
  return { ...ui, ConfirmDialog };
});

import { PurgeDialog } from "../../../src/features/recorder/PurgeDialog";
import type { PurgeTarget } from "../../../src/features/recorder/purge";
import { problem } from "./fixtures";
import { NOW } from "./gridFixtures";

const TARGETS: readonly PurgeTarget[] = [
  { symbol: "ADAUSDT", pinned: false, retentionDays: 30, diskBytes: 11e9, startedAt: null },
];
const json = (status: number, body?: unknown): Response =>
  new Response(body === undefined ? null : JSON.stringify(body), { status });

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"], now: NOW });
});
afterEach(() => {
  apiFetch.mockReset();
  vi.useRealTimers();
});

it("sends confirm_symbol as typed, never the select's symbol; the server's mismatch is the T4 with its code", async () => {
  apiFetch.mockImplementation(async (url, init) =>
    (init?.method ?? "GET") === "GET"
      ? json(200, { symbol: "ADAUSDT", streams: [] })
      : json(422, problem(422, "purge_confirmation_mismatch")),
  );
  render(
    <PurgeDialog
      open
      symbol="ADAUSDT"
      symbols={TARGETS}
      onClose={() => undefined}
      onStarted={() => undefined}
      readBack={() => undefined}
    />,
  );
  await act(async () => void (await Promise.resolve()));
  fireEvent.change(screen.getByRole("textbox", { name: "Reason (required, 3–280 characters)" }), {
    target: { value: "space for the import" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Confirm as typed" }));
  for (let i = 0; i < 4; i += 1) await act(async () => void (await Promise.resolve()));
  const posts = apiFetch.mock.calls.filter(([, init]) => init?.method === "POST");
  expect(posts).toHaveLength(1);
  const body = JSON.parse(String(posts[0]?.[1]?.body)) as Record<string, unknown>;
  expect(body).toMatchObject({ symbol: "ADAUSDT", confirm_symbol: "adausdt" });
  expect(screen.getByRole("dialog")).toHaveTextContent(
    "Not started: the server refused it. (purge_confirmation_mismatch)",
  );
});
