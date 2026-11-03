import { createRequire } from "node:module";
import { useLayoutEffect } from "react";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ShellAnnouncer, clearAnnouncements } from "../../../src/features/app-shell/announcer";
import {
  BACK_NOTE,
  takeExitRowFocus,
  type ExitOutcome,
} from "../../../src/features/view-as/exitViewAs";
import {
  EXIT_FAILED_ID,
  ViewAsBanner,
  ViewAsBannerView,
} from "../../../src/features/view-as/ViewAsBanner";
import { showHeldBoot } from "../../../src/features/view-as/heldBoot";
import { VA_COPY } from "../../../src/features/view-as/copy";
import { documentTitle } from "../../../src/routes/titles";
import {
  resetShellState,
  setShellState,
  type HeldViewAs,
} from "../../../src/shell/bootstrap/store";

/**
 * E42-S03 (SCR-124; E42-D03 §10, D24, §13): the banner is a region named "View-as", never live;
 * Exit is its one control (Enter or Space leaves, Esc never does); its glyph changes at 5:00 and
 * 1:00 on the server's clock; it speaks through the shell announcer, once per mark, never per tick.
 */
const axe = createRequire(createRequire(import.meta.url).resolve("@axe-core/playwright"))(
  "axe-core",
) as { run: (el: Element, o?: object) => Promise<{ violations: { impact?: string | null }[] }> };
const seriousAxe = async (el: Element): Promise<unknown[]> =>
  (await axe.run(el, { rules: { "color-contrast": { enabled: false } } })).violations.filter(
    (v) => v.impact === "serious" || v.impact === "critical",
  );

const EXPIRES = Date.parse("2026-09-14T10:30:00Z");
/** The server's clock runs 4 s behind the client's: every count reads the server's. */
const OFFSET = -4_000;
const HELD: HeldViewAs = {
  kind: "held",
  targetId: "9f1c2b4e-0a1d-4f2b-9e3a-11c0ffee0002",
  targetName: "alex",
  startedAtMs: EXPIRES - 1_800_000,
  expiresAtMs: EXPIRES,
  state: "active",
  offsetMs: OFFSET,
};
/** Sets the client clock so that `ms` are left on the server's. */
const leave = (ms: number): void => {
  vi.setSystemTime(EXPIRES - ms - OFFSET);
};

const banner = (): HTMLElement => screen.getByRole("region", { name: "View-as" });
const exitButton = (): HTMLElement => within(banner()).getByRole("button", { name: VA_COPY.exit });
const liveText = (live: "polite" | "assertive"): string | null =>
  document.querySelector(`[aria-live="${live}"] p`)?.textContent ?? null;
const liveSeq = (live: "polite" | "assertive"): string | null =>
  document.querySelector(`[aria-live="${live}"] p`)?.getAttribute("data-seq") ?? null;

/** Exit's call, answering `outcome`. */
const exitWith = (outcome: ExitOutcome) => vi.fn(async (): Promise<ExitOutcome> => outcome);

function mount(held: HeldViewAs = HELD, onExit = exitWith("leaving")) {
  render(
    <>
      <ViewAsBannerView held={held} onExit={onExit} />
      <ShellAnnouncer />
    </>,
  );
  return onExit;
}

beforeEach(() => {
  vi.useFakeTimers({
    toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval", "Date"],
  });
  leave(1_660_000); // 27:40
});
afterEach(() => {
  act(() => {
    clearAnnouncements();
    resetShellState();
  });
  vi.useRealTimers();
  window.sessionStorage.clear();
});

