// E08-S12 (#5207) BQ-5: the build-time slice flags (`flags.ts`).
interface ImportMetaEnv {
  readonly VITE_FLAG_CONNECTIVITY_RATE_BUDGET?: string;
  readonly VITE_FLAG_CONNECTIVITY_CONNECTION?: string;
  readonly VITE_FLAG_CONNECTIVITY_CLOCK?: string;
  readonly VITE_FLAG_CONNECTIVITY_RESERVE?: string;
  readonly VITE_FLAG_CONNECTIVITY_INSPECTOR?: string;
  readonly VITE_FLAG_CONNECTIVITY_ACTIONS?: string;
}
