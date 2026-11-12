import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    environment: "node",
    include: ["test/**/*.test.ts"],
    testTimeout: 20_000,
  },
  resolve: {
    alias: {
      "@tpmsc/protocol": new URL("../packages/protocol/src/index.ts", import.meta.url).pathname,
    },
  },
});
