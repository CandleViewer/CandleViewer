/**
 * SCR-141's registration (#485/#486 BQ-6, BQ-14): SCR-140 draws "Retention policy" (the disk card and the level-3
 * banner) only while an editor is registered, so this call is what makes SCR-141 reachable. Nothing calls it yet:
 * the R-340 route that mounts SCR-140 (#484's route swap) wires it beside SCR-142's, and until then the editor is
 * unreachable, with no flag (C-4.13). The returned function takes the editor away again.
 */
import { registerRecorderExtensions } from "../extensions";
import { RetentionEditor } from "./RetentionEditor";

export function registerRetentionEditor(): () => void {
  return registerRecorderExtensions({ RetentionEditor });
}
