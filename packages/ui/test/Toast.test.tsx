// @vitest-environment jsdom
import { act, useState, type JSX } from "react";
import { expect, fireEvent, within } from "storybook/test";
import { afterEach, beforeEach, describe, it, vi } from "vitest";
import {
  Button,
  Dialog,
  Toast,
  ToastRegion,
  type ToastAnnounce,
  type ToastItem,
  type ToastRegionProps,
} from "../src/components/index.js";
import { mount } from "./theme/mount.js";

const screen = (): ReturnType<typeof within> => within(document.body);
const press = async (key: string): Promise<void> => {
  await act(async () => {
    fireEvent.keyDown(document.activeElement ?? document.body, { key });
  });
};
const click = async (element: Element): Promise<void> => {
  await act(async () => {
    fireEvent.click(element);
  });
};
const focus = async (element: HTMLElement): Promise<void> => {
  await act(async () => element.focus());
};
const advance = async (ms: number): Promise<void> => {
  await act(async () => {
    vi.advanceTimersByTime(ms);
  });
};

describe("Toast (CMP-045)", () => {
  it("is a group named by its title, never a live region, with the glyph hidden", async () => {
    const host = await mount(
      <Toast
        kicker="Warning · Alert"
        title="BTC above 65k"
        description="Last price 65,012.5 crossed above 65,000"
        meta="BTCUSDT · 5m"
        tone="warning"
        onDismiss={() => undefined}
      />,
    );
    const group = within(host).getByRole("group", { name: "BTC above 65k" });
    await expect(group).toHaveAttribute("data-tone", "warning");
    await expect(group).toHaveTextContent("Warning · Alert");
    await expect(group).toHaveTextContent("BTCUSDT · 5m");
    await expect(within(host).queryByRole("status")).toBeNull();
    await expect(within(host).queryByRole("alert")).toBeNull();
    await expect(host.querySelector(".cv-toast__glyph svg")).toHaveAttribute("aria-hidden", "true");
    await expect(
      within(host).getByRole("button", { name: "Dismiss BTC above 65k" }),
    ).toBeInTheDocument();
  });

  it("renders no dismiss button when not dismissible", async () => {
    const host = await mount(
      <Toast
        title="Order rejected"
        tone="danger"
        dismissible={false}
        onDismiss={() => undefined}
      />,
    );
    await expect(within(host).queryByRole("button")).toBeNull();
  });

  it("gated actions keep their names, stay focusable and point at one reason line", async () => {
    const onClick = vi.fn();
    const onRefuse = vi.fn();
    const reason = "Your role can't change alerts.";
    const host = await mount(
      <Toast
        title="BTC above 65k"
        actions={[
          { label: "Open chart", onClick },
          { label: "Snooze", onClick, disabledReason: reason },
          { label: "Disable", onClick, disabledReason: reason },
        ]}
        onRefuse={onRefuse}
      />,
    );
    const snooze = within(host).getByRole("button", { name: "Snooze" });
    const disable = within(host).getByRole("button", { name: "Disable" });
    await expect(snooze).toHaveAttribute("aria-disabled", "true");
    await expect(snooze).not.toBeDisabled();
    await expect(host.querySelectorAll(".cv-toast__notice")).toHaveLength(1);
    await expect(snooze).toHaveAccessibleDescription(reason);
    await expect(snooze.getAttribute("aria-describedby")).toBe(
      disable.getAttribute("aria-describedby"),
    );
    await click(snooze);
    await expect(onClick).not.toHaveBeenCalled();
    await expect(onRefuse).toHaveBeenCalledWith(reason);
    await click(within(host).getByRole("button", { name: "Open chart" }));
    await expect(onClick).toHaveBeenCalledTimes(1);
  });

  it("a gated action keeps CMP-001's gated markup (classes, data attributes, the lock glyph)", async () => {
    const reason = "Your role can't change alerts.";
    const host = await mount(
      <>
        <Button size="sm" disabledReason={reason}>
          Snooze
        </Button>
        <Toast
          title="BTC above 65k"
          actions={[{ label: "Disable", onClick: vi.fn(), disabledReason: reason }]}
        />
      </>,
    );
    const button = within(host).getByRole("button", { name: "Snooze" });
    const gated = within(host).getByRole("button", { name: "Disable" });
    await expect(gated.className).toBe(button.className);
    for (const attr of ["data-variant", "data-size", "data-gated", "aria-disabled", "type"]) {
      await expect(gated.getAttribute(attr)).toBe(button.getAttribute(attr));
    }
    await expect(gated.querySelector(".cv-button__glyph svg")).not.toBeNull();
    await expect(button.querySelector(".cv-button__glyph svg")).not.toBeNull();
    await expect(gated.querySelector(".cv-button__label")).toHaveTextContent("Disable");
  });

  it("Undo calls back; once its window closes the outcome line replaces it", async () => {
    const onUndo = vi.fn();
    const undo = { onUndo, outcome: "EMA 21 removed." };
    const host = await mount(<Toast title="EMA 21 removed" undo={undo} />);
    await click(within(host).getByRole("button", { name: "Undo" }));
    await expect(onUndo).toHaveBeenCalledTimes(1);
    const closed = await mount(<Toast title="EMA 21 removed" undo={undo} undoClosed />);
    await expect(within(closed).queryByRole("button", { name: "Undo" })).toBeNull();
    await expect(closed).toHaveTextContent("EMA 21 removed.");
  });

  it("Esc on a focused toast dismisses it", async () => {
    const onDismiss = vi.fn();
    const action = { label: "Details", onClick: vi.fn() };
    const host = await mount(
      <Toast title="Order rejected" actions={[action]} onDismiss={onDismiss} />,
    );
    await focus(within(host).getByRole("button", { name: "Details" }));
    await press("Escape");
    await expect(onDismiss).toHaveBeenCalledWith("escape");
  });
});

