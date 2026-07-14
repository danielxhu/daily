"use client";

import { HELP_EVENT } from "@/components/Onboarding";
import { useT } from "@/lib/i18n";

/** Header guide entry — reopens the first-run guide (Onboarding listens for
 * HELP_EVENT). A labeled word, not a bare "?": the owner found the glyph cryptic
 * (2026-07-08). */
export function HelpButton() {
  const t = useT();
  return (
    <button
      type="button"
      onClick={() => window.dispatchEvent(new CustomEvent(HELP_EVENT))}
      aria-label={t("help.aria")}
      className="min-h-[44px] whitespace-nowrap rounded-lg px-2 py-2 text-sm text-muted transition-colors hover:bg-panel hover:text-ink sm:px-3"
    >
      {t("help.label")}
    </button>
  );
}
