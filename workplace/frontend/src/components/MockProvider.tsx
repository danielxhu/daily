"use client";

import { useEffect } from "react";
import type { ReactNode } from "react";

import { resolveMswReady } from "@/lib/msw-gate";

// When NEXT_PUBLIC_API_MOCK=1 (e.g. `npm run dev:mock`), start the MSW worker so
// the app serves a fixture /verify response without a real backend. In every
// other build the env is unset, so this is a transparent passthrough and the
// worker code is never loaded. Mount-time fetches in child views are gated on the
// msw-gate deferred (lib/api), so they wait for the worker instead of racing it.
// Module-level guard: React StrictMode mounts effects twice in dev, and a second
// worker.start() surfaces as a red error toast — the first pixel a beta demo shows.
let mswStarting = false;

export function MockProvider({ children }: { children: ReactNode }) {
  useEffect(() => {
    if (process.env.NEXT_PUBLIC_API_MOCK !== "1") {
      // M13.6 (beta P2 mock leak): a previously-run mock build leaves its service
      // worker registered on this origin — a REAL session on the same browser then
      // keeps serving fixture data (Acme/Beta) and a demo silently lies. Unregister
      // any leftover MSW worker; other service workers are left alone.
      void navigator.serviceWorker?.getRegistrations?.().then((regs) => {
        for (const reg of regs) {
          if ((reg.active?.scriptURL ?? "").includes("mockServiceWorker")) {
            void reg.unregister();
          }
        }
      });
      return;
    }
    if (mswStarting) return;
    mswStarting = true;
    void import("@/mocks/browser").then(({ worker }) =>
      worker.start({ onUnhandledRequest: "bypass" }).then(() => {
        resolveMswReady(); // release gated fetches
        // signal readiness so E2E can wait before submitting
        document.documentElement.dataset.mswReady = "true";
      }),
    );
  }, []);

  return <>{children}</>;
}