describe("SCR-124 V-4: the live banner", () => {
  it("is a region named View-as with the read-only words, the count and the notice; no live role", async () => {
    mount();
    const region = banner();
    expect(region.tagName).toBe("SECTION");
    // va.banner_ro's sentences (the count's digits, then CMP-035's spoken twin), then va.notified
    expect(within(region).getByText("Viewing as alex (read-only).")).toBeInTheDocument();
    expect(region).toHaveTextContent("Ends in 27:4027 minutes 40 seconds. alex has been notified.");
    expect(region).toHaveAttribute("data-phase", "normal");
    expect(region.querySelector('[role="status"], [role="alert"]')).toBeNull();
    const live = [...region.querySelectorAll("[aria-live]")].map((el) =>
      el.getAttribute("aria-live"),
    );
    expect(live.every((value) => value === "off")).toBe(true);
    vi.useRealTimers();
    expect(await seriousAxe(region)).toEqual([]);
  });

  it("makes Exit its first and only Tab stop", () => {
    mount();
    const stops = [...banner().querySelectorAll<HTMLElement>("a[href], button, input, [tabindex]")];
    expect(stops).toEqual([exitButton()]);
  });

  it("leaves on Exit's press (Enter and Space press a button); Esc never does", async () => {
    const onExit = mount();
    act(() => exitButton().focus());
    fireEvent.keyDown(exitButton(), { key: "Escape" });
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onExit).not.toHaveBeenCalled();
    fireEvent.click(exitButton());
    await act(async () => {});
    expect(onExit).toHaveBeenCalledTimes(1);
    expect(exitButton()).toHaveAttribute("aria-busy", "true"); // the page is leaving
    fireEvent.click(exitButton());
    await act(async () => {});
    expect(onExit).toHaveBeenCalledTimes(1);
  });

  it("says va.announce_ro once on entry, assertively", () => {
    mount();
    expect(liveText("assertive")).toBe("Viewing as alex, read-only. Exit view-as.");
  });

  it("changes only the glyph at 5:00 and 1:00 on the server's clock, each said once, never per tick", () => {
    mount();
    expect(banner().querySelector("[data-glyph]")).toBeNull();
    const entrySeq = liveSeq("assertive");
    act(() => void vi.advanceTimersByTime(1_660_000 - 300_001));
    expect(banner()).toHaveAttribute("data-phase", "normal");
    expect(liveText("polite")).toBeNull();
    act(() => void vi.advanceTimersByTime(1));
    expect(banner()).toHaveAttribute("data-phase", "five");
    expect(banner().querySelector("[data-glyph]")).toHaveAttribute("data-glyph", "warning");
    expect(banner()).toHaveTextContent("Ends in 5:005 minutes.");
    expect(liveText("polite")).toBe("View-as ends in 5 minutes.");
    const fiveSeq = liveSeq("polite");
    act(() => void vi.advanceTimersByTime(30_000));
    expect([liveSeq("polite"), liveSeq("assertive")]).toEqual([fiveSeq, entrySeq]); // ticks say nothing
    act(() => void vi.advanceTimersByTime(210_000));
    expect(banner()).toHaveAttribute("data-phase", "one");
    expect(banner().querySelector("[data-glyph]")).toHaveAttribute("data-glyph", "danger");
    expect(liveText("assertive")).toBe("View-as ends in 1 minute.");
    const oneSeq = liveSeq("assertive");
    act(() => void vi.advanceTimersByTime(59_000));
    expect([liveSeq("polite"), liveSeq("assertive")]).toEqual([fiveSeq, oneSeq]);
    expect(banner()).toHaveTextContent("Ends in 0:011 second.");
  });

  it("says no mark the page loaded past: at 3:00 only the entry, then 1:00", () => {
    leave(180_000);
    mount();
    expect(banner()).toHaveAttribute("data-phase", "five");
    expect(liveText("polite")).toBeNull();
    act(() => void vi.advanceTimersByTime(120_000));
    expect(liveText("assertive")).toBe("View-as ends in 1 minute.");
  });

  it("looks again when a mark's timer fires with the page clock 1 ms short: 5:00 and 1:00 still come, once each", () => {
    let lag = 0;
    render(
      <>
        <ViewAsBannerView held={HELD} now={() => Date.now() - lag} onExit={exitWith("leaving")} />
        <ShellAnnouncer />
      </>,
    );
    lag = 1; // the page clock steps 1 ms back while the timer waits: a clock sync, a resume
    act(() => void vi.advanceTimersByTime(1_660_000 - 300_000)); // fires: 5:00.001 on the page clock
    expect(banner()).toHaveAttribute("data-phase", "normal");
    act(() => void vi.advanceTimersByTime(1));
    expect(banner()).toHaveAttribute("data-phase", "five");
    expect(liveText("polite")).toBe("View-as ends in 5 minutes.");
    const fiveSeq = liveSeq("polite");
    lag = 2; // and once more before the next mark
    act(() => void vi.advanceTimersByTime(240_000));
    expect(banner()).toHaveAttribute("data-phase", "five");
    act(() => void vi.advanceTimersByTime(1));
    expect(banner()).toHaveAttribute("data-phase", "one");
    expect(liveText("assertive")).toBe("View-as ends in 1 minute.");
    const oneSeq = liveSeq("assertive");
    act(() => void vi.advanceTimersByTime(30_000));
    expect([liveSeq("polite"), liveSeq("assertive")]).toEqual([fiveSeq, oneSeq]);
  });

  it("looks again when the wall clock steps back 2 s between arming and firing", () => {
    mount();
    act(() => void vi.advanceTimersByTime(1_000_000)); // 11:00 left; the 5:00 timer waits on
    vi.setSystemTime(Date.now() - 2_000); // `Date` steps back; the timer does not
    act(() => void vi.advanceTimersByTime(360_000)); // it fires: the page clock reads 5:02
    expect(banner()).toHaveAttribute("data-phase", "normal");
    expect(liveText("polite")).toBeNull();
    act(() => void vi.advanceTimersByTime(2_000));
    expect(banner()).toHaveAttribute("data-phase", "five");
    expect(liveText("polite")).toBe("View-as ends in 5 minutes.");
    const fiveSeq = liveSeq("polite");
    vi.setSystemTime(Date.now() - 2_000); // and again before 1:00
    act(() => void vi.advanceTimersByTime(240_000));
    act(() => void vi.advanceTimersByTime(2_000));
    expect(banner()).toHaveAttribute("data-phase", "one");
    expect(liveText("assertive")).toBe("View-as ends in 1 minute.");
    expect(liveSeq("polite")).toBe(fiveSeq);
  });
});

