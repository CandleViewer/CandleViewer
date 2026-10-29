// E10-S04 (#306) slice 10a: SCR-157's comparison, a pure function of the client's version and the
// last `welcome`'s build label (23 §2.3, §4.2), and `app.version_mismatch` once per pair (`14` SCR-157).
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { CLIENT_PROTOCOL } from "../../../src/lib/ws/protocol/frames";
import {
  checkVersion,
  reportVersionMismatch,
  resetVersionReports,
  type VersionCheck,
} from "../../../src/features/system-states/versionMismatch";

type Row = [string, string, string | null | undefined, string | undefined, VersionCheck];

describe("checkVersion", () => {
  it.each<Row>([
    ["no welcome yet", "1.4.2", undefined, undefined, "compatible"],
    ["the same build", "1.4.2", "cv.v1", "1.4.2", "compatible"],
    ["a build label the client did not keep", "1.4.2", "cv.v1", undefined, "compatible"],
    // a welcome whose protocol label was refused: 10b's dialog fails closed
    ["a protocol label refused, the same build", "1.4.2", null, "1.4.2", "incompatible"],
    ["a protocol label refused, another build", "1.4.2", null, "1.4.3", "incompatible"],
    ["another build on the negotiated protocol", "1.4.2", "cv.v1", "1.4.3", "update_available"],
    ["an older build on the negotiated protocol", "1.4.2", "cv.v1", "1.4.1", "update_available"],
    ["a label that differs in case only", "1.4.2-rc", "cv.v1", "1.4.2-RC", "update_available"],
    ["another protocol, the same build", "1.4.2", "cv.v2", "1.4.2", "incompatible"],
    ["another protocol and another build", "1.4.2", "cv.v2", "1.4.3", "incompatible"],
    ["another protocol, no build label", "1.4.2", "cv.v2", undefined, "incompatible"],
    ["a protocol that differs in case only", "1.4.2", "CV.V1", "1.4.2", "incompatible"],
  ])("%s", (_case, client, protocol, version, expected) => {
    expect(checkVersion(client, protocol, version)).toBe(expected);
  });

  it("compares with cv.v1, the one protocol constant hello names (23 §2.3)", () => {
    expect(CLIENT_PROTOCOL).toBe("cv.v1");
    expect(checkVersion("1.4.2", CLIENT_PROTOCOL, "1.4.2")).toBe("compatible");
  });
});

describe("reportVersionMismatch", () => {
  let heard: unknown[];
  const listener = (event: Event): void => void heard.push((event as CustomEvent).detail);
  beforeEach(() => {
    heard = [];
    resetVersionReports();
    window.addEventListener("cv:analytics", listener);
  });
  afterEach(() => window.removeEventListener("cv:analytics", listener));

  it("says app.version_mismatch on cv:analytics once per distinct pair a session, versions only", () => {
    const said = (serverVersion: string) => ({
      name: "app.version_mismatch",
      clientVersion: "0.1.0",
      serverVersion,
      blocking: false,
    });
    reportVersionMismatch("0.1.0", "0.2.0", false);
    reportVersionMismatch("0.1.0", "0.2.0", false);
    reportVersionMismatch("0.1.0", "0.3.0", false);
    reportVersionMismatch("0.1.0", "0.2.0", false); // back to a pair already said
    expect(heard).toEqual([said("0.2.0"), said("0.3.0")]);
    resetVersionReports(); // a new session says it again
    reportVersionMismatch("0.1.0", "0.2.0", false);
    expect(heard).toEqual([said("0.2.0"), said("0.3.0"), said("0.2.0")]);
  });
});
