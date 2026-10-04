"use client";

import Link from "next/link";

import { useT } from "@/lib/i18n";

// M9.5 — branded 404 instead of the default Next.js page.
export default function NotFound() {
  const t = useT();
  return (
    <div className="space-y-3">
      <h2 className="text-base font-semibold">{t("page.notFound.title")}</h2>
      <p className="text-sm text-muted">{t("page.notFound.body")}</p>
      <Link href="/" className="text-sm text-accent underline underline-offset-2">
        {t("page.notFound.link")}
      </Link>
    </div>
  );
}
