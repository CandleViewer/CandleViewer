/**
 * Build-time switch for SCR-002's recovery-code form (#2711 BQ-08 (a)): `true` only in a build made with
 * `CV_MFA_RECOVERY_UI=1` (see `vite.config.ts`), `false` in every other, so a production build does not
 * bundle the form. A recovery sign-in mints an enrolment-only session whose one exit, standalone SCR-003
 * (R-006), is not built yet; the switch comes out with that screen. It gates no safety invariant (C-4.14).
 */
declare const __CV_MFA_RECOVERY_UI__: boolean;
