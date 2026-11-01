/**
 * The generated protocol types SCR-140's model reads (C-4.16: never a hand-written DTO): REST
 * `22` `/recording/*` and the WS `recorder` topic (23 §6.2.2, §15.8).
 */
import type { generated } from "@candleviewer/protocol";

type Schemas = generated.rest.components["schemas"];

export type RecordedSymbol = Schemas["RecordedSymbol"];
export type RecordingStatus = Schemas["RecordingStatus"];
export type StorageUsage = Schemas["StorageUsage"];
export type RecorderPolicy = Schemas["RecorderPolicySettings"];
export type RecordReason = Schemas["RecordReason"];
export type RecordingState = Schemas["RecordingState"];
export type RecorderFrame = generated.ws.Recorder;
