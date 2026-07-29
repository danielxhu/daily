"use client";

import Link from "next/link";

import { useT } from "@/lib/i18n";

/** Header guide entry — the guide lives on the welcome page now. A labeled
 * word, not a bare "?": the glyph alone is cryptic. */
export function HelpButton() {
  const t = useT();
  return (
    <Link
      href="/welcome"
      aria-label={t("help.aria")}
      className="flex min-h-[44px] items-center whitespace-nowrap rounded-lg px-2 py-2 text-sm text-muted transition-colors hover:bg-panel hover:text-ink sm:px-3"
    >
      {t("help.label")}
    </Link>
  );
}
