/**
 * E16-S01 PR 3, the recorder's step-up host (#485/#486 BQ-7) and the guard every dialog that hosts it gets
 * (S-5353-01): a write on the wire keeps its dialog's view (H22); whatever closes the dialog clears the host; a
 * challenge that answers a write started before that clear is dropped, said "Not sent" once at the point of action
 * and never re-sent; a later opening mounts no earlier challenge, only its own. A stubbed `apiFetch` (no network,
 * C-13.5); the `22` examples' clock.
 */
import { act, fireEvent, render, screen } from "@testing-library/react";
import { useState, type JSX } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { apiFetch } = vi.hoisted(() => ({
  apiFetch: vi.fn<(url: string, init?: RequestInit) => Promise<Response>>(),
}));
vi.mock("../../../src/lib/http/csrfFetch", () => ({ apiFetch }));

import { recorderApi } from "../../../src/features/recorder/recorderApi";
import { useStepUpHost } from "../../../src/features/recorder/stepUpHost";
import { stepUpRequired } from "./fixtures";
import { NOW } from "./gridFixtures";

const json = (status: number, body?: unknown): Response =>
  new Response(body === undefined ? null : JSON.stringify(body), { status });
const settle = async (): Promise<void> => {
  for (let i = 0; i < 4; i += 1) await act(async () => void (await Promise.resolve()));
};
/** The PUTs sent, by their Idempotency-Key. */
const keys = (): (string | null)[] =>
  apiFetch.mock.calls
    .filter(([, init]) => init?.method === "PUT")
    .map(([, init]) => new Headers(init?.headers).get("Idempotency-Key"));
/** Answers each PUT with the next deferred reply, released by the test. */
function deferred(): (response: Response) => void {
  let release: (response: Response) => void = () => undefined;
  apiFetch.mockImplementation(
    () =>
      new Promise<Response>((resolve) => {
        release = resolve;
      }),
  );
  return (response) => release(response);
}
/** Holds every PUT; `release(n, response)` answers the n-th sent. */
function holdEach(): (n: number, response: Response) => void {
  const held: ((response: Response) => void)[] = [];
  apiFetch.mockImplementation(() => new Promise<Response>((resolve) => void held.push(resolve)));
  return (n, response) => held[n]?.(response);
}

const said: string[] = [];
let closeFromOutside: () => void = () => undefined;

/** A dialog that hosts the step-up: Send pins, Cancel goes through the host, and the page may close it. */
function Page({ readBack = () => undefined }: { readonly readBack?: () => unknown }): JSX.Element {
  const [open, setOpen] = useState(false);
  const [answer, setAnswer] = useState<string | null>(null);
  const stepUp = useStepUpHost(readBack, "Recorded symbols", {
    say: (text) => void said.push(text),
  });
  closeFromOutside = () => {
    stepUp.clear(); // whatever closes the dialog clears the host (S-5353-01 (b))
    setOpen(false);
  };
  const send = (): Promise<void> =>
    stepUp.start(async (route) => {
      const res = await recorderApi.pin("id-btcusdt", { pinned: true });
      route("pinRecordedSymbol", res, (r) => setAnswer(`answered ${r.status}`));
    });
  return (
    <>
      <button
        type="button"
        onClick={() => {
          stepUp.clear();
          setOpen(true);
        }}
      >
        Open
      </button>
      {open ? (
        <div role="dialog" aria-label="Keep BTCUSDT data forever?">
          <button type="button" onClick={() => void send()}>
            Send
          </button>
          <button type="button" onClick={() => stepUp.cancel(() => setOpen(false))}>
            Cancel
          </button>
          {answer}
          {stepUp.gate}
        </div>
      ) : null}
    </>
  );
}

const dialog = (): HTMLElement | null =>
  screen.queryByRole("dialog", { name: "Keep BTCUSDT data forever?" });
const challenge = (): HTMLElement | null =>
  screen.queryByRole("alertdialog", { name: "Confirm with two-factor" });
