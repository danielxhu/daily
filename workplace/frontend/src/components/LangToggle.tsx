"use client";

import { useLocale, useT } from "@/lib/i18n";

export function LangToggle() {
  const { locale, setLocale } = useLocale();
  const t = useT();

  return (
    <button
      type="button"
      onClick={() => setLocale(locale === "en" ? "zh" : "en")}
      aria-label={t("lang.aria")}
      className="min-h-[44px] min-w-[44px] whitespace-nowrap rounded-lg px-2 py-2 text-sm text-muted transition-colors hover:bg-panel hover:text-ink sm:px-3"
    >
      {t("lang.other")}
    </button>
  );
}
