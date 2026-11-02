import { act, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { WsErrorHost } from "../../src/lib/ws/WsErrorHost";
import { handleWsError } from "../../src/lib/ws/errorHandler";

const feed = (code: string) => act(() => void handleWsError({ t: "err", p: { code } }));

describe("WsErrorHost", () => {
  it("fatal code opens a blocking modal", () => {
    render(<WsErrorHost />);
    feed("auth_failed");
    expect(screen.getByRole("alertdialog")).toBeTruthy();
  });
  it("transient code shows a badge, not a modal", () => {
    render(<WsErrorHost />);
    feed("degraded_data");
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(screen.getByRole("status").textContent).toContain("stale");
  });
  it("client bug code shows report-a-bug toast", () => {
    render(<WsErrorHost />);
    feed("frame_malformed");
    expect(screen.getByRole("status").textContent).toContain("report a bug");
  });
  it("forbidden keeps its 10.3 copy (sign in again or contact an owner) inside the modal", () => {
    render(<WsErrorHost />);
    feed("forbidden");
    expect(screen.getByRole("alertdialog")).toHaveAccessibleDescription(
      "Session error (forbidden). Sign in again or contact an owner.",
    );
  });
});
