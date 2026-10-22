import { defineConfig } from "tsup";

export default defineConfig({
  entry: { index: "src/index.ts", "rule-ir": "src/generated/ruleIr/index.ts" },
  format: ["esm"],
  dts: true,
  sourcemap: true,
  clean: true,
  target: "es2022",
  platform: "neutral",
});
