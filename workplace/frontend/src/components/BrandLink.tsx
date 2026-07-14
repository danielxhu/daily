"use client";

import Link from "next/link";

import { useT } from "@/lib/i18n";

/** The header wordmark home link. Client-only so its accessible name follows the
 * active locale (the layout itself stays a server component for metadata). */
export function BrandLink() {
  const t = useT();
  return (
    <Link
      href="/"
      className="text-base font-semibold tracking-tight text-ink"
      aria-label={t("layout.home.aria")}
    >
      daily
    </Link>
  );
}
