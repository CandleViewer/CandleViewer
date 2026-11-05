import { useEffect, useState, type JSX } from "react";
import { createFakeEngine } from "../engine/stub/fakeEngine";
import { normaliseDescriptor, type CatalogueEntry } from "../model/catalogue";
import { createIndicatorStore } from "../store/indicatorStore";
import type { IndicatorPreviewPort } from "./clock";
import { IndicatorSettingsDialog, type SettingsAccess } from "./IndicatorSettingsDialog";

// SCR-035 (E13-S01 #423 S4): the story host (BQ-06: no route mounts the dialog yet). Plain CSF, no
// storybook types, as SettingsNav's. Each story opens the dialog over a fake engine; the states a
// user reaches by typing are driven once after mount through the DOM, as a person would.
export default {
  title: "Features/Indicators/IndicatorSettingsDialog",
  component: IndicatorSettingsDialog,
};

const period = { type: "integer", title: "Period", minimum: 1, maximum: 5000, default: 21 };
const descriptor = (id: string, compute: string, properties: Record<string, unknown>) =>
  normaliseDescriptor({
    id,
    name: id.toUpperCase(),
    category: "trend",
    pane: "price",
    compute,
    estimated: false,
    params_schema: { type: "object", additionalProperties: false, properties },
    defaults: {},
    outputs: [{ id, name: id.toUpperCase() }],
  }) as CatalogueEntry;

const EMA = descriptor("ema", "server", { n: period });
const BOLL = descriptor("bollinger", "client_worker", {
  n: { ...period, default: 20 },
  mult: {
    type: "number",
    title: "Standard deviations",
    minimum: 0.1,
    maximum: 10,
    multipleOf: 0.1,
    default: 2,
  },
});
const VWAP = descriptor("vwap", "server", {
  anchor: { type: "string", title: "Anchor", enum: ["session", "week"], default: "session" },
  bands: { type: "boolean", title: "Show bands", default: false },
  shape: { type: "object", title: "Band shape", properties: {} },
});
const VOLUME = descriptor("volume", "server", {});

/** A preview that lands after `ms`, or never (`null`): "Updating…" shows past 100 ms. */
const previewAfter = (ms: number | null): IndicatorPreviewPort => ({
  preview: () =>
    new Promise<void>((resolve) => {
      if (ms !== null) globalThis.setTimeout(resolve, ms);
    }),
  clear: () => undefined,
});

/** Sets a field's text as typing would (React reads the native value setter's input event). */
function typeInto(name: string, value: string): void {
  const input = [...document.querySelectorAll<HTMLInputElement>('[role="spinbutton"]')].find(
    (el) => el.labels?.[0]?.textContent === name,
  );
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
  if (input === undefined || setter === undefined) return;
  setter.call(input, value);
  input.dispatchEvent(new Event("input", { bubbles: true }));
}

const press = (selector: string, text: string): void => {
  [...document.querySelectorAll<HTMLElement>(selector)]
    .find((el) => el.textContent === text)
    ?.click();
};

interface HostProps {
  readonly entry: CatalogueEntry;
  /** The entry the instance is added with, when the dialog is handed another (a hostile reload). */
  readonly addWith?: CatalogueEntry;
  readonly params?: Record<string, unknown>;
  readonly target?: "overlay" | "subpane";
  readonly access?: SettingsAccess;
  readonly preview?: IndicatorPreviewPort;
  readonly capacity?: number;
  readonly script?: () => void;
}

function Host(props: HostProps): JSX.Element {
  const [setup] = useState(() => {
    const store = createIndicatorStore({ report: () => undefined, hasPlugin: () => true });
    const engine = createFakeEngine();
    store.bind("story", engine);
    const added = store.add("story", {
      entry: props.addWith ?? props.entry,
      params: props.params ?? {},
      target: props.target ?? "overlay",
      source: "library",
    });
    if (props.capacity !== undefined) engine.capacity = props.capacity;
    return { store, id: added.ok ? added.id : null };
  });
  const [open, setOpen] = useState(true);
  const { script } = props;
  useEffect(() => {
    if (script !== undefined) queueMicrotask(script);
  }, [script]);
  if (setup.id === null) return <p>The fake engine refused the instance.</p>;
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>
        Open settings
      </button>
      <IndicatorSettingsDialog
        open={open}
        onClose={() => setOpen(false)}
        store={setup.store}
        chart="story"
        instanceId={setup.id}
        entry={props.entry}
        label={`${props.entry.id.toUpperCase()} 21`}
        timeframe="5m"
        access={props.access ?? { viewAs: null, canWrite: true }}
        {...(props.preview === undefined ? {} : { preview: props.preview })}
      />
    </>
  );
}

/** A `server` instance: the committed curve, "Preview on Apply…"; commits on Enter or Apply only. */
export const ServerInstance = { render: () => <Host entry={EMA} /> };

/** A `client_worker` instance: previews each valid change, display-only. */
export const ClientWorker = { render: () => <Host entry={BOLL} preview={previewAfter(20)} /> };

/** A recompute past 100 ms: "Updating…" under the tile. */
export const Updating = {
  render: () => (
    <Host entry={BOLL} preview={previewAfter(null)} script={() => typeInto("Period", "30")} />
  ),
};

/** Non-default values: the header and the field carry the dot and "edited". */
export const Edited = { render: () => <Host entry={EMA} params={{ n: 34 }} /> };

/** A value refused, never clamped: the deck sentence, Apply at opacity.disabled with its reason. */
export const Invalid = {
  render: () => <Host entry={BOLL} script={() => typeInto("Standard deviations", "2.25")} />,
};

/** The Style tab: its token controls are absent, with one note (C-b). */
export const StyleTab = {
  render: () => <Host entry={EMA} script={() => press('[role="tab"]', "Style")} />,
};

/** Enum, boolean and the deck's read-only row for a type outside the subset. */
export const MixedControls = { render: () => <Host entry={VWAP} /> };

/** "This indicator has no parameters." */
export const NoParameters = { render: () => <Host entry={VOLUME} /> };

/** A sub-pane instance's header. */
export const SubPane = { render: () => <Host entry={EMA} target="subpane" /> };

/** T2, the view-as leg first: one header notice; Apply locked and pointing at it. */
export const ViewingAs = {
  render: () => <Host entry={BOLL} access={{ viewAs: "alex", canWrite: false }} />,
};

/** T2, the role leg: "Your role can't save workspaces." */
export const Viewer = {
  render: () => <Host entry={BOLL} access={{ viewAs: null, canWrite: false }} />,
};

/** The server at capacity: the dialog stays open with the deck's sentence. */
export const AtCapacity = {
  render: () => (
    <Host
      entry={EMA}
      capacity={0}
      script={() => {
        typeInto("Period", "50");
        queueMicrotask(() => press("button", "Apply"));
      }}
    />
  ),
};

/** A hostile schema in a reloaded catalogue: one safe error, nothing rendered from the payload. */
export const HostileSchema = {
  render: () => (
    <Host
      addWith={EMA}
      entry={descriptor("ema", "server", { n: { $ref: "#/definitions/<img src=x>" } })}
    />
  ),
};
