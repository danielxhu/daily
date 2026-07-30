import { defineConfig, devices } from "@playwright/test";

// Browser smoke for the thin report. Runs against a production mock build
// (NEXT_PUBLIC_API_MOCK=1 via `build:mock` + `start`), so no backend is required.
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  // each page runs the app's WebGL field, so the suite is GPU-bound: at the
  // default worker count the parallel contexts wedge a renderer and an unrelated
  // page.evaluate never returns. Two workers is stable and no slower overall.
  workers: 2,
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
    // the light field behind the app is a WebGL loop; asking Chromium for reduced
    // motion makes it paint one frame and stop, which keeps 50+ parallel pages off
    // the GPU and makes full-page screenshots deterministic. It also exercises the
    // reduced-motion path every run — the hero and the reveals are visible
    // without motion.
    launchOptions: { args: ["--force-prefers-reduced-motion"] },
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
