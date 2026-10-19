// Runs before electron-builder in build:installer. electron-builder.yml copies ../web/dist
// into the installer as the only web app the app:// handler serves, and electron-builder
// only warns when an extraResources `from` is missing, so an installer built without it
// would open an empty window. Refuse to package until apps/web is built (#3518).
import console from "node:console";
import { existsSync } from "node:fs";
import process from "node:process";
import { URL } from "node:url";

if (!existsSync(new URL("../../web/dist/index.html", import.meta.url))) {
  console.error(
    "build:installer: apps/web/dist/index.html is missing; build @candleviewer/web first",
  );
  process.exit(1);
}
