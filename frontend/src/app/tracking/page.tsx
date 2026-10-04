"use client";

import { useT } from "@/lib/i18n";
import { TrackingView } from "@/components/TrackingView";

export default function TrackingPage() {
  const t = useT();
  return (
    <div>
      <header className="border-b border-line pb-5">
        <h1 className="text-[28px] font-semibold tracking-[-0.02em] text-ink">{t("page.tracking.title")}</h1>
        <p className="mt-1 text-sm text-muted">
          {t("page.tracking.subtitle")}
        </p>
      </header>
      <section className="py-8">
        <TrackingView />
      </section>
    </div>
  );
}
