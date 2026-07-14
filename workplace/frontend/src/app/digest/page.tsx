"use client";

import { useT } from "@/lib/i18n";
import { DigestView } from "@/components/DigestView";

export default function DigestPage() {
  const t = useT();
  return (
    <div>
      <header className="border-b border-line pb-4">
        <h1 className="text-[28px] font-semibold tracking-[-0.02em] text-ink">{t("page.digest.title")}</h1>
        <p className="mt-1 text-sm text-muted">
          {t("page.digest.subtitle")}
        </p>
      </header>
      <section className="py-6">
        <DigestView />
      </section>
    </div>
  );
}
