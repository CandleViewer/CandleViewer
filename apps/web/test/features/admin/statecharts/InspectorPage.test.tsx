/**
 * E42-S08 (#1137) §5.1: the statechart inspector's page for R-357 `/admin/statecharts` (BQ-1 as
 * ruled), its frame: CMP-088's `h1` "Statechart inspector" and its "All times UTC" line, and its
 * screen id as one PROPOSED placeholder, never one of the two slots `14` holds for security
 * screens. No route mounts the page yet: R-357 comes with this ticket's last part.
 */
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  INSPECTOR_SCREEN,
  InspectorPage,
} from "../../../../src/features/admin/statecharts/InspectorPage";
import { inspector } from "../../../../src/features/admin/statecharts/inspectorStore";

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(() => new Promise<Response>(() => undefined)), // no answer: the frame alone
  );
});

afterEach(() => {
  inspector.reset();
  vi.unstubAllGlobals();
});

describe("the page frame (BQ-1)", () => {
  it("test_page_frame_has_the_one_h1_and_the_utc_line", () => {
    render(
      <MemoryRouter initialEntries={["/admin/statecharts"]}>
        <InspectorPage />
      </MemoryRouter>,
    );
    const h1 = screen.getByRole("heading", { level: 1 });
    expect(h1).toHaveAccessibleName("Statechart inspector");
    expect(document.querySelectorAll('[data-cmp="CMP-088"]')).toHaveLength(1);
    expect(screen.getByText("All times UTC")).toBeInTheDocument();
  });

  it("test_page_screen_id_is_one_proposed_placeholder_never_a_held_slot", () => {
    render(
      <MemoryRouter initialEntries={["/admin/statecharts"]}>
        <InspectorPage />
      </MemoryRouter>,
    );
    expect(INSPECTOR_SCREEN).toBe("SCR-PROPOSED");
    expect(document.querySelector(`[data-scr="${INSPECTOR_SCREEN}"]`)).not.toBeNull();
    expect(INSPECTOR_SCREEN).not.toMatch(/SCR-13[89]/);
  });
});