describe("Toast Esc on the dismiss button", () => {
  it("hides the button's name echo first (the topmost layer), then dismisses", async () => {
    const onDismiss = vi.fn();
    const host = await mount(<Toast title="Session extended" onDismiss={onDismiss} />);
    await focus(within(host).getByRole("button", { name: "Dismiss Session extended" }));
    await press("Escape");
    await expect(onDismiss).not.toHaveBeenCalled();
    await press("Escape");
    await expect(onDismiss).toHaveBeenCalledTimes(1);
    await expect(onDismiss).toHaveBeenCalledWith("escape");
  });
});

/** A host that owns the queue: `add` pushes a toast, `remove` drops one unasked, `onDismiss` removes it. */
let add: (toast: ToastItem) => void = () => undefined;
let remove: (id: string) => void = () => undefined;
function Host({
  initial = [],
  announce,
  onDismiss,
  ...props
}: Partial<Omit<ToastRegionProps, "toasts">> & {
  readonly initial?: readonly ToastItem[];
  readonly announce: ToastAnnounce;
}): JSX.Element {
  const [toasts, setToasts] = useState<readonly ToastItem[]>(initial);
  add = (toast) => setToasts((list) => [...list, toast]);
  remove = (id) => setToasts((list) => list.filter((toast) => toast.id !== id));
  return (
    <>
      <label>
        Price
        <input type="text" />
      </label>
      <ToastRegion
        {...props}
        toasts={toasts}
        announce={announce}
        onDismiss={(id, reason) => {
          onDismiss?.(id, reason);
          setToasts((list) => list.filter((toast) => toast.id !== id));
        }}
      />
    </>
  );
}

const info: ToastItem = { id: "a", title: "Session extended", description: "Idle timer reset." };

