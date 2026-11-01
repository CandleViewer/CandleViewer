/**
 * SCR-142's registration (#485/#486 BQ-6, BQ-14): SCR-140 draws "Storage details" and the storage section only while
 * a panel is registered, so this call is what makes SCR-142 reachable. Nothing calls it yet: the R-340 route that
 * mounts SCR-140 (#484's route swap) wires it beside SCR-141's, and until then the section is unreachable, with no
 * flag (C-4.13). The returned function takes the section away again.
 */
import { registerRecorderExtensions } from "../extensions";
import { StoragePanel } from "./StoragePanel";

export function registerStoragePanel(): () => void {
  return registerRecorderExtensions({ StoragePanel });
}
