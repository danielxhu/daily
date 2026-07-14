"use client";

import { useT } from "@/lib/i18n";
import { TraceView } from "@/components/TraceView";

export default function TracePage() {
  const t = useT();
  return (
    <div>
      <header className="border-b border-line pb-4">
        <h1 className="text-[28px] font-semibold tracking-[-0.02em] text-ink">{t("page.trace.title")}</h1>
        <p className="mt-1 text-sm text-muted">
          {t("page.trace.subtitle")}
        </p>
      </header>
      <section className="py-6">
        <TraceView />
      </section>
    </div>
  );
}
