/**
 * E42-S04 (#1135): the integrity incident's banner (E42-D04 §7, D11). Its message is `role="alert"`
 * on the episode's first mount only and static after; it offers [Copy details], the "What to do
 * now" disclosure (which only toggles `aria-expanded`) and two links, and never a Retry, a re-run,
 * a dismiss or an acknowledge. The halt sentence takes the safety line's place while the served
 * incident is open (the orchestrator's BQ-5).
 */
import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AUDIT_COPY as COPY } from "../../../../src/features/admin/audit/copy";
import { ShellAnnouncer, clearAnnouncements } from "../../../../src/features/app-shell/announcer";
import type { BannerModel } from "../../../../src/features/admin/audit/integrity";
import { TamperBanner } from "../../../../src/features/admin/audit/TamperBanner";

const MODEL: BannerModel = {
  voice: "break:1204118",
  entryId: 1_204_118,
  title: "Tamper check FAILED at entry 1,204,118 — treat this as a security incident",
  facts: "Found at 14:05:07 UTC on 2026-10-22 in a check of entries 204,119–1,204,118.",
  meaning: COPY.tamper.failed.meaning,
  safe: COPY.tamper.failed.safe,
  halted: false,
  recheck: COPY.tamper.failed.recheck,
  steps: COPY.tamper.failed.steps,
  details: "first_bad_id: 1204118",
};

const mount = (speak: boolean, model: BannerModel = MODEL) => {
  const onSpoken = vi.fn();
  const view = render(
    <MemoryRouter>
      <TamperBanner model={model} speak={speak} onSpoken={onSpoken} />
    </MemoryRouter>,
  );
  return { onSpoken, view };
};

afterEach(() => clearAnnouncements());

describe("the incident banner (§7)", () => {
  it("test_banner_first_mount_is_an_alert_and_spends_the_episodes_voice", () => {
    const { onSpoken } = mount(true);
    expect(screen.getByRole("alert")).toHaveTextContent(MODEL.title);
    expect(onSpoken.mock.calls).toEqual([["break:1204118"]]);
  });

  it("test_banner_first_mount_under_a_modal_speaks_through_the_shell_and_stays_static", () => {
    // A-1135P2-10: a modal makes the page inert, so its alert is never heard; the shell's
    // assertive region stays live under a modal, and the episode's one voice is said there
    const onSpoken = vi.fn();
    render(<ShellAnnouncer />);
    const page = document.body.appendChild(document.createElement("div"));
    page.setAttribute("inert", "");
    render(
      <MemoryRouter>
        <TamperBanner model={MODEL} speak onSpoken={onSpoken} />
      </MemoryRouter>,
      { container: page },
    );
    expect(page.querySelector("[role='alert']")).toBeNull();
    const assertive = document.querySelector("[aria-live='assertive']");
    expect(assertive).toHaveTextContent(MODEL.title);
    expect(assertive).toHaveTextContent(COPY.tamper.failed.recheck);
    expect(onSpoken.mock.calls).toEqual([["break:1204118"]]);
    page.remove();
  });

  it("test_banner_later_mount_is_static_and_says_nothing", () => {
    const { onSpoken } = mount(false);
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.getByText(MODEL.title)).toBeInTheDocument();
    expect(onSpoken).not.toHaveBeenCalled();
  });

  it("test_banner_offers_copy_the_steps_disclosure_and_two_links_never_a_retry_or_dismiss", () => {
    mount(false);
    const buttons = screen
      .getAllByRole("button")
      .map((b) => b.getAttribute("aria-label") ?? b.textContent);
    expect(buttons).toEqual(["Copy details", "What to do now"]);
    const steps = screen.getByRole("button", { name: "What to do now" });
    expect(steps).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByText(COPY.tamper.failed.steps)).not.toBeVisible();
    fireEvent.click(steps);
    expect(steps).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText(COPY.tamper.failed.steps)).toBeVisible();
    expect(screen.queryByRole("alert")).toBeNull(); // the disclosure says nothing (D11)
    const links = screen.getAllByRole("link").map((a) => [a.textContent, a.getAttribute("href")]);
    expect(links).toEqual([
      ["Incident log", "/admin/health"],
      ["Security centre", "/admin/security"],
    ]);
  });

  it("test_banner_halt_sentence_replaces_the_safety_line_while_the_incident_is_open", () => {
    const { view } = mount(false, { ...MODEL, safe: COPY.tamper.failed.halted, halted: true });
    const banner = view.container.querySelector<HTMLElement>("[data-tamper-banner]");
    expect(within(banner as HTMLElement).getByText(COPY.tamper.failed.halted)).toBeVisible();
    expect(within(banner as HTMLElement).queryByText(COPY.tamper.failed.safe)).toBeNull();
  });
});
