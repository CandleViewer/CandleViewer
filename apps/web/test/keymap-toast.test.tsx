import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ToastHost } from "../src/keymap/KeymapHost";
import { ShellAnnouncer, clearAnnouncements } from "../src/features/app-shell/announcer";

/** SCR-015 toasts and WCAG 2.2.1 (#5197): the user, not a 5 s timer, ends a toast. */
const item = { id: "t-1", title: "Cancel all is not available here", tone: "info" as const };

function mount(durationMs?: number | null) {
  const onDismiss = vi.fn();
  const props = durationMs === undefined ? {} : { durationMs };
  render(
    <>
      <ShellAnnouncer />
      <ToastHost toasts={[item]} onDismiss={onDismiss} {...props} />
    </>,
  );
  return onDismiss;
}
const region = (): HTMLElement => screen.getByRole("region", { name: "Notifications" });
const advance = (ms: number): void => void act(() => void vi.advanceTimersByTime(ms));

describe("SCR-015 toast host", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => {
    clearAnnouncements();
    vi.useRealTimers();
  });

  it("by default stays past 5 s and leaves only on its dismiss control", () => {
    const onDismiss = mount();
    advance(60_000);
    expect(onDismiss).not.toHaveBeenCalled();
    fireEvent.click(within(region()).getByRole("button", { name: /Dismiss/ }));
    expect(onDismiss).toHaveBeenCalledWith("t-1");
  });

  it("with a finite duration, hover pauses it and leave resumes the remaining time", () => {
    const onDismiss = mount(5000);
    const list = within(region()).getByRole("list");
    advance(3000);
    fireEvent.mouseEnter(list);
    advance(60_000);
    expect(onDismiss).not.toHaveBeenCalled();
    fireEvent.mouseLeave(list);
    advance(1900);
    expect(onDismiss).not.toHaveBeenCalled();
    advance(200);
    expect(onDismiss).toHaveBeenCalledWith("t-1");
  });

  it("with a finite duration, focus inside pauses it and blur resumes", () => {
    const onDismiss = mount(5000);
    const button = within(region()).getByRole("button", { name: /Dismiss/ });
    act(() => button.focus());
    advance(60_000);
    expect(onDismiss).not.toHaveBeenCalled();
    act(() => button.blur());
    advance(5100);
    expect(onDismiss).toHaveBeenCalledWith("t-1");
  });

  it("speaks the sentence once, in the shell's polite region and not in the stack", () => {
    mount();
    const polite = document.querySelector('[aria-live="polite"]');
    expect(polite?.textContent).toBe(item.title);
    advance(10_000);
    expect(polite?.textContent).toBe(item.title);
    expect(region().querySelector("[aria-live]")).toBeNull();
    expect(document.querySelectorAll('[aria-live="polite"] > *')).toHaveLength(1);
  });
});