describe("SCR-124 V-8: held once the server ended it", () => {
  it("reads va.ended with no count, keeps Exit, and says it once, assertively", async () => {
    mount({ ...HELD, state: "expired" });
    expect(banner()).toHaveTextContent("Viewing as alex ended. Exit to return to your own view.");
    expect(banner()).not.toHaveTextContent("Ends in");
    expect(banner().querySelector('[data-cmp="CMP-035"]')).toBeNull();
    expect(exitButton()).toBeInTheDocument();
    expect(liveText("assertive")).toBe("Viewing as alex ended. Exit to return to your own view.");
    vi.useRealTimers();
    expect(await seriousAxe(banner())).toEqual([]);
  });

  it("moves from live to ended when the context it shows does, and says so once", () => {
    const { rerender } = render(
      <>
        <ViewAsBannerView held={HELD} onExit={exitWith("leaving")} />
        <ShellAnnouncer />
      </>,
    );
    rerender(
      <>
        <ViewAsBannerView held={{ ...HELD, state: "expired" }} onExit={exitWith("leaving")} />
        <ShellAnnouncer />
      </>,
    );
    expect(banner()).toHaveAttribute("data-phase", "ended");
    expect(liveText("assertive")).toBe("Viewing as alex ended. Exit to return to your own view.");
  });

  it("draws va.ended in the very commit the context ends in, never a frame of the live copy", () => {
    const drawn: string[] = [];
    /** Reads the banner after each commit of the tree, before its effects run. */
    function Painted(): null {
      useLayoutEffect(() => void drawn.push(banner().textContent ?? ""));
      return null;
    }
    const tree = (held: HeldViewAs) => (
      <>
        <ViewAsBannerView held={held} onExit={exitWith("leaving")} />
        <Painted />
      </>
    );
    const { rerender } = render(tree(HELD));
    drawn.length = 0;
    rerender(tree({ ...HELD, state: "expired" }));
    expect(drawn[0]).toContain("Viewing as alex ended.");
    expect(drawn[0]).not.toContain("Ends in");
  });
});

describe("SCR-124 V-14: Exit failed", () => {
  it("keeps the banner and focus on Exit, shows va.exit_failed under it, says it once per failure", async () => {
    const onExit = mount(HELD, exitWith("failed"));
    act(() => exitButton().focus());
    fireEvent.click(exitButton());
    await act(async () => {});
    const failed = document.getElementById(EXIT_FAILED_ID);
    expect(failed).toHaveTextContent("Couldn't end view-as — try again.");
    expect(exitButton()).toHaveAttribute("aria-describedby", EXIT_FAILED_ID);
    expect(exitButton()).not.toHaveAttribute("aria-busy");
    expect(document.activeElement).toBe(exitButton());
    expect(liveText("assertive")).toBe("Couldn't end view-as — try again.");
    const first = liveSeq("assertive");
    fireEvent.click(exitButton());
    await act(async () => {});
    expect(onExit).toHaveBeenCalledTimes(2);
    expect(liveSeq("assertive")).not.toBe(first); // the second failure is said too
    vi.useRealTimers();
    expect(await seriousAxe(banner())).toEqual([]);
  });

  it("leaves an idle-locked Exit to SCR-005: no V-14, nothing said, Exit pressable again", async () => {
    const onExit = mount(HELD, exitWith("locked"));
    const entry = liveSeq("assertive");
    fireEvent.click(exitButton());
    await act(async () => {});
    expect(document.getElementById(EXIT_FAILED_ID)).toBeNull();
    expect(exitButton()).not.toHaveAttribute("aria-describedby");
    expect(exitButton()).not.toHaveAttribute("aria-busy");
    expect(liveSeq("assertive")).toBe(entry);
    fireEvent.click(exitButton());
    await act(async () => {});
    expect(onExit).toHaveBeenCalledTimes(2);
  });
});

