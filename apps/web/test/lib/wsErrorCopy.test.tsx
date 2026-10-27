// #415 (E17-X02), accessibility note: the default WS error copy shows no `request_id`,
// `connection_id` or `git_sha`. The client does receive them (`err.request_id` and
// `welcome.connection_id` reach the state's `diagnostics`, kept for a "copy details" affordance only),
// so each WS error code is fed with all three in its frame, and the copy is read from the
// accessibility tree. NOT RUN: the keyboard reach and the label of "copy details", as no such
// affordance exists yet.
import { WS_ERROR_CODES } from "@candleviewer/protocol";
import { act, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { WsErrorHost } from "../../src/lib/ws/WsErrorHost";
import { handleWsError } from "../../src/lib/ws/errorHandler";
import { shim, WAIT } from "./ws/support/portShim";

const IDS = {
  request_id: "urn:cv:req:0193f2bd-4411-7c02-9911-aa22bb33cc44",
  connection_id: "ws_0193f2bc1d40",
  git_sha: "a91f0c3",
};
const MESSAGE = Object.entries(IDS)
  .map((entry) => entry.join("="))
  .join(" ");
const NAMES = /request[_ ]?id|connection[_ ]?id|git[_ ]?sha/i;
const VALUES = [...Object.values(IDS), "ws_1"]; // "ws_1" is the fake gateway's connection id

beforeEach(() => void vi.spyOn(console, "error").mockImplementation(() => undefined));
afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
});

/** What the accessibility tree shows of the host: every dialog, status and button, text and label. */
const copy = (): string =>
  ["alertdialog", "status", "button"]
    .flatMap((role) => screen.queryAllByRole(role))
    .flatMap((el) => [el.textContent, el.getAttribute("aria-label")])
    .join(" ");

it("no WS error code puts a request, connection or build id into the default copy", () => {
  expect(WS_ERROR_CODES.length).toBeGreaterThan(20); // an emptied registry must not pass vacuously
  for (const code of WS_ERROR_CODES) {
    const { unmount } = render(<WsErrorHost />);
    act(() => void handleWsError({ t: "err", p: { code, message: MESSAGE, ...IDS } }));
    expect(copy(), code).toContain(code); // the host did show this error
    expect(copy(), code).not.toMatch(NAMES);
    expect(
      VALUES.filter((value) => copy().includes(value)),
      code,
    ).toEqual([]);
    unmount();
  }
});

it("the ids reach the client's diagnostics, and still not the copy", async () => {
  // the real path: the worker's host over the fake gateway, and a tab at the far end of a message port
  const { gateway, tab } = shim();
  const { client } = tab();
  render(<WsErrorHost />);
  await waitFor(() => expect(client.getState().transport).toBe("connected"), WAIT);
  const p = { code: "internal_error", message: "m", request_id: IDS.request_id };
  gateway.latest.send({ t: "err", p });
  await waitFor(() => expect(copy()).toContain("internal_error"), WAIT);
  expect(client.getState().diagnostics).toEqual({
    connectionId: "ws_1",
    requestId: IDS.request_id,
  });
  expect(copy()).not.toMatch(NAMES);
  expect(VALUES.filter((value) => copy().includes(value))).toEqual([]);
});
