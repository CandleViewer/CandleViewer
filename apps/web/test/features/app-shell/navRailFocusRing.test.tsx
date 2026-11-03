// E10-Q03 (#302) F-4: driver B measured every rail link on the browser's default 1 px `auto` focus ring (1.1:1 on
// the dark surfaces), not the CMP-039 ring (2 px, `color.focus.ring`). The rail frame clips what it overflows, so
// the ring is the inset variant (SC 2.4.7 / 2.4.11 / 2.4.13).
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { beforeEach, describe, expect, it } from "vitest";
import { NavRail } from "../../../src/features/app-shell/NavRail";
import { resetMeClaims, setMeClaims } from "../../../src/lib/auth/meCache";

beforeEach(() => {
  resetMeClaims();
  setMeClaims({ authenticated: true, role: "owner", permissions: [] });
});

describe("E10-Q03 F-4: every rail link carries the CMP-039 focus ring", () => {
  it.each([false, true])("collapsed=%s: each link has the inset ring class", (collapsed) => {
    render(
      <MemoryRouter initialEntries={["/journal"]}>
        <NavRail collapsed={collapsed} />
      </MemoryRouter>,
    );
    const links = screen.getAllByRole("link");
    expect(links.length).toBeGreaterThan(0);
    for (const link of links) expect(link).toHaveClass("cv-focus-ring", "cv-focus-ring--inset");
  });
});