describe("the shell's view-as slot (ViewAsBanner)", () => {
  it("renders nothing while the session views as no one, or before the boot read", () => {
    const { container } = render(<ViewAsBanner />);
    expect(container).toBeEmptyDOMElement();
    act(() => setShellState({ viewAs: { kind: "none" } }));
    expect(container).toBeEmptyDOMElement();
    act(() => setShellState({ viewAs: HELD }));
    expect(banner()).toBeInTheDocument();
  });

  it("says va.back politely once after an Exit's load, forgets the note, keeps its id for SCR-121", () => {
    // Exit's note, 1.5 s before: its time and the target's id
    window.sessionStorage.setItem(BACK_NOTE, `${Date.now() - 1_500}:${HELD.targetId}`);
    render(
      <>
        <ViewAsBanner />
        <ShellAnnouncer />
      </>,
    );
    expect(liveText("polite")).toBe("Back to your own view");
    expect(window.sessionStorage.getItem(BACK_NOTE)).toBeNull();
    expect([takeExitRowFocus(), takeExitRowFocus()]).toEqual([HELD.targetId, null]);
  });
});

describe("the held boot (V-8 at load)", () => {
  /** The session read in the hold (`GET /auth/session`, an own operation): idle-locked or not. */
  let locked = false;
  const sessionClock = () => ({
    server_time: new Date().toISOString(),
    session: {
      id: "5b1f0c3e-7d2a-4c11-9e8f-0a1b2c3d4e5f",
      issued_at: new Date(Date.now() - 3_600_000).toISOString(),
      expires_at: new Date(Date.now() + 3_600_000).toISOString(),
      idle_deadline: new Date(Date.now() + 900_000).toISOString(),
      idle_timeout_s: 900,
      locked,
    },
  });
  /** The server in the hold: the session reads, and Exit's `DELETE` gets `exit`. */
  function serve(exit: () => Response = () => new Response(null, { status: 204 })): void {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const path = new URL(String(input), window.location.origin).pathname;
        if (path === "/api/v1/auth/session")
          return new Response(JSON.stringify(sessionClock()), { status: 200 });
        if (path === "/api/v1/auth/session/view-as" && init?.method === "DELETE") return exit();
        return new Response(null, { status: 404 });
      }),
    );
  }
  async function boot(): Promise<() => void> {
    act(() => setShellState({ viewAs: { ...HELD, state: "expired" } }));
    const host = document.body.appendChild(document.createElement("div"));
    const { createRoot } = await import("react-dom/client");
    const root = createRoot(host);
    await act(async () => showHeldBoot(root));
    return () => {
      act(() => root.unmount());
      host.remove();
    };
  }
  beforeEach(() => {
    locked = false;
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    document.title = "";
  });

  it("renders the banner first, then one main with its h1; Exit is the first Tab stop", async () => {
    serve();
    const unmount = await boot();
    const region = banner();
    expect(
      region.compareDocumentPosition(screen.getByRole("main")) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(screen.getByRole("heading", { level: 1, name: "View-as" })).toBeInTheDocument();
    const stops = [...document.querySelectorAll<HTMLElement>("a[href], button, [tabindex]")].filter(
      (el) => el.tabIndex >= 0,
    );
    expect(stops[0]).toBe(exitButton());
    expect(liveText("assertive")).toBe("Viewing as alex ended. Exit to return to your own view.");
    unmount();
  });

  it("names the page apart from the app's other windows: View-as ended (WCAG 2.4.2)", async () => {
    serve();
    const unmount = await boot();
    expect(document.title).toBe(documentTitle("View-as ended"));
    unmount();
  });

  it("hands an idle-locked Exit to SCR-005, whose host the page mounts, never to V-14", async () => {
    vi.useRealTimers();
    serve(() => {
      locked = true; // the session idle-locked meanwhile: Exit is refused, nothing changed
      const body = JSON.stringify({ status: 401, code: "session_idle_locked" });
      return new Response(body, { status: 401 });
    });
    const unmount = await boot();
    expect(screen.queryByRole("alertdialog")).toBeNull();
    fireEvent.click(exitButton());
    expect(await screen.findByRole("alertdialog", { name: "Session locked" })).toBeInTheDocument();
    expect(document.getElementById(EXIT_FAILED_ID)).toBeNull();
    expect(screen.queryByText(VA_COPY.exitFailed)).toBeNull();
    unmount();
  });
});
