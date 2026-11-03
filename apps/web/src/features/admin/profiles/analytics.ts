/**
 * SCR-130's client analytics (E28-S01; `14` SCR-130 `profile.list_viewed`; E28-D06 §11): an event
 * name and counts only, never an account label, symbol list, figure or free text. No analytics
 * transport is named by any plan document (E28-D06 G6-1), so the default sink does nothing and no
 * wire is invented (the `features/admin-connectivity/analytics.ts` pattern).
 */
export interface ListViewedEvent {
  readonly name: "profile.list_viewed";
  readonly accounts: number;
  readonly profiles: number;
}

/** A refused write, counted by its served code (the ticket's save-failures metric). */
export interface WriteRefusedEvent {
  readonly name: "profile.write_refused";
  readonly operation: "delete";
  readonly code: string;
}

export type ProfilesEvent = ListViewedEvent | WriteRefusedEvent;

export interface ProfilesAnalytics {
  emit(event: ProfilesEvent): void;
}

export const noopProfilesAnalytics: ProfilesAnalytics = { emit: () => undefined };
