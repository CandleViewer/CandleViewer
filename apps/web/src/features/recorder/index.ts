/**
 * The recorder feature's public surface (E16-S01; E16-S02's REC chip and picker reuse the client).
 * Nothing imports it until SCR-140 mounts at `/admin/recorder` (E16-S01 9/9): no route, no flag
 * (C-4.13).
 */
export * from "./recorderApi";
export * from "./recorderTopic";
