// E11-S09 PR 2 (#446 BQ-21): the main-thread registry with fake members. Membership across
// hosts, the relay flag once a group spans two worker links, the relay with the origin kept,
// and one announcement per group per state change.
import { describe, expect, it } from "vitest";
import { DEFAULT_SYNC_MODES, type SyncModes } from "../../src/sync/SyncGroup.js";
import {
  SyncRegistry,
  syncRegistryFor,
  syncText,
  type SyncMember,
} from "../../src/sync/registry.js";
import type { Command, FromWorker, SyncMessage } from "../../src/worker/protocol.js";

interface Fake extends SyncMember {
  readonly name: string;
  readonly cmds: Command[];
  readonly synced: [string, Omit<SyncMessage, "t" | "groupId">][];
}

const said: [string, string][] = [];

function member(name: string, link: object): Fake {
  const cmds: Command[] = [];
  const synced: Fake["synced"] = [];
  return {
    name,
    link,
    cmds,
    synced,
    command: (c) => void cmds.push(c),
    sync: (g, p) => void synced.push([g, p]),
    say: (text) => void said.push([name, text]),
  };
}

const WITH_LEVELS: SyncModes = { time: true, crosshair: true, levels: true };

describe("Scenario: Sync state announced once", () => {
  it("test_levelsOnThreeMembers_announcesLinkedOnce_sameStateSaysNothing", () => {
    said.length = 0;
    const reg = new SyncRegistry();
    const link = {};
    const [a, b, c] = [member("a", link), member("b", link), member("c", link)];
    reg.set(a, "g", DEFAULT_SYNC_MODES); // one member: still unlinked, nothing said
    reg.set(b, "g", DEFAULT_SYNC_MODES);
    reg.set(c, "g", DEFAULT_SYNC_MODES); // the same state: nothing
    expect(said).toEqual([["b", "Panes linked: time, crosshair"]]);
    said.length = 0;
    for (const m of [a, b, c]) reg.set(m, "g", WITH_LEVELS);
    expect(said).toEqual([["a", "Panes linked: time, crosshair, levels"]]);
    said.length = 0;
    for (const m of [a, b, c]) reg.set(m, "g", WITH_LEVELS); // a repeat says nothing
    expect(said).toEqual([]);
    reg.set(a, null, WITH_LEVELS);
    reg.set(b, null, WITH_LEVELS); // c alone: unlinked, said once by the one who left
    expect(said).toEqual([["b", "Panes unlinked"]]);
    expect(reg.groupOf(a)).toBeNull();
    expect(reg.groupOf(c)).toEqual({ groupId: "g", modes: WITH_LEVELS, relay: false });
  });

  it("test_dispose_remainingMemberSaysUnlinked_andEachMemberGetsItsSetSync", () => {
    said.length = 0;
    const reg = new SyncRegistry();
    const link = {};
    const [a, b] = [member("a", link), member("b", link)];
    reg.set(a, "g", DEFAULT_SYNC_MODES);
    reg.set(b, "g", DEFAULT_SYNC_MODES);
    reg.remove(a); // disposed: b says it
    reg.remove(a); // twice: nothing
    expect(said).toEqual([
      ["b", "Panes linked: time, crosshair"],
      ["b", "Panes unlinked"],
    ]);
    const set = { k: "setSync", groupId: "g", modes: DEFAULT_SYNC_MODES, relay: false };
    expect(a.cmds).toEqual([set]);
    expect(b.cmds).toEqual([set]);
    reg.remove(b);
    expect(said).toHaveLength(2); // the group is gone; nothing more to say
    expect(reg.groupOf(b)).toBeNull();
  });

  it("test_switchFromAToB_announcesOnceInOneCall_theNewGroupsState_m4", () => {
    said.length = 0;
    const reg = new SyncRegistry();
    const link = {};
    const [a, b, c, d] = ["a", "b", "c", "d"].map((n) => member(n, link)) as [
      Fake,
      Fake,
      Fake,
      Fake,
    ];
    reg.set(a, "A", DEFAULT_SYNC_MODES);
    reg.set(b, "A", DEFAULT_SYNC_MODES);
    reg.set(c, "B", WITH_LEVELS);
    said.length = 0;
    reg.set(b, "B", WITH_LEVELS); // A goes unlinked, B goes linked: one call, one announcement
    expect(said).toEqual([["b", "Panes linked: time, crosshair, levels"]]);
    said.length = 0;
    reg.set(d, "A", DEFAULT_SYNC_MODES); // A was recorded unlinked: d links it again, said once
    expect(said).toEqual([["d", "Panes linked: time, crosshair"]]);
    said.length = 0;
    reg.set(d, "C", DEFAULT_SYNC_MODES); // C alone is unchanged; A's new state is said instead
    expect(said).toEqual([["d", "Panes unlinked"]]);
  });

  it("test_syncText_ordersModes_andNoneIsUnlinked", () => {
    expect(syncText({ time: false, crosshair: true, levels: true })).toBe(
      "Panes linked: crosshair, levels",
    );
    expect(syncText({ time: false, crosshair: false, levels: false })).toBe("Panes unlinked");
    expect(syncText(null)).toBe("Panes unlinked");
  });
});

