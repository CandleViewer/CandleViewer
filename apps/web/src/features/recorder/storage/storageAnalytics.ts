/**
 * SCR-142's analytics (E16-D04 D04-D10; `14` SCR-142 "Analytics/audit"; E16-D06 C-z): `storage.panel_viewed`, once
 * per entry, on the app's seam (`cv:analytics` on `window`, as SCR-140 reports). The payload carries nothing: never
 * a user, a symbol, a size or a server message. The maintenance actions are the server's to audit
 * (`recorder.compact`, `recorder.import`, `retention.purge`); the client passes no audit name, and a T2 press emits
 * nothing.
 */
import { THEME_ANALYTICS_EVENT } from "../../../shell/bootstrap/themeStore";

export type StorageAnalytics = { readonly name: "storage.panel_viewed" };

export function reportStorage(event: StorageAnalytics): void {
  window.dispatchEvent(new CustomEvent<StorageAnalytics>(THEME_ANALYTICS_EVENT, { detail: event }));
}
