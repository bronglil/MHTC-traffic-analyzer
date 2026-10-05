import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

const api = process.env.VITE_API_PROXY ?? "http://localhost:8000";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  // Unit tests only; browser tests in e2e/ run with Playwright (npm run test:e2e).
  test: { include: ["src/**/*.test.ts"] },
  server: {
    proxy: {
      "/api": { target: api, changeOrigin: true, ws: true },
    },
  },
});
