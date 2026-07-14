"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { useT } from "@/lib/i18n";

/** Primary navigation in user-task language: Today / Sources / Knowledge. The
 * on-demand verify (Check) was removed from the product surface (2026-07-02); the
 * internal modules (full digest, boards, the fact-layer browse, run traces) live as
 * secondary "details & tools" links in the footer, so the app reads as an information
 * assistant, not a pipeline/debug console. */
export const PRIMARY_NAV = [
  { href: "/", key: "nav.today" },
  { href: "/tracking", key: "nav.sources" },
  { href: "/knowledge", key: "nav.knowledge" },
] as const;

function isActive(pathname: string, href: string): boolean {
  return href === "/" ? pathname === "/" : pathname.startsWith(href);
}

export function Nav() {
  const pathname = usePathname() ?? "/";
  const t = useT();
  return (
    <nav aria-label={t("nav.primary.aria")} className="flex items-center gap-1">
      {PRIMARY_NAV.map(({ href, key }) => {
        const active = isActive(pathname, href);
        return (
          <Link
            key={href}
            href={href}
            aria-current={active ? "page" : undefined}
            className={`rounded-lg px-2 py-2 text-sm transition-colors sm:px-3 ${
              active
                ? "bg-panel font-medium text-ink"
                : "text-faint hover:bg-panel/60 hover:text-ink"
            }`}
          >
            {t(key)}
          </Link>
        );
      })}
    </nav>
  );
}
