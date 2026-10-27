import { describe, expect, it } from "vitest";
import { ALLOWED_IPC_CHANNELS, buildAllowList, isChannelAllowed } from "../src/preload/allowList";

describe("preload allow-list builder", () => {
  it("has exactly the named channels the ShellPort surface needs (SR-111)", () => {
    expect(ALLOWED_IPC_CHANNELS).toEqual([
      "cv:gpu:info",
      "cv:keychain:getKekHandle",
      "cv:updates:check",
      "cv:crashLog:append",
    ]);
  });

  it("rejects a channel not present in the allow-list", () => {
    expect(isChannelAllowed("not-allowed")).toBe(false);
    expect(() => buildAllowList(["not-allowed"], async () => undefined)).toThrow(
      /not on the allow-list/,
    );
  });

  it("builds an invoke function only for allow-listed channels", () => {
    const built = buildAllowList([], async () => undefined, []);
    expect(Object.keys(built)).toEqual([]);
  });

  it("invokes through the built function for a channel on an injected allow-list", async () => {
    const calls: Array<[string, unknown[]]> = [];
    const invoke = async (channel: string, ...args: unknown[]) => {
      calls.push([channel, args]);
      return "ok";
    };
    const built = buildAllowList(["test-channel"], invoke, ["test-channel"]);
    const result = await built["test-channel"]?.("arg1");
    expect(result).toBe("ok");
    expect(calls).toEqual([["test-channel", ["arg1"]]]);
  });

  it("rejects a real channel name that is not itself allow-listed for a given caller", () => {
    expect(isChannelAllowed("cv:gpu:info", ["cv:keychain:getKekHandle"])).toBe(false);
  });
});
