// E22-S01 (#714) BQ-217: `orderflow.tape` as a build-time switch. `apps/web` has no client flag
// service (G-56), so the flag is the Vite variable `VITE_FLAG_ORDERFLOW_TAPE`: off ("unset") in
// every environment, on ("1") only in the Playwright build. Off, nothing subscribes and no panel
// mounts (C-4.13). Its removal is owned by the E15 dock ticket that docks SCR-053.

/** `true` only in a build made with `VITE_FLAG_ORDERFLOW_TAPE=1`. */
export const TAPE_ENABLED: boolean = import.meta.env.VITE_FLAG_ORDERFLOW_TAPE === "1";
