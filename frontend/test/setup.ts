/**
 * Test setup.
 *
 * Node 26 exposes a global `localStorage` that is `undefined` unless the
 * process was started with `--localstorage-file`. Vitest copies jsdom's
 * globals onto `globalThis` but skips any key that already exists there,
 * so that stub shadows jsdom's working implementation and every
 * `window.localStorage` access returns `undefined` — which reads as "no
 * bearer stored" rather than as a broken test environment.
 *
 * So: install a minimal in-memory Storage when the real one is missing.
 * `lib/bearer.ts` only uses get/set/remove/clear, and `bearer.test.ts`
 * relies on exactly those.
 */

import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

class MemoryStorage implements Storage {
  private items = new Map<string, string>();

  get length(): number {
    return this.items.size;
  }

  clear(): void {
    this.items.clear();
  }

  getItem(key: string): string | null {
    return this.items.get(key) ?? null;
  }

  key(index: number): string | null {
    return [...this.items.keys()][index] ?? null;
  }

  removeItem(key: string): void {
    this.items.delete(key);
  }

  setItem(key: string, value: string): void {
    this.items.set(key, String(value));
  }
}

if (typeof window !== "undefined" && !window.localStorage) {
  Object.defineProperty(window, "localStorage", {
    value: new MemoryStorage(),
    configurable: true,
    writable: true,
  });
}

// React 19 asks for this flag before `act()`; Testing Library's `render`
// would otherwise warn on every component test.
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

// Testing Library cleans up rendered trees between tests. Registering it
// here means a component test file does not have to remember to.
afterEach(() => {
  cleanup();
});