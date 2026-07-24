"use client";

import { SettingsView } from "@/components/SettingsView";
import { useT } from "@/lib/i18n";

/** Settings (owner 2026-07-23): the model API credential slots. Secondary
 * surface (footer link) — daily works out of the box with the built-in text
 * model and the local on-device image OCR. */
export default function SettingsPage() {
  const t = useT();
  return (
    <div>
      <header className="border-b border-line pb-5">
        <h1 className="text-[28px] font-semibold tracking-[-0.02em] text-ink">
          {t("page.settings.title")}
        </h1>
        <p className="mt-1 text-sm text-muted">{t("page.settings.subtitle")}</p>
      </header>
      <div className="py-8">
        <SettingsView />
      </div>
    </div>
  );
}
