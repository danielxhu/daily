"use client";

// M9.5 — route-level error fallback (Next app router). Component render errors inside
// a view land here instead of a blank/crashed page; the ErrorBoundary covers the rest.

import { useT } from "@/lib/i18n";

export default function Error({ reset }: { error: Error & { digest?: string }; reset: () => void }) {
  const t = useT();
  return (
    <div role="alert" className="space-y-3">
      <h2 className="text-base font-semibold">{t("page.error.title")}</h2>
      <p className="text-sm text-muted">{t("page.error.body")}</p>
      <button
        type="button"
        onClick={reset}
        className="btn-primary"
      >
        {t("page.error.retry")}
      </button>
    </div>
  );
}
