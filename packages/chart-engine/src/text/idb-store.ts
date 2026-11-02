// The atlas cache's IndexedDB `KvStore` (E11-S11, BQ-264). It lives in src/text/ because that is
// the one directory the E11-X02 no-I/O rule lets reach IndexedDB (TM DS1, CE-E04); the browser
// glue (src/worker/text-platform.ts) hands over its scope and never touches the database itself.
// The factory is typed structurally: this directory compiles without the DOM lib.
import { ATLAS_DB, ATLAS_STORE } from "./atlas-cache.js";
import type { KvStore } from "./platform.js";

interface Req<T> {
  result: T;
  onsuccess: (() => void) | null;
  onerror: (() => void) | null;
}
interface IdbStore {
  get(k: string): Req<unknown>;
  put(v: unknown, k: string): Req<unknown>;
  getAllKeys(): Req<unknown[]>;
  delete(k: string): Req<unknown>;
}
interface Idb {
  close(): void;
  onversionchange: (() => void) | null;
  createObjectStore(name: string): unknown;
  transaction(name: string, mode: string): { objectStore(name: string): IdbStore };
}
/** The members of an IndexedDB factory used here. */
export interface IdbFactory {
  open(name: string, v: number): Req<Idb> & { onupgradeneeded: (() => void) | null };
}

const done = <T>(r: Req<T>): Promise<T> =>
  new Promise((resolve, reject) => {
    r.onsuccess = () => resolve(r.result);
    r.onerror = () => reject(new Error("indexedDB request failed"));
  });

/** The atlas store on `scope`'s IndexedDB, or null where the scope has none. */
export async function openAtlasStore(scope: { indexedDB?: IdbFactory }): Promise<KvStore | null> {
  const factory = scope.indexedDB;
  if (factory === undefined) return null;
  const open = factory.open(ATLAS_DB, 1);
  open.onupgradeneeded = () => void open.result.createObjectStore(ATLAS_STORE);
  const db = await done(open);
  db.onversionchange = () => db.close(); // another context upgrades the database: let it
  const tx = (mode: string): IdbStore => db.transaction(ATLAS_STORE, mode).objectStore(ATLAS_STORE);
  return {
    get: (k) => done(tx("readonly").get(k)),
    put: async (k, v) => void (await done(tx("readwrite").put(v, k))),
    keys: async () => (await done(tx("readonly").getAllKeys())).map(String),
    delete: async (k) => void (await done(tx("readwrite").delete(k))),
    close: () => db.close(),
  };
}
