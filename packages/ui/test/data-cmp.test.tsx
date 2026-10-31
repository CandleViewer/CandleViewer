// @vitest-environment jsdom
import type { JSX } from "react";
import { describe, expect, it } from "vitest";
import {
  AdminLayout,
  AuditRow,
  AuditRowList,
  Button,
  Card,
  Checkbox,
  CommandPalette,
  ConfirmDialog,
  DatePicker,
  DateRangePicker,
  Dialog,
  Drawer,
  FilterBar,
  FormField,
  FormSection,
  IconButton,
  InfoPanel,
  Menu,
  NumericStepperInput,
  PageHeader,
  RadioGroup,
  SearchBox,
  SegmentedControl,
  Select,
  Slider,
  SystemHealthTile,
  Table,
  Tabs,
  TextInput,
  Toast,
  Toggle,
} from "../src/index.js";
import {
  ColumnPicker,
  FileDrop,
  FreshnessMarker,
  WatchlistGroupTabs,
  WatchlistRow,
  watchlistColumns,
} from "../src/index.js";
import type { AuditRowProps, SegmentedOptions, WatchlistRowData } from "../src/index.js";
import { mount } from "./theme/mount.js";

const options = [
  { value: "a", label: "Alpha" },
  { value: "b", label: "Bravo" },
];
const segments: SegmentedOptions = [
  { value: "a", label: "Alpha" },
  { value: "b", label: "Bravo" },
];
const noop = (): void => undefined;
const auditEntry: AuditRowProps["entry"] = {
  id: 1,
  ts: "2026-10-22T14:02:11Z",
  action: "admin.area_entered",
  actor_user_id: null,
  subject_type: null,
  subject_id: null,
  outcome: "success",
  severity: "info",
  detail: {},
  entry_hash: null,
  prev_hash: null,
};

const atoms: [string, () => JSX.Element][] = [
  ["CMP-001", () => <Button>Save</Button>],
  ["CMP-002", () => <IconButton icon="lock" label="Settings" />],
  [
    "CMP-003",
    () => <SegmentedControl aria-label="View" options={segments} value="a" onChange={noop} />,
  ],
  ["CMP-004", () => <Toggle label="Armed" />],
  ["CMP-005", () => <Checkbox label="Reduce only" />],
  ["CMP-006", () => <RadioGroup aria-label="Mode" options={options} value="a" onChange={noop} />],
  ["CMP-007", () => <TextInput aria-label="Name" value="" onChange={noop} />],
  [
    "CMP-008",
    () => <NumericStepperInput label="Size" value={1} step={1} precision={0} onChange={noop} />,
  ],
  ["CMP-009", () => <Select aria-label="Pick" options={options} value="a" onChange={noop} />],
  [
    "CMP-010",
    () => <Slider aria-label="Level" value={1} min={0} max={5} step={1} onChange={noop} />,
  ],
  [
    "CMP-040",
    () => (
      <FormField label="Name">
        <TextInput />
      </FormField>
    ),
  ],
  ["CMP-054", () => <SearchBox label="Search users" value="alex" onChange={noop} onClear={noop} />],
  [
    "CMP-065",
    () => (
      <FormSection title="Offsets">
        <FormField label="Name">
          <TextInput />
        </FormField>
      </FormSection>
    ),
  ],
];

describe("control atoms carry their catalogue id", () => {
  it.each(atoms)("%s marks exactly one root with data-cmp", async (id, render) => {
    const host = await mount(render());
    expect(host.querySelectorAll(`[data-cmp="${id}"]`)).toHaveLength(1);
  });
});

const molecules: [string, () => JSX.Element][] = [
  [
    "CMP-042",
    () => (
      <Tabs
        aria-label="Sections"
        tabs={[{ id: "a", label: "Alpha" }]}
        value="a"
        onChange={noop}
        renderPanel={() => null}
      />
    ),
  ],
  ["CMP-045", () => <Toast title="Session extended" />],
  ["CMP-047", () => <DatePicker aria-label="Go to date" value="2026-10-23" onChange={noop} />],
  [
    "CMP-047",
    () => (
      <DateRangePicker
        aria-label="Replay range"
        value={{ start: "2026-10-01", end: "2026-10-07" }}
        onChange={noop}
      />
    ),
  ],
  [
    "CMP-049",
    () => (
      <Table
        caption="Users"
        columns={[{ id: "name", header: "Name", cell: (row: string) => row }]}
        rows={["alex"]}
        rowKey={(row) => row}
      />
    ),
  ],
  ["CMP-050", () => <Card title="Accounts">Body</Card>],
  [
    "CMP-055",
    () => (
      <FilterBar
        fields={[{ id: "role", label: "Role", options: [{ value: "viewer", label: "Viewer" }] }]}
        value={[{ field: "role", value: "viewer" }]}
        onChange={noop}
      />
    ),
  ],
  ["CMP-088", () => <PageHeader title="Users" meta="All times UTC · as of 14:02:11" />],
  [
    "CMP-173",
    () => (
      <AuditRowList>
        <AuditRow entry={auditEntry} variant="compact" href="#audit-1" />
      </AuditRowList>
    ),
  ],
  ["CMP-178", () => <SystemHealthTile label="Users" href="#users" state="ready" tone="ok" />],
];

