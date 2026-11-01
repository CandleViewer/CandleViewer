import { act, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Chart } from "../../../src/chart";
import { clearAnnouncements, ShellAnnouncer } from "../../../src/features/app-shell/announcer";
import {
  ANNOUNCE_EVENT,
  ChartAnnounceRoute,
} from "../../../src/features/chart-announce/ChartAnnounceRoute";

vi.mock("@candleviewer/chart-engine", () => ({
  createChart: (): unknown => ({
    subscribe: () => () => undefined,
    dispose: () => undefined,
    setTheme: () => undefined,
    setDensity: () => undefined,
  }),
}));

const theme = { palette: "default", convention: "standard", colors: {} } as const;
const polite = (): HTMLElement => document.querySelector<HTMLElement>('[aria-live="polite"]')!; // ShellAnnouncer is rendered

function mount() {
  return render(
    <>
      <ShellAnnouncer />
      <Chart options={{ theme }} label="Price chart">
        <ChartAnnounceRoute />
      </Chart>
    </>,
  );
}
const send = (detail: unknown): void => {
  const figure = screen.getByRole("figure", { name: "Price chart" });
  act(() => void figure.dispatchEvent(new CustomEvent(ANNOUNCE_EVENT, { bubbles: true, detail })));
};

afterEach(() => clearAnnouncements());

describe("candleviewer:announce routing (E11-S07, BQ-21)", () => {
  it("writes the engine's message into the shell's polite region, latest state per key", () => {
    mount();
    send({ politeness: "polite", text: "14 Oct 13:42, close 64,011.0", key: "chart:cursor" });
    expect(polite()).toHaveTextContent("14 Oct 13:42, close 64,011.0");
    send({ politeness: "polite", text: "14 Oct 13:43, close 64,020.0", key: "chart:cursor" });
    expect(polite()).toHaveTextContent("14 Oct 13:43, close 64,020.0");
    expect(polite().querySelectorAll("p")).toHaveLength(1);
  });

  it("ignores malformed details", () => {
    mount();
    send({ politeness: "loud", text: "x", key: "k" });
    send(null);
    send({ politeness: "polite", text: "", key: "k" });
    expect(polite()).toBeEmptyDOMElement();
  });

  it("removes its listener on unmount", () => {
    const view = mount();
    const figure = screen.getByRole("figure", { name: "Price chart" });
    const remove = vi.spyOn(figure, "removeEventListener");
    view.unmount();
    expect(remove).toHaveBeenCalledWith(ANNOUNCE_EVENT, expect.any(Function));
  });
});
