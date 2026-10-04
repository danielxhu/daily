"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { useT } from "@/lib/i18n";
import { STATIC_DATA } from "@/lib/static-data";

// the GitHub Pages build links back to its repository (set by the Pages workflow)
const REPO_URL = STATIC_DATA ? process.env.NEXT_PUBLIC_REPO_URL : undefined;

/** Primary navigation in user-task language: Today / Sources / Knowledge. The
 * on-demand verify (Check) was removed from the product surface (2026-07-02); the
 * internal modules (full digest, boards, the fact-layer browse, run traces) live as
 * secondary "details & tools" links in the footer, so the app reads as an information
 * assistant, not a pipeline/debug console. */
export const PRIMARY_NAV = [
  { href: "/", key: "nav.today" },
  { href: "/tracking", key: "nav.sources" },
  { href: "/knowledge", key: "nav.knowledge" },
  // settings holds the model credentials and the language choice — a top-level
  // entry, not a buried footer link
  { href: "/settings", key: "nav.settings" },
] as const;

function isActive(pathname: string, href: string): boolean {
  return href === "/" ? pathname === "/" : pathname.startsWith(href);
}

export function Nav() {
  const pathname = usePathname() ?? "/";
  const t = useT();
  return (
    <nav aria-label={t("nav.primary.aria")} className="flex flex-wrap items-center gap-1">
      {REPO_URL && (
        <a
          href={REPO_URL}
          target="_blank"
          rel="noreferrer"
          aria-label={t("nav.github")}
          title={t("nav.github")}
          className="rounded-lg p-2 text-faint transition-colors hover:bg-panel/60 hover:text-ink"
        >
          {/* the GitHub mark — an icon keeps the 375px header from overflowing */}
          <svg aria-hidden="true" viewBox="0 0 16 16" width="16" height="16" fill="currentColor">
            <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z" />
          </svg>
        </a>
      )}
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
