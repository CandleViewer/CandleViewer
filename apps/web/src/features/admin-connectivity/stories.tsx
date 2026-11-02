import { useState, type JSX } from "react";
import { COPY } from "./copy";
import {
  BudgetGrid,
  ChangeBudgetDialog,
  ConnectivityActions,
  NotServedBlock,
  RateMeter,
  ReconnectDialog,
  ReserveRow,
  StateTile,
  UsageHistory,
} from "./components";
import { AuditMarker } from "./AuditMarker";
import { AS_OF, SERVED_REPORT, USAGE_SERIES } from "./fixtures";
import { rateBudgetRows } from "./rateBudget";
import { fill } from "./text";

/**
 * The hand-off §D story lists (E08-D09-handoff §D), one entry per story name, each rendered in dark, light and high
 * contrast by `STORY_THEMES` (E08-S12 BQ-12). `apps/web` has no Storybook (the ui package's globs stop at its own
 * `src`), so the stories are plain render functions run by the Vitest story test; PR 2 lifts them into the
 * Storybook host once it can see this folder. A matrix may supplement them and never replaces them.
 */
export const STORY_THEMES = ["dark", "light", "high-contrast"] as const;
export type StoryTheme = (typeof STORY_THEMES)[number];

export interface StoryDef {
  /** The catalogue component the story belongs to (`15`). */
  readonly cmp: "CMP-178" | "CMP-023" | "CMP-049" | "CMP-044" | "CMP-079" | "CMP-024" | "CMP-093";
  readonly name: string;
  readonly render: () => JSX.Element;
}

const ROWS = rateBudgetRows(SERVED_REPORT);
function first<T>(xs: readonly T[]): T {
  const x = xs[0];
  if (x === undefined) throw new Error("story fixture has no rows");
  return x;
}
const MAIN = first(ROWS);
const NO_FIGURES = ROWS.map((r) => ({
  ...r,
  limitPerMinute: null,
  peakUsedPerMinute: null,
  utilisationPct: null,
}));
const noop = (): void => undefined;

function Illustrative({ children }: { readonly children: JSX.Element }): JSX.Element {
  return (
    <div>
      {children}
      <p>{COPY["W-01"]}</p>
    </div>
  );
}

function Dialog({
  render,
}: {
  readonly render: (open: boolean, close: () => void) => JSX.Element;
}): JSX.Element {
  const [open, setOpen] = useState(true);
  return render(open, () => setOpen(false));
}

function Tile(props: {
  readonly id: Parameters<typeof StateTile>[0]["id"];
  readonly label: string;
  readonly slots?: Readonly<Record<string, string>>;
}): JSX.Element {
  return (
    <Illustrative>
      <StateTile id={props.id} label={props.label} slots={props.slots ?? {}} asOf={AS_OF} />
    </Illustrative>
  );
}

const trend = fill(COPY["W-72"], { order: "All", Main: "Main", "12": 12, "41": 41 }) ?? "";

export const STORIES: readonly StoryDef[] = [
  {
    cmp: "CMP-178",
    name: "RateHeld",
    render: () => (
      <Tile id="S-04" label="IP hold" slots={{ "14:42:05": "14:42:05", "8m 20s": "8m 20s" }} />
    ),
  },
  { cmp: "CMP-178", name: "RateBanned", render: () => <Tile id="S-05" label="IP hold" /> },
  { cmp: "CMP-178", name: "ClockHalted", render: () => <Tile id="S-10" label="Clock" /> },
  { cmp: "CMP-178", name: "NotMeasured", render: () => <Tile id="S-12" label="Clock" /> },
  {
    cmp: "CMP-023",
    name: "MeterStepped",
    render: () => (
      <Illustrative>
        <RateMeter row={MAIN} />
      </Illustrative>
    ),
  },
  {
    cmp: "CMP-023",
    name: "MeterNotConnected",
    render: () => <RateMeter row={first(NO_FIGURES)} />,
  },
  { cmp: "CMP-049", name: "BudgetGrid", render: () => <BudgetGrid rows={NO_FIGURES} /> },
  {
    cmp: "CMP-049",
    name: "BudgetGridPerMinute",
    render: () => (
      <Illustrative>
        <BudgetGrid rows={ROWS} />
      </Illustrative>
    ),
  },
  {
    cmp: "CMP-049",
    name: "SimulatorResult",
    render: () => <NotServedBlock title="Fan-out simulator" />,
  },
  {
    cmp: "CMP-049",
    name: "HistoryTable",
    render: () => (
      <Illustrative>
        <UsageHistory points={USAGE_SERIES} trend={trend} />
      </Illustrative>
    ),
  },
  {
    cmp: "CMP-044",
    name: "ReconnectMarketData",
    render: () => (
      <Dialog
        render={(open, close) => (
          <ReconnectDialog
            open={open}
            onConfirm={close}
            onCancel={close}
            connections={3}
            topics={120}
          />
        )}
      />
    ),
  },
  {
    cmp: "CMP-044",
    name: "ChangeBudget",
    render: () => (
      <Dialog
        render={(open, close) => (
          <ChangeBudgetDialog
            open={open}
            onConfirm={close}
            onCancel={close}
            account="Main"
            range={{ min: 60, max: 420 }}
          />
        )}
      />
    ),
  },
  {
    cmp: "CMP-044",
    name: "ChangeBudgetRefused",
    render: () => (
      <Dialog
        render={(open, close) => (
          <ChangeBudgetDialog
            open={open}
            onConfirm={close}
            onCancel={close}
            account="Main"
            range={{ min: 60, max: 420 }}
            refusal={fill(COPY["W-61"], { "60": 60, "420": 420 }) ?? ""}
          />
        )}
      />
    ),
  },
  {
    cmp: "CMP-079",
    name: "HoldReason",
    render: () => (
      <ConnectivityActions gate={{ kind: "hold" }} onReconnect={noop} onChangeBudget={noop} />
    ),
  },
  {
    cmp: "CMP-079",
    name: "ConnectionBudgetWait",
    render: () => (
      <ConnectivityActions
        gate={{ kind: "wait", seconds: 40 }}
        onReconnect={noop}
        onChangeBudget={noop}
      />
    ),
  },
  {
    cmp: "CMP-079",
    name: "ViewAs",
    render: () => (
      <ConnectivityActions
        gate={{ kind: "view_as", user: "Alex" }}
        onReconnect={noop}
        onChangeBudget={noop}
      />
    ),
  },
  {
    cmp: "CMP-024",
    name: "UsageHistory",
    render: () => (
      <Illustrative>
        <UsageHistory points={USAGE_SERIES} trend={trend} />
      </Illustrative>
    ),
  },
  {
    cmp: "CMP-024",
    name: "UsageHistoryEmpty",
    render: () => <UsageHistory points={[]} trend="" />,
  },
  {
    cmp: "CMP-093",
    name: "MarkerPendingRegistration",
    render: () => <AuditMarker action="reconnect" />,
  },
  { cmp: "CMP-178", name: "ReserveNotConnected", render: () => <ReserveRow /> },
];
