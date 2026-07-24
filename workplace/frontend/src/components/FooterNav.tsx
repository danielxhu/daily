"use client";

import Link from "next/link";

import { useT } from "@/lib/i18n";

// boards browse moved into the Knowledge page (M12.4) — no separate footer entry.
// M16.1: the fact-layer browse (/memory) left the surface with the check retirement.
const SECONDARY_LINKS = [
  { href: "/digest", key: "footer.fullDigest" },
  { href: "/trace", key: "footer.runDetails" },
  { href: "/settings", key: "footer.settings" },
] as const;

export function FooterNav() {
  const t = useT();
  return (
    <nav
      aria-label={t("footer.nav.aria")}
      className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-faint"
    >
      {SECONDARY_LINKS.map(({ href, key }) => (
        <Link key={href} href={href} className="py-1 transition-colors hover:text-muted">
          {t(key)}
        </Link>
      ))}
    </nav>
  );
}
