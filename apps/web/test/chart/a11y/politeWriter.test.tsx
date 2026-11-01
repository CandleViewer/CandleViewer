import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, render, screen, waitFor } from "@testing-library/react";
import { useEffect } from "react";
import { PreferencesProvider } from "../../../src/features/a11y-preferences";
import {
  ShellAnnouncer,
  announce,
  clearAnnouncements,
} from "../../../src/features/app-shell/announcer";
import {
  AMBIENT_CADENCE_MS,
  createAmbientWriter,
  sayToShell,
  useAmbientWriter,
  type AmbientWriter,
  type AnnouncePrefs,
} from "../../../src/chart/a11y/politeWriter";

const ALWAYS: AnnouncePrefs = { announce_prices: "always", verbosity: "normal" };

function writer(prefs: AnnouncePrefs = ALWAYS) {
  const say = vi.fn<(p: "polite" | "assertive", text: string) => void>();
  const w = createAmbientWriter({ fields: ["last", "bid"], prefs: () => prefs, say });
  return { w, say };
}

beforeEach(() => {
  vi.useFakeTimers();
  clearAnnouncements();
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  clearAnnouncements();
});

describe("ambient writer: throttled, latest wins (05 §6.2)", () => {
  it("20 Hz for 10 s: at most one polite write per 2 s, each carrying the latest value", () => {
    const { w, say } = writer();
    let price = 64000;
    for (let tick = 0; tick < 200; tick++) {
      price += 0.5;
      w.set("last", `Last price ${price}`);
      vi.advanceTimersByTime(50);
    }
    vi.advanceTimersByTime(AMBIENT_CADENCE_MS);
    const writes = say.mock.calls;
    expect(writes.length).toBeLessThanOrEqual(10_000 / AMBIENT_CADENCE_MS + 1);
    expect(writes.every(([p]) => p === "polite")).toBe(true);
    expect(writes.at(-1)?.[1]).toBe(`Last price ${price}`);
  });

  it("the first value is said at once, later ones wait out the cadence", () => {
    const { w, say } = writer();
    w.set("last", "Last price 1");
    vi.advanceTimersByTime(0);
    expect(say).toHaveBeenCalledTimes(1);
    w.set("last", "Last price 2");
    vi.advanceTimersByTime(AMBIENT_CADENCE_MS - 1);
    expect(say).toHaveBeenCalledTimes(1);
    vi.advanceTimersByTime(1);
    expect(say).toHaveBeenLastCalledWith("polite", "Last price 2");
  });

  it("fields due together are one message, in field order", () => {
    const { w, say } = writer();
    w.set("bid", "Best bid 9");
    w.set("last", "Last price 10");
    vi.advanceTimersByTime(0);
    expect(say).toHaveBeenCalledWith("polite", "Last price 10. Best bid 9");
  });

  it("announce_prices off says nothing; significant lets only significant values through", () => {
    const off = writer({ announce_prices: "off", verbosity: "normal" });
    off.w.set("last", "x", true);
    vi.runAllTimers();
    expect(off.say).not.toHaveBeenCalled();
    const sig = writer({ announce_prices: "significant", verbosity: "normal" });
    sig.w.set("last", "ordinary");
    vi.runAllTimers();
    expect(sig.say).not.toHaveBeenCalled();
    sig.w.set("last", "Last price crossed 65,000", true);
    vi.runAllTimers();
    expect(sig.say).toHaveBeenCalledWith("polite", "Last price crossed 65,000");
  });

  it("a disconnect is assertive at once and drops the pending stale values", () => {
    const { w, say } = writer();
    w.set("last", "Last price 1");
    vi.advanceTimersByTime(0);
    w.set("last", "Last price 2");
    w.alert("Disconnected");
    expect(say).toHaveBeenLastCalledWith("assertive", "Disconnected");
    vi.runAllTimers();
    expect(say).toHaveBeenCalledTimes(2);
  });

  it("teardown: dispose cancels the pending write and silences the writer", () => {
    const { w, say } = writer();
    w.set("last", "Last price 1");
    w.dispose();
    vi.runAllTimers();
    w.set("last", "Last price 2");
    w.alert("Disconnected");
    vi.runAllTimers();
    expect(say).not.toHaveBeenCalled();
    expect(vi.getTimerCount()).toBe(0);
  });

  it("never cuts another writer's polite message inside the shell's region budget", () => {
    const { w, say } = writer();
    announce("polite", "Order filled", "other:1");
    w.set("last", "Last price 1");
    vi.advanceTimersByTime(4_999);
    expect(say).not.toHaveBeenCalled();
    vi.advanceTimersByTime(1);
    expect(say).toHaveBeenCalledTimes(1);
  });

  it("an unchanged value is not said again; a changed one is", () => {
    const { w, say } = writer();
    w.set("last", "Last price 1");
    vi.advanceTimersByTime(0);
    for (let i = 0; i < 5; i++) {
      w.set("last", "Last price 1");
      vi.advanceTimersByTime(AMBIENT_CADENCE_MS);
    }
    expect(say).toHaveBeenCalledTimes(1);
    w.set("last", "Last price 2");
    w.set("last", "Last price 1"); // back to what was said before the window closed: nothing new
    vi.runAllTimers();
    expect(say).toHaveBeenCalledTimes(1);
    w.alert("Disconnected");
    w.set("last", "Last price 1"); // after a disconnect the value is news again
    vi.runAllTimers();
    expect(say).toHaveBeenLastCalledWith("polite", "Last price 1");
  });

  it("a cadence read live keeps the pending value when the cadence changes", () => {
    let cadence = AMBIENT_CADENCE_MS;
    const say = vi.fn<(p: "polite" | "assertive", text: string) => void>();
    const w = createAmbientWriter({
      fields: ["last"],
      prefs: () => ALWAYS,
      say,
      cadenceMs: () => cadence,
    });
    w.set("last", "Last price 1");
    vi.advanceTimersByTime(0);
    cadence = 5_000;
    w.set("last", "Last price 2");
    vi.advanceTimersByTime(4_999);
    expect(say).toHaveBeenCalledTimes(1);
    vi.advanceTimersByTime(1);
    expect(say).toHaveBeenLastCalledWith("polite", "Last price 2");
  });

  it("refuses an undeclared field", () => {
    expect(() => writer().w.set("mark", "x")).toThrow(RangeError);
  });
});

