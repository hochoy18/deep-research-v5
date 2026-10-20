import { defineConfig } from "vitest/config";

export default defineConfig({
  // Next compiles JSX with the automatic runtime; esbuild defaults to the
  // classic one, which leaves `React` undefined in a `.tsx` test.
  esbuild: { jsx: "automatic" },
  test: {
    environment: "jsdom",
    // An explicit origin is what makes `window.localStorage` exist: on
    // jsdom's default opaque origin the getter is present but returns
    // undefined, which reads as "no storage" rather than as a bug.
    environmentOptions: { jsdom: { url: "http://localhost:3000" } },
    setupFiles: ["./test/setup.ts"],
    globals: false,
    // `*.test.tsx` too: issue #3's acceptance criteria name what the Plan
    // page renders, so the page itself needs a test, not just its helpers.
    include: ["lib/**/*.test.ts", "lib/**/*.test.tsx", "app/**/*.test.tsx"],
  },
  resolve: {
    alias: {
      "@": new URL(".", import.meta.url).pathname,
    },
  },
});