/**
 * E16-S01: SCR-140's one voice for a press (E16-D02 §10.5; E16-D06 R-5, SR-14): a T2 reason, a refusal or a grid
 * line is said once, politely, by the shell announcer (never a region of the page's own), and the same sentence
 * pressed twice is said twice.
 */
import { act, render } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import { ShellAnnouncer, clearAnnouncements } from "../../../src/features/app-shell/announcer";
import { sayPolitely } from "../../../src/features/recorder/pageAnnouncer";

afterEach(() => act(() => clearAnnouncements()));

it("test_say_politely_writes_the_shell_announcers_polite_region_once_per_press", () => {
  const { container } = render(<ShellAnnouncer />);
  const polite = container.querySelector('[aria-live="polite"]') as HTMLElement;
  const assertive = container.querySelector('[aria-live="assertive"]') as HTMLElement;
  const reason = "Recording stops 30 min after the last chart closes.";
  act(() => sayPolitely(reason));
  const first = polite.querySelector("p")?.dataset["seq"];
  expect(polite).toHaveTextContent(reason);
  act(() => sayPolitely(reason));
  expect(polite.querySelector("p")?.dataset["seq"]).not.toBe(first);
  expect(polite).toHaveTextContent(reason);
  act(() => sayPolitely("   "));
  expect(polite).toHaveTextContent(reason);
  expect(assertive).toBeEmptyDOMElement();
});