describe("molecules carry their catalogue id", () => {
  it.each(molecules)("%s marks exactly one root with data-cmp", async (id, render) => {
    const host = await mount(render());
    expect(host.querySelectorAll(`[data-cmp="${id}"]`)).toHaveLength(1);
  });

  it("CMP-043 marks exactly one root with data-cmp (in its portalled layer)", async () => {
    await mount(<Dialog open title="Go to date" onOpenChange={noop} />);
    expect(document.querySelectorAll('[data-cmp="CMP-043"]')).toHaveLength(1);
  });

  it("CMP-059 marks exactly one root with data-cmp (inside its CMP-043 layer)", async () => {
    await mount(
      <CommandPalette
        open
        onOpenChange={noop}
        commands={[{ id: "a", label: "Alpha", group: "Action", onRun: noop }]}
      />,
    );
    expect(document.querySelectorAll('[data-cmp="CMP-059"]')).toHaveLength(1);
  });

  it("CMP-044 marks exactly one root with data-cmp (inside its CMP-043 layer)", async () => {
    await mount(
      <ConfirmDialog
        open
        title="Freeze sub_001?"
        confirmLabel="Freeze sub_001"
        onConfirm={noop}
        onCancel={noop}
      />,
    );
    expect(document.querySelectorAll('[data-cmp="CMP-044"]')).toHaveLength(1);
  });

  it("CMP-046 marks exactly one root with data-cmp (in its portalled layer)", async () => {
    await mount(<Drawer open title="Instrument rules" onOpenChange={noop} />);
    expect(document.querySelectorAll('[data-cmp="CMP-046"]')).toHaveLength(1);
  });

  it("CMP-069 marks exactly one root with data-cmp, in either form", async () => {
    const trigger = (props: object): JSX.Element => (
      <button type="button" {...props}>
        About
      </button>
    );
    await mount(<InfoPanel defaultOpen title="Iceberg" content="Text" trigger={trigger} />);
    expect(document.querySelectorAll('[data-cmp="CMP-069"]')).toHaveLength(1);
    document.body.replaceChildren();
    const host = await mount(
      <InfoPanel defaultOpen variant="inline" title="Iceberg" content="Text" trigger={trigger} />,
    );
    expect(host.querySelectorAll('[data-cmp="CMP-069"]')).toHaveLength(1);
  });

  it("CMP-041 marks exactly one root with data-cmp (its portalled menu, closed)", async () => {
    await mount(
      <Menu
        trigger={<Button>Actions</Button>}
        items={[{ id: "a", label: "Alpha", onSelect: noop }]}
      />,
    );
    expect(document.querySelectorAll('[data-cmp="CMP-041"]')).toHaveLength(1);
  });
});

describe("E08-S08's watchlist components carry their catalogue id", () => {
  const BTC: WatchlistRowData = { symbol: "BTCUSDT", priceScale: 2, lastPrice: 64012.5 };
  const watchlist: [string, () => JSX.Element][] = [
    [
      "CMP-056",
      () => (
        <ColumnPicker
          label="Columns"
          columns={[{ id: "last", label: "Last", visible: true }]}
          onChange={noop}
          onReorder={noop}
        />
      ),
    ],
    [
      "CMP-067",
      () => (
        <FileDrop
          label="Import…"
          accept=".txt"
          maxBytes={65536}
          oversizedMessage={() => "Too big."}
          notTextMessage="Not text."
          onText={noop}
        />
      ),
    ],
    [
      "CMP-161",
      () => (
        <Table<WatchlistRowData>
          grid
          caption="Watchlist Majors"
          columns={watchlistColumns(["symbol", "last"])}
          rows={[BTC]}
          rowKey={(row) => row.symbol}
          renderRow={(row, grid) => (
            <WatchlistRow grid={grid} row={row} columns={["symbol", "last"]} />
          )}
        />
      ),
    ],
    [
      "CMP-162",
      () => (
        <WatchlistGroupTabs
          aria-label="Watchlists"
          groups={[{ id: "majors", name: "Majors" }]}
          counts={{ majors: 12 }}
          activeId="majors"
          onSwitch={noop}
          onCreate={noop}
          onRename={noop}
          onDuplicate={noop}
          onDelete={noop}
          onManage={noop}
        />
      ),
    ],
    [
      "CMP-239",
      () => <FreshnessMarker presentation="compact" state="stale" lastUpdatedAgeMs={7000} />,
    ],
  ];

  it.each(watchlist)("%s marks exactly one root with data-cmp", async (id, render) => {
    const host = await mount(render());
    expect(host.querySelectorAll(`[data-cmp="${id}"]`)).toHaveLength(1);
  });
});

const organisms: [string, () => JSX.Element][] = [
  ["CMP-087", () => <AdminLayout routeLabel="Users">Body</AdminLayout>],
];

describe("organisms carry their catalogue id", () => {
  it.each(organisms)("%s marks exactly one root with data-cmp", async (id, render) => {
    const host = await mount(render());
    expect(host.querySelectorAll(`[data-cmp="${id}"]`)).toHaveLength(1);
  });
});
