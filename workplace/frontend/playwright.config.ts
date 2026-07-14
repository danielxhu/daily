import { defineConfig, devices } from "@playwright/test";

// Browser smoke for the thin report. Runs against a production mock build
// (NEXT_PUBLIC_API_MOCK=1 via `build:mock` + `start`), so no backend is required.
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: 0,
  reporter: [
    ["list"],
    ["html", { outputFolder: "playwright-report", open: "never" }],
  ],
  use: {
    // e2e owns its own port (3100): the dev servers on :3000/:8000 can stay up
    // without the suite silently reusing a NON-mock server (M16.1 review fix —
    // it bit both reviewers repeatedly). Note build:mock still replaces .next,
    // so a dev server sharing this checkout needs a restart after an e2e run.
    baseURL: "http://localhost:3100",
    trace: "on",
    screenshot: "on",
  },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"] } },
    { name: "mobile", use: { ...devices["Pixel 5"] } },
  ],
  // Run against a production build in mock mode: no dev overlay, no Strict-Mode
  // double effects, and it is the real "local demo" of the thin report.
  webServer: {
    command: "npm run build:mock && npm run start -- -p 3100",
    url: "http://localhost:3100",
    // NEVER reuse an existing server: a stale/non-mock server on the port makes
    // every spec time out on html[data-msw-ready] with zero explanation. Failing
    // loudly ("port already used") is the reproducible behavior reviews need.
    reuseExistingServer: false,
    timeout: 300_000, // build:mock + start on a loaded machine can pass 3 min
  },
});