describe("BQ-21: relay only when a group spans more than one worker link", () => {
  it("test_secondLink_turnsRelayOnForEveryMember_andBackOffWhenItLeaves", () => {
    const reg = new SyncRegistry();
    const [l1, l2] = [{}, {}];
    const [a, b, c] = [member("a", l1), member("b", l1), member("c", l2)];
    reg.set(a, "g", DEFAULT_SYNC_MODES);
    reg.set(b, "g", DEFAULT_SYNC_MODES);
    expect(a.cmds.at(-1)).toMatchObject({ relay: false });
    reg.set(c, "g", DEFAULT_SYNC_MODES);
    for (const m of [a, b, c]) expect(m.cmds.at(-1)).toMatchObject({ groupId: "g", relay: true });
    reg.set(c, "other", DEFAULT_SYNC_MODES);
    for (const m of [a, b]) expect(m.cmds.at(-1)).toMatchObject({ groupId: "g", relay: false });
    expect(c.cmds.at(-1)).toMatchObject({ groupId: "other", relay: false });
  });

  it("test_relay_toOneMemberPerOtherLink_originKept_neverBackToItsOwnLink", () => {
    const reg = new SyncRegistry();
    const [l1, l2, l3] = [{}, {}, {}];
    const [a, b, c, d, e] = [
      member("a", l1),
      member("b", l1),
      member("c", l2),
      member("d", l2),
      member("e", l3),
    ];
    for (const m of [a, b, c, d]) reg.set(m, "g", DEFAULT_SYNC_MODES);
    reg.set(e, "other", DEFAULT_SYNC_MODES);
    const origin = { worker: "worker-1.0", chart: 3, seq: 7 };
    const msg: Extract<FromWorker, { t: "sync" }> = {
      t: "sync",
      id: 3,
      groupId: "g",
      timeRange: [10, 20],
      origin,
    };
    reg.relay(a, msg);
    expect([a, b, c, d, e].map((m) => m.synced.length)).toEqual([0, 0, 1, 0, 0]);
    expect(c.synced[0]).toEqual(["g", { timeRange: [10, 20], origin }]);
    reg.relay(a, { t: "sync", id: 3, groupId: "g", crosshair: null, origin }); // crosshair-only
    expect(c.synced[1]).toEqual(["g", { crosshair: null, origin }]);
    reg.relay(e, msg); // e is not in g: nothing
    reg.relay(member("x", l2), msg); // unknown member: nothing
    expect(c.synced).toHaveLength(2);
  });

  it("test_syncRegistryFor_oneRegistryPerRealm", () => {
    const [r1, r2] = [{}, {}];
    expect(syncRegistryFor(r1)).toBe(syncRegistryFor(r1));
    expect(syncRegistryFor(r1)).not.toBe(syncRegistryFor(r2));
  });
});
