import { act, fireEvent, render, screen } from "@testing-library/react";
import { createMemoryRouter } from "react-router";
import { RouterProvider } from "react-router/dom";
import { Button } from "@candleviewer/ui";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { ShellLayout } from "../../../src/features/app-shell/ShellLayout";
import { resetMeClaims, setMeClaims } from "../../../src/lib/auth/meCache";

beforeEach(() => {
  resetMeClaims();
  setMeClaims({ authenticated: true, role: "owner", permissions: [] });
});
afterEach(() => resetMeClaims());

describe("G-T2.3: the shell owns the gated announcement", () => {
  it("a gated press inside the shell writes nothing to the ui package's own region", async () => {
    const router = createMemoryRouter(
      [
        {
          element: <ShellLayout />,
          children: [
            {
              path: "/",
              element: <Button disabledReason="Only the owner can do this.">Gated</Button>,
            },
          ],
        },
      ],
      { initialEntries: ["/"] },
    );
    render(<RouterProvider router={router} />);
    const button = await screen.findByRole("button", { name: /Gated/ });
    fireEvent.click(button);
    await act(async () => {
      await Promise.resolve();
    });
    expect(document.getElementById("cv-theme-live-region")?.textContent ?? "").toBe("");
  });
});
