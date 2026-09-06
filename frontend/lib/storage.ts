// Storage is optional. Its failure must never turn a confirmed anchor into an error.
export const tabStorage = {
  get(key: string): string | null {
    try { return window.sessionStorage.getItem(key); } catch { return null; }
  },
  set(key: string, value: string): void {
    try { window.sessionStorage.setItem(key, value); } catch { /* In-memory workflow remains available. */ }
  },
  remove(key: string): void {
    try { window.sessionStorage.removeItem(key); } catch { /* Storage may be disabled. */ }
  },
};
