// E11-Q02 (#444) engine E2E harness: its own Vite entry and build (vite.config.ts), outside `src/`, so the
// production build never holds it. Public engine surface only (BQ-03); frames arrive over a
// same-origin WebSocket that the spec fakes with `routeWebSocket`.
import { useEffect, useLayoutEffect, useRef, type JSX } from "react";
import { createRoot } from "react-dom/client";
import type { ChartEvents, ChartOptions } from "@candleviewer/chart-engine";
import { Chart, Pane, useChartApi } from "../../src/chart";
import { decodeBarsFrame, type BarsHeader } from "./barsFrame";
import { RECORDED, record, type EngineEventLog } from "./events";

const THEME: ChartOptions["theme"] = {
  palette: "default",
  convention: "standard",
  colors: {
    "color.chart.background": "#0b0e11",
    "color.candle.up": "#26a69a",
    "color.candle.down": "#ef5350",
  },
};

/** Records the engine's public events and feeds the pane's candles from the faked socket. */
function Feed({
  fixture,
  events,
}: {
  fixture: string;
  events: EngineEventLog;
}): JSX.Element | null {
  const chart = useChartApi();
  useEffect(() => {
    const pane = chart?.panes[0];
    if (chart === null || pane === undefined) return undefined;
    const offs = RECORDED.map((type) =>
      chart.subscribe(type, (payload: ChartEvents[typeof type]) => record(events, type, payload)),
    );
    const series = pane.addSeries("candles", {
      upColorToken: "color.candle.up",
      downColorToken: "color.candle.down",
    });
    const scheme = window.location.protocol === "https:" ? "wss:" : "ws:";
    const socket = new WebSocket(`${scheme}//${window.location.host}/__engine-feed`);
    socket.binaryType = "arraybuffer";
    let header: BarsHeader | null = null;
    socket.addEventListener("open", () => socket.send(JSON.stringify({ fixture })));
    socket.addEventListener("message", (m: MessageEvent<string | ArrayBuffer>) => {
      if (typeof m.data === "string") {
        header = JSON.parse(m.data) as BarsHeader;
        return;
      }
      if (header === null) return;
      const data = decodeBarsFrame(header, m.data);
      series.setData(data);
      chart.timeScale.setVisibleRange({
        from: data.time[Math.max(0, header.count - header.initialVisible)] ?? 0,
        to: (data.time[header.count - 1] ?? 0) + header.barDurationUs,
      });
      record(events, "fixtureLoaded", { fixture: header.fixture, count: header.count });
    });
    return () => {
      socket.close();
      series.remove();
      for (const off of offs) off();
    };
  }, [chart, fixture, events]);
  return null;
}

/** The sized box the chart fills (a layout effect: it has a size before the chart is created). */
function Harness(props: {
  fixture: string;
  runMode: "worker" | "inline";
  events: EngineEventLog;
}): JSX.Element {
  const box = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const figure = box.current?.firstElementChild;
    if (figure instanceof HTMLElement) figure.style.cssText += ";width:100%;height:100%";
  }, []);
  return (
    <div ref={box} data-testid="engine-harness-chart" style={{ width: 900, height: 520 }}>
      <Chart options={{ theme: THEME, runMode: props.runMode }} label="Engine harness chart">
        <Pane>
          <Feed fixture={props.fixture} events={props.events} />
        </Pane>
      </Chart>
    </div>
  );
}

const params = new URLSearchParams(window.location.search);
const events: EngineEventLog = { log: [], seq: 0 };
window.__engineEvents = events;
const root = document.getElementById("root");
if (root === null) throw new Error("engine harness: #root is missing");
createRoot(root).render(
  <Harness
    fixture={params.get("fixture") ?? "btcusdt-1m-100k"}
    runMode={params.get("runMode") === "inline" ? "inline" : "worker"}
    events={events}
  />,
);
