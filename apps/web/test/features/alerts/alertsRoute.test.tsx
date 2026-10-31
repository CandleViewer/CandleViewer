/** The route wrapper and the default CSV download (E40-S01). */
import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { downloadCsv } from "../../../src/features/alerts/AlertHistoryDialog";
import { AlertsRoute } from "../../../src/features/alerts/AlertsRoute";
import { resetMeClaims, setMeClaims } from "../../../src/lib/auth/meCache";

afterEach(() => {
  resetMeClaims();
  vi.restoreAllMocks();
});

describe("AlertsRoute", () => {
  it("renders the screen under the page heading, refusing a session without alerts:read", () => {
    setMeClaims({ authenticated: true, role: "viewer", permissions: [] });
    render(
      <MemoryRouter>
        <AlertsRoute />
      </MemoryRouter>,
    );
    expect(screen.queryByRole("grid")).toBeNull();
    expect(screen.getByRole("main")).toBeVisible();
  });
});

describe("downloadCsv", () => {
  it("hands the text to a temporary object URL and revokes it", () => {
    const create = vi.fn(() => "blob:x");
    const revoke = vi.fn();
    Object.assign(URL, { createObjectURL: create, revokeObjectURL: revoke });
    const click = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => undefined);
    downloadCsv("a.csv", "x");
    expect(create).toHaveBeenCalledTimes(1);
    expect(click).toHaveBeenCalledTimes(1);
    expect(revoke).toHaveBeenCalledWith("blob:x");
  });
});
