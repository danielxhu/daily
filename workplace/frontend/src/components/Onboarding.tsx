"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

import { useT } from "@/lib/i18n";

const STORAGE_KEY = "daily.onboarded";
/** HelpButton dispatches this to reopen the guide at any time. */
export const HELP_EVENT = "daily:help";

// First-run guide (M11.2; copy reworked with the M16.1 check retirement). An
// inline, dismissible panel — deliberately NOT a modal, so it never blocks the
// page for users (or the e2e suite). Shows until dismissed (localStorage), and
// the labeled header button reopens it. The copy keeps the honest v0.13
// boundaries: scheduled polling (not real time) and AI summaries that only
// restate the source — check the original.
export function Onboarding() {
  const [open, setOpen] = useState(false); // SSR/first paint: hidden (no flash)
  const t = useT();

  useEffect(() => {
    try {
      if (window.localStorage.getItem(STORAGE_KEY) !== "1") setOpen(true);
    } catch {
      // storage unavailable — leave the guide hidden rather than nag every visit
    }
    const reopen = () => setOpen(true);
    window.addEventListener(HELP_EVENT, reopen);
    return () => window.removeEventListener(HELP_EVENT, reopen);
  }, []);

  function dismiss() {
    setOpen(false);
    try {
      window.localStorage.setItem(STORAGE_KEY, "1");
    } catch {
      // storage unavailable — dismissal just won't persist
    }
  }

  if (!open) return null;

  const steps = [
    { title: t("onboard.step1.title"), body: t("onboard.step1.body"), href: "/tracking" },
    { title: t("onboard.step2.title"), body: t("onboard.step2.body"), href: null },
    { title: t("onboard.step3.title"), body: t("onboard.step3.body"), href: "/knowledge" },
  ];

  return (
    <section
      aria-label={t("onboard.title")}
      className="mb-8 rounded-xl border border-line bg-accent-soft/40 p-5"
      style={{ boxShadow: "inset 0 1px 0 rgb(255 255 255 / 0.04)" }}
    >
      <h2 className="text-base font-semibold tracking-[-0.01em] text-ink">
        {t("onboard.title")}
      </h2>
      <p className="mt-1 text-sm text-muted">{t("onboard.intro")}</p>
      <ol className="mt-5 space-y-4">
        {steps.map((step, i) => (
          <li key={step.title} className="flex gap-3.5">
            <span
              aria-hidden="true"
              className="mono tnum mt-0.5 inline-flex h-5 w-5 shrink-0 items-center justify-center rounded border border-accent/30 text-[11px] font-semibold text-accent-strong"
            >
              {i + 1}
            </span>
            <div>
              <p className="text-sm font-medium text-ink">
                {step.href ? (
                  <Link href={step.href} className="text-accent hover:text-accent-strong">
                    {step.title}
                  </Link>
                ) : (
                  step.title
                )}
              </p>
              <p className="mt-0.5 max-w-[65ch] text-xs leading-relaxed text-muted">
                {step.body}
              </p>
            </div>
          </li>
        ))}
      </ol>
      <button type="button" onClick={dismiss} className="btn-primary mt-5">
        {t("onboard.dismiss")}
      </button>
    </section>
  );
}
