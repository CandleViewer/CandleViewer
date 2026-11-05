// E13-S01 (#423) S1: the indicator model's types. Wire shapes come from the generated protocol only
// (C-4.16); everything else here is local model (BQ-3: instances are client chart state).
import type { generated } from "@candleviewer/protocol";

type Schemas = generated.rest.components["schemas"];

export type IndicatorDescriptor = Schemas["IndicatorDescriptor"];
export type IndicatorPreset = Schemas["IndicatorPreset"];
export type IndicatorPresetInput = Schemas["IndicatorPresetInput"];
/** One `listIndicators` 200 body. */
export type CatalogueBody =
  generated.rest.operations["listIndicators"]["responses"][200]["content"]["application/json"];
/** One `indicators.*` subscription entry (`23` §13 `indicatorInstance`). */
export type WsIndicatorInstance = generated.ws.IndicatorInstance;

export type Compute = IndicatorDescriptor["compute"];
export type DescriptorPane = IndicatorDescriptor["pane"];
export type Category = NonNullable<IndicatorDescriptor["category"]>;
export type Unit = NonNullable<IndicatorDescriptor["unit"]>;
export type PaneTarget = IndicatorPreset["pane_target"];

/** A parameter value as the WS entry carries it (`23` §13); numbers stay JSON numbers. */
export type ParamValue = NonNullable<WsIndicatorInstance["params"]>[string];
/** A complete, validated parameter object: null-prototype, frozen, in the schema's order (SR-E13-09). */
export type Params = Readonly<Record<string, ParamValue>>;
