"use client";

import { useEffect, useState } from "react";

import { useLocale, useT } from "@/lib/i18n";
import { TodayView } from "@/components/TodayView";

/** The masthead date, in the active locale. Rendered after mount so SSR output is
 * stable (the date itself is presentation, not data). */
function MastheadDate() {
  const { locale } = useLocale();
  const [date, setDate] = useState("");
  useEffect(() => {
    setDate(
      new Intl.DateTimeFormat(locale === "zh" ? "zh-CN" : "en-US", {
        weekday: "long",
        year: "numeric",
        month: "long",
        day: "numeric",
      }).format(new Date()),
    );
  }, [locale]);
  return (
    <p className="mono tnum mb-2 text-xs text-faint" suppressHydrationWarning>
      {date}
    </p>
  );
}

export default function Home() {
  const t = useT();
  return (
    <div>
      <header className="border-b border-line pb-5">
        <MastheadDate />
        <h1 className="text-[28px] font-semibold tracking-[-0.02em] text-ink">{t("page.today.title")}</h1>
        <p className="mt-1 text-sm text-muted">
          {t("page.today.subtitle")}
        </p>
      </header>
      <section className="py-8">
        <TodayView />
      </section>
    </div>
  );
}
