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
    <p
      className="mono tnum text-[11px] uppercase tracking-[0.18em] text-faint"
      suppressHydrationWarning
    >
      {date}
    </p>
  );
}

export default function Home() {
  const t = useT();
  return (
    <div>
      {/* broadsheet masthead: a dateline over a serif nameplate, closed by a
          two-weight rule (a firm ink rule above a hairline) */}
      <header className="border-t-2 border-ink pt-4">
        <MastheadDate />
        <h1 className="serif mt-3 text-[clamp(2.25rem,6vw,3rem)] font-semibold leading-[1.05] tracking-[-0.02em] text-balance text-ink">
          {t("page.today.title")}
        </h1>
        <p className="mt-2 max-w-[60ch] text-sm leading-relaxed text-muted">
          {t("page.today.subtitle")}
        </p>
        <div aria-hidden="true" className="mt-5 border-b border-line" />
      </header>
      <section className="py-9">
        <TodayView />
      </section>
    </div>
  );
}
