import { defineConfig } from "@playwright/test";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

// Fresh backend data dir + SQLite DB for every run, so tests never depend on old state.
const dataDir = process.env.TV_E2E_DATA_DIR ?? mkdtempSync(join(tmpdir(), "tv-e2e-"));
const API_PORT = 8765;
const WEB_PORT = 5765;

export default defineConfig({
  testDir: "e2e",
  timeout: 180_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: `http://localhost:${WEB_PORT}`,
    viewport: { width: 1400, height: 1000 },
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    // Use a pre-installed Chromium when provided (e.g. CI images), else Playwright's own.
    launchOptions: process.env.PW_CHROMIUM_PATH ? { executablePath: process.env.PW_CHROMIUM_PATH } : {},
  },
  webServer: [
    {
      command: `python -m uvicorn app.main:app --port ${API_PORT}`,
      cwd: "../backend",
      url: `http://localhost:${API_PORT}/api/health`,
      env: {
        TV_DATA_DIR: dataDir,
        TV_DATABASE_URL: `sqlite:///${dataDir}/e2e.db`,
        TV_EMBEDDED_WORKER: "true",
        TV_WORKER_POLL_SECONDS: "0.2",
      },
      reuseExistingServer: false,
      timeout: 60_000,
    },
    {
      command: `npx vite --port ${WEB_PORT} --strictPort`,
      url: `http://localhost:${WEB_PORT}`,
      env: { VITE_API_PROXY: `http://localhost:${API_PORT}` },
      reuseExistingServer: false,
      timeout: 60_000,
    },
  ],
});