describe("ToastRegion", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("Toast does not steal focus: focus stays in the typing field, the toast is announced politely", async () => {
    const announce = vi.fn<ToastAnnounce>();
    await mount(<Host announce={announce} />);
    const field = screen().getByRole("textbox", { name: "Price" });
    await focus(field);
    await act(async () => add(info));
    await expect(screen().getByRole("group", { name: "Session extended" })).toBeInTheDocument();
    await expect(document.activeElement).toBe(field);
    await expect(announce.mock.calls).toEqual([
      ["polite", "Session extended. Idle timer reset.", "a"],
    ]);
    await expect(screen().getByRole("region", { name: "Notifications" })).toBeInTheDocument();
  });

  it("speaks assertively only for danger or an error; politeness overrides; each toast once", async () => {
    const announce = vi.fn<ToastAnnounce>();
    await mount(<Host announce={announce} />);
    await act(async () => add({ id: "d", title: "Order rejected", tone: "danger" }));
    await act(async () => add({ id: "e", title: "Export failed", error: true }));
    await act(async () => add({ id: "w", title: "Feed stale", tone: "warning" }));
    await act(async () => add({ id: "p", title: "Rule fired", politeness: "assertive" }));
    await expect(announce.mock.calls).toEqual([
      ["assertive", "Order rejected", "d"],
      ["assertive", "Export failed", "e"],
      ["polite", "Feed stale", "w"],
      ["assertive", "Rule fired", "p"],
    ]);
  });

  it("a timed toast closes after the default 5 s, with no countdown bar", async () => {
    const onDismiss = vi.fn();
    await mount(<Host announce={vi.fn()} onDismiss={onDismiss} initial={[info]} />);
    await expect(document.querySelector('[role="progressbar"]')).toBeNull();
    await advance(4999);
    await expect(onDismiss).not.toHaveBeenCalled();
    await advance(1);
    await expect(onDismiss).toHaveBeenCalledWith("a", "timeout");
    await expect(screen().queryByRole("group")).toBeNull();
  });

  it("follows the host's duration; a toast's own duration wins; null is until dismissed", async () => {
    const onDismiss = vi.fn();
    await mount(
      <Host
        announce={vi.fn()}
        onDismiss={onDismiss}
        durationMs={10000}
        initial={[info, { id: "b", title: "Saved", durationMs: null }]}
      />,
    );
    await advance(9999);
    await expect(onDismiss).not.toHaveBeenCalled();
    await advance(1);
    await expect(onDismiss).toHaveBeenCalledTimes(1);
    await expect(onDismiss).toHaveBeenCalledWith("a", "timeout");
    await advance(60000);
    await expect(onDismiss).toHaveBeenCalledTimes(1);
  });

  it.each<[string, ToastItem]>([
    [
      "an action",
      { id: "x", title: "Alert fired", actions: [{ label: "Open chart", onClick: vi.fn() }] },
    ],
    ["a danger tone", { id: "x", title: "Order rejected", tone: "danger" }],
    ["an error", { id: "x", title: "Export failed", error: true }],
    ["persistent", { id: "x", title: "Pinned", persistent: true }],
  ])("runs no timer on a persistent toast: %s", async (_name, toast) => {
    const onDismiss = vi.fn();
    await mount(<Host announce={vi.fn()} onDismiss={onDismiss} initial={[toast]} />);
    await expect(vi.getTimerCount()).toBe(0);
    await advance(120000);
    await expect(onDismiss).not.toHaveBeenCalled();
  });

  it("pauses every timer while the pointer is over the stack and resumes with the time left", async () => {
    const onDismiss = vi.fn();
    await mount(<Host announce={vi.fn()} onDismiss={onDismiss} initial={[info]} />);
    await advance(3000);
    const list = screen().getByRole("list");
    await act(async () => {
      fireEvent.mouseOver(list);
    });
    await advance(30000);
    await expect(onDismiss).not.toHaveBeenCalled();
    await act(async () => {
      fireEvent.mouseOut(list, { relatedTarget: document.body });
    });
    await advance(1999);
    await expect(onDismiss).not.toHaveBeenCalled();
    await advance(1);
    await expect(onDismiss).toHaveBeenCalledWith("a", "timeout");
  });

  it("pauses while focus is in the stack and resumes when it leaves", async () => {
    const onDismiss = vi.fn();
    await mount(
      <Host announce={vi.fn()} onDismiss={onDismiss} initial={[info, { ...info, id: "b" }]} />,
    );
    const [first] = screen().getAllByRole("button", { name: "Dismiss Session extended" });
    await focus(first as HTMLElement);
    await advance(30000);
    await expect(onDismiss).not.toHaveBeenCalled();
    await focus(screen().getByRole("textbox", { name: "Price" }));
    await advance(5000);
    await expect(onDismiss).toHaveBeenCalledTimes(2);
  });

  it("pauses while a modal layer is open and resumes when it closes", async () => {
    const onDismiss = vi.fn();
    let setOpen: (open: boolean) => void = () => undefined;
    function WithDialog(): JSX.Element {
      const [open, set] = useState(false);
      setOpen = set;
      return <Dialog open={open} title="Rename layout" onOpenChange={set} />;
    }
    await mount(
      <>
        <Host announce={vi.fn()} onDismiss={onDismiss} initial={[info]} />
        <WithDialog />
      </>,
    );
    await advance(1000);
    await act(async () => setOpen(true));
    // Visible but inert: the dialog's inert-outside pass covers the region, a child of `body` (jsdom has no
    // `inert`, so the pass falls back to `aria-hidden`; the RegionUnderModal story asserts `inert` itself).
    const region = document.querySelector(".cv-toast-region");
    await expect(region?.closest('[inert], [aria-hidden="true"]')).not.toBeNull();
    await advance(60000);
    await expect(onDismiss).not.toHaveBeenCalled();
    await act(async () => setOpen(false));
    await advance(4000);
    await expect(onDismiss).toHaveBeenCalledWith("a", "timeout");
  });

  it("Esc on a focused toast dismisses it and moves focus to the next, then back to the field", async () => {
    const announce = vi.fn<ToastAnnounce>();
    const onDismiss = vi.fn();
    const action = { label: "Details", onClick: vi.fn() };
    await mount(
      <Host
        announce={announce}
        onDismiss={onDismiss}
        initial={[
          { id: "a", title: "First", actions: [action] },
          { id: "b", title: "Second", actions: [action] },
        ]}
      />,
    );
    const field = screen().getByRole("textbox", { name: "Price" });
    await focus(field);
    const [details] = screen().getAllByRole("button", { name: "Details" });
    await focus(details as HTMLElement);
    await press("Escape");
    await expect(onDismiss).toHaveBeenCalledWith("a", "escape");
    const second = screen().getByRole("group", { name: "Second" });
    await expect(within(second).getByRole("button", { name: "Details" })).toHaveFocus();
    await press("Escape");
    await expect(onDismiss).toHaveBeenCalledWith("b", "escape");
    await expect(field).toHaveFocus();
    await expect(screen().queryByRole("region", { name: "Notifications" })).toBeNull();
  });

  it("a timer fires once even if the host keeps the toast after the timeout", async () => {
    const onDismiss = vi.fn();
    await mount(<ToastRegion toasts={[info]} announce={vi.fn()} onDismiss={onDismiss} />);
    await advance(5000);
    await expect(onDismiss).toHaveBeenCalledTimes(1);
    const list = screen().getByRole("list");
    await act(async () => {
      fireEvent.mouseOver(list);
    });
    await act(async () => {
      fireEvent.mouseOut(list, { relatedTarget: document.body });
    });
    await focus(screen().getByRole("button", { name: "Dismiss Session extended" }));
    await focus(document.body);
    await advance(60000);
    await expect(onDismiss).toHaveBeenCalledTimes(1);
  });

  it("after unmount no timer fires and the group's Esc listener is gone", async () => {
    const onDismiss = vi.fn();
    let setShown: (shown: boolean) => void = () => undefined;
    function Toggle(): JSX.Element | null {
      const [shown, set] = useState(true);
      setShown = set;
      return shown ? (
        <ToastRegion toasts={[info]} announce={vi.fn()} onDismiss={onDismiss} />
      ) : null;
    }
    await mount(<Toggle />);
    const group = screen().getByRole("group", { name: "Session extended" });
    await act(async () => setShown(false));
    await advance(60000);
    group.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    await expect(onDismiss).not.toHaveBeenCalled();
    await expect(vi.getTimerCount()).toBe(0);
  });

  it("a focused toast the host removes by itself gives focus back where it came from", async () => {
    const action = { label: "Details", onClick: vi.fn() };
    await mount(
      <Host announce={vi.fn()} initial={[{ id: "a", title: "First", actions: [action] }]} />,
    );
    const field = screen().getByRole("textbox", { name: "Price" });
    await focus(field);
    await focus(screen().getByRole("button", { name: "Details" }));
    await act(async () => remove("a"));
    await expect(screen().queryByRole("group", { name: "First" })).toBeNull();
    await expect(field).toHaveFocus();
  });

  it("the dismiss button hands focus on too", async () => {
    await mount(<Host announce={vi.fn()} initial={[info, { ...info, id: "b", title: "Saved" }]} />);
    const dismiss = screen().getByRole("button", { name: "Dismiss Session extended" });
    await focus(dismiss);
    await click(dismiss);
    await expect(screen().queryByRole("group", { name: "Session extended" })).toBeNull();
    await expect(screen().getByRole("button", { name: "Dismiss Saved" })).toHaveFocus();
  });

  it("an Undo window follows the duration, then the outcome line stays and is spoken once", async () => {
    const announce = vi.fn<ToastAnnounce>();
    const onDismiss = vi.fn();
    const onUndo = vi.fn();
    await mount(
      <Host
        announce={announce}
        onDismiss={onDismiss}
        initial={[
          { id: "u", title: "EMA 21 removed", undo: { onUndo, outcome: "EMA 21 removed." } },
        ]}
      />,
    );
    await expect(screen().getByRole("button", { name: "Undo" })).toBeInTheDocument();
    await advance(5000);
    await expect(screen().queryByRole("button", { name: "Undo" })).toBeNull();
    await expect(screen().getByRole("group", { name: "EMA 21 removed" })).toHaveTextContent(
      "EMA 21 removed.",
    );
    await expect(announce).toHaveBeenLastCalledWith("polite", "EMA 21 removed.", "u:outcome");
    await advance(120000);
    await expect(onDismiss).not.toHaveBeenCalled();
  });

  it("a press on a gated action speaks its reason politely, once per press", async () => {
    const announce = vi.fn<ToastAnnounce>();
    const reason = "Your role can't change alerts.";
    await mount(
      <Host
        announce={announce}
        initial={[
          {
            id: "g",
            title: "BTC above 65k",
            actions: [{ label: "Snooze", onClick: vi.fn(), disabledReason: reason }],
          },
        ]}
      />,
    );
    const snooze = screen().getByRole("button", { name: "Snooze" });
    await click(snooze);
    await click(snooze);
    await expect(announce.mock.calls.slice(1)).toEqual([
      ["polite", reason, "g:refuse:1"],
      ["polite", reason, "g:refuse:2"],
    ]);
  });
});
