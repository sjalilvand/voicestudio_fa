/**
 * The renderer half of Cloud settings sync (desktop-app-guide §5): every write
 * to a synced localStorage key is mirrored to the backend, and pulled values
 * are written back without echoing.
 *
 * The wrapper patches Storage.prototype and checks the instance: assigning
 * `localStorage.setItem = …` would store an item named "setItem" instead.
 */
type Post = (key: string, value: unknown, raw: boolean) => Promise<void>;

function decode(raw: string | null): [unknown, boolean] {
  if (raw === null) return [null, false];
  try {
    return [JSON.parse(raw), false];
  } catch {
    return [raw, true];
  }
}

export function installSyncedStorage(opts: {
  storage: Storage;
  keys: readonly string[];
  post: Post;
}) {
  const { storage, post } = opts;
  const keys = new Set(opts.keys);
  const proto = Storage.prototype;
  const originalSet = proto.setItem;
  const originalRemove = proto.removeItem;
  let applying = false;

  const announce = (key: string, raw: string | null) => {
    if (applying || !keys.has(key)) return;
    const [value, isRaw] = decode(raw);
    post(key, value, isRaw).catch(() => {});
  };

  proto.setItem = function setItem(this: Storage, key: string, value: string) {
    originalSet.call(this, key, value);
    if (this === storage) announce(String(key), String(value));
  };
  proto.removeItem = function removeItem(this: Storage, key: string) {
    originalRemove.call(this, key);
    if (this === storage) announce(String(key), null);
  };

  return {
    /** Write a pulled value; stores listening for `storage` events re-read it. */
    apply(key: string, value: unknown, raw: boolean) {
      if (!keys.has(key)) return;
      applying = true;
      try {
        if (value === null || value === undefined) storage.removeItem(key);
        else storage.setItem(key, raw && typeof value === 'string' ? value : JSON.stringify(value));
      } finally {
        applying = false;
      }
      window.dispatchEvent(new StorageEvent('storage', { key, newValue: storage.getItem(key) }));
    },
    /** Current values of every synced key, for the first mirror after start-up. */
    snapshot(): Array<[string, unknown, boolean]> {
      const out: Array<[string, unknown, boolean]> = [];
      for (const key of keys) {
        const raw = storage.getItem(key);
        if (raw !== null) out.push([key, ...decode(raw)]);
      }
      return out;
    },
    uninstall() {
      proto.setItem = originalSet;
      proto.removeItem = originalRemove;
    },
  };
}