describe("the shell path", () => {
  it("sayToShell writes the shell's one region, and the same words can be said again", () => {
    render(<ShellAnnouncer />);
    act(() => sayToShell("polite", "Chart"));
    expect(screen.getByText("Chart")).toBeInTheDocument();
    act(() => sayToShell("polite", "Chart"));
    expect(screen.getAllByText("Chart")).toHaveLength(1);
    act(() => sayToShell("assertive", "Disconnected"));
    expect(screen.getByText("Disconnected").closest("[aria-live]")).toHaveAttribute(
      "aria-live",
      "assertive",
    );
  });
});

describe("useAmbientWriter", () => {
  function Child({ w }: { w: AmbientWriter }): null {
    useEffect(() => w.alert("Disconnected"), [w]);
    return null;
  }
  function Host(): JSX.Element {
    const w = useAmbientWriter(["last"]);
    return <Child w={w} />;
  }

  it("a write from a child's mount effect, before the hook's own effect, is heard", async () => {
    vi.useRealTimers();
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({}) }),
    );
    render(
      <PreferencesProvider>
        <ShellAnnouncer />
        <Host />
      </PreferencesProvider>,
    );
    await waitFor(() =>
      expect(document.querySelector('[aria-live="assertive"]')).toHaveTextContent("Disconnected"),
    );
  });

  it("is silent after unmount", () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({}) }),
    );
    let captured: AmbientWriter | null = null;
    function Grab(): null {
      captured = useAmbientWriter(["last"]);
      return null;
    }
    const view = render(
      <PreferencesProvider>
        <ShellAnnouncer />
        <Grab />
      </PreferencesProvider>,
    );
    view.unmount();
    (captured as AmbientWriter | null)?.alert("Disconnected");
    vi.runAllTimers();
    expect(vi.getTimerCount()).toBe(0);
    expect(document.body).not.toHaveTextContent("Disconnected");
  });
});