const click = (name: string): void => void fireEvent.click(screen.getByRole("button", { name }));

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"], now: NOW });
  said.length = 0;
});
afterEach(() => {
  apiFetch.mockReset();
  vi.useRealTimers();
});

describe("the step-up host's guard (S-5353-01; H22)", () => {
  it("(a) while its write is on the wire, Cancel keeps the dialog and its answer lands there; then Cancel closes", async () => {
    const release = deferred();
    render(<Page />);
    click("Open");
    click("Send");
    await settle();
    click("Cancel");
    expect(dialog()).not.toBeNull();
    release(json(200, { id: "id-btcusdt", symbol: "BTCUSDT", pinned: true }));
    await settle();
    expect(dialog()).toHaveTextContent("answered 200");
    click("Cancel");
    expect(dialog()).toBeNull();
  });

  it("(c) a challenge for a write whose dialog closed meanwhile is dropped: no SCR-006, Not sent once, never re-sent", async () => {
    const release = deferred();
    render(<Page />);
    click("Open");
    click("Send");
    await settle();
    act(() => closeFromOutside());
    release(json(403, stepUpRequired));
    await settle();
    expect(challenge()).toBeNull();
    expect(said).toEqual(["Not sent"]);
    // (b) The next opening mounts no earlier challenge: nothing until its own press, which is a new request.
    click("Open");
    expect(challenge()).toBeNull();
    expect(keys()).toHaveLength(1);
    const again = deferred();
    click("Send");
    await settle();
    again(json(403, stepUpRequired));
    await settle();
    expect(challenge()).not.toBeNull();
    expect(keys()).toHaveLength(2);
    expect(keys()[1]).not.toBe(keys()[0]);
    expect(said).toEqual(["Not sent"]);
  });

  it("a challenge for the open dialog's write is held there, as before: SCR-006 opens inside it", async () => {
    const release = deferred();
    render(<Page />);
    click("Open");
    click("Send");
    await settle();
    release(json(403, stepUpRequired));
    await settle();
    expect(challenge()).not.toBeNull();
    expect(dialog()?.contains(challenge())).toBe(true);
    expect(said).toEqual([]);
  });

  it("a write's challenge is its own opening's: one that lands after a later opening's write started is dropped, Not sent once; that write's opens its own (S-5347-d01)", async () => {
    const release = holdEach();
    render(<Page />);
    click("Open");
    click("Send"); // A, in the first opening
    await settle();
    act(() => closeFromOutside());
    click("Open");
    click("Send"); // B, in the next opening, while A is still on the wire
    await settle();
    release(0, json(403, stepUpRequired)); // A's challenge lands under B's dialog
    await settle();
    expect(challenge()).toBeNull();
    expect(said).toEqual(["Not sent"]);
    release(1, json(403, stepUpRequired));
    await settle();
    expect(challenge()).not.toBeNull();
    expect(dialog()?.contains(challenge())).toBe(true);
    expect(said).toEqual(["Not sent"]);
    expect(keys()).toHaveLength(2);
  });

  it("a write that never answers keeps the dialog for the re-send's bound; then Cancel closes it: Outcome pending, read again (C-5347-d03)", async () => {
    const readBack = vi.fn();
    const release = deferred();
    render(<Page readBack={readBack} />);
    click("Open");
    click("Send");
    await settle();
    act(() => void vi.advanceTimersByTime(9_999));
    click("Cancel");
    expect(dialog()).not.toBeNull();
    expect(said).toEqual([]);
    act(() => void vi.advanceTimersByTime(1));
    click("Cancel");
    expect(dialog()).toBeNull();
    expect(said).toEqual(["Outcome pending, see Recorded symbols"]);
    expect(readBack).toHaveBeenCalledTimes(1);
    // Its late challenge is the closed opening's: dropped and said, never parked for the next one.
    release(json(403, stepUpRequired));
    await settle();
    click("Open");
    expect(challenge()).toBeNull();
    expect(said).toEqual(["Outcome pending, see Recorded symbols", "Not sent"]);
  });
});
