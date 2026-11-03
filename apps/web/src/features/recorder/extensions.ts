/**
 * SCR-140's extension seam (#485/#486 ruling BQ-6; BQ-11): SCR-141's retention editor (E16-S03) and SCR-142's
 * storage section (E16-S04) register here, and `openRowDetail(symbol)` (the row detail, #484 PR 3), so S03's
 * "Manage pin in Recorder" can reach a row. The page renders "Retention policy" and "Storage details" only when
 * their part is registered. Each part receives the page's reads, so none opens a second `recorder` topic.
 */
import { useSyncExternalStore, type ComponentType } from "react";
import type { RecorderFrame, RecordingStatus, StorageUsage } from "./model/types";

/** What SCR-140 hands an extension: its first-paint reads and the topic's view. */
export interface RecorderExtensionView {
  readonly status: RecordingStatus | null;
  readonly storage: StorageUsage | null;
  readonly frame: RecorderFrame | null;
  readonly stale: boolean;
}

/** SCR-141, a dialog over SCR-140 (E16-D03): focus returns to "Retention policy" on close (KB-09). */
export interface RetentionEditorProps extends RecorderExtensionView {
  readonly open: boolean;
  readonly onClose: () => void;
}

/** SCR-142, a section of `/admin/recorder` (E16-D04): its heading takes `headingId` ("Storage details" moves there). */
export interface StoragePanelProps extends RecorderExtensionView {
  readonly headingId: string;
}

export interface RecorderExtensions {
  readonly RetentionEditor?: ComponentType<RetentionEditorProps>;
  readonly StoragePanel?: ComponentType<StoragePanelProps>;
  /** Opens a row's detail (the drawer, D02 §6.7). */
  readonly openRowDetail?: (symbol: string) => void;
}

type Mutable = { -readonly [K in keyof RecorderExtensions]: RecorderExtensions[K] };

let current: RecorderExtensions = {};
const listeners = new Set<() => void>();
const emit = (): void => listeners.forEach((listener) => listener());

/**
 * Registers `parts` over what is there; the returned function removes each part it set, unless another
 * registration replaced it since.
 */
export function registerRecorderExtensions(parts: RecorderExtensions): () => void {
  current = { ...current, ...parts };
  emit();
  return () => {
    const next: Mutable = { ...current };
    if (parts.RetentionEditor !== undefined && next.RetentionEditor === parts.RetentionEditor) {
      delete next.RetentionEditor;
    }
    if (parts.StoragePanel !== undefined && next.StoragePanel === parts.StoragePanel) {
      delete next.StoragePanel;
    }
    if (parts.openRowDetail !== undefined && next.openRowDetail === parts.openRowDetail) {
      delete next.openRowDetail;
    }
    current = next;
    emit();
  };
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => void listeners.delete(listener);
}
const snapshot = (): RecorderExtensions => current;

/** The registered parts; a registration re-renders the page. */
export const useRecorderExtensions = (): RecorderExtensions =>
  useSyncExternalStore(subscribe, snapshot, snapshot);
