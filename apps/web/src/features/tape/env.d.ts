// E22-S01 (#714) BQ-217: the build-time tape flag (`flag.ts`).
interface ImportMetaEnv {
  readonly VITE_FLAG_ORDERFLOW_TAPE?: string;
}
