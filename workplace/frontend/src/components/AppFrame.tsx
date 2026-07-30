"use client";

import type { ReactNode } from "react";
import dynamic from "next/dynamic";
import { usePathname } from "next/navigation";

import { BrandLink } from "@/components/BrandLink";
import { FooterNav } from "@/components/FooterNav";
import { HelpButton } from "@/components/HelpButton";
import { Nav } from "@/components/Nav";
import { Shell } from "@/components/Shell";
import { useAppliedTheme } from "@/lib/prefs";

// keeps WebGL out of the shared bundle: the welcome page has its own composition
// and never mounts the field
const PlasmaField = dynamic(() => import("@/components/PlasmaField").then((m) => m.PlasmaField), {
  ssr: false,
});

/** The app chrome (header + container + footer). The welcome page is a full-bleed
 * composition with its own scroll and nav, so it renders bare — wrapping it in the
 * app container would also put that container over its content. */
export function AppFrame({ children }: { children: ReactNode }) {
  const path = usePathname();
  const theme = useAppliedTheme();
  if (path === "/welcome") return <main>{children}</main>;
  // Today puts its content on cards, so the field is the page behind them; the
  // reading surfaces keep the sheet
  const onCards = path === "/";
  return (
    <>
      <PlasmaField theme={theme} />
      <div aria-hidden="true" className={onCards ? "sheet sheet-veil" : "sheet"} />
      <header className="sticky top-0 z-20 border-b border-line bg-surface/80 backdrop-blur">
        {/* flex-wrap + compact paddings: the labeled Guide entry (M16.1) made
            the control cluster wider — the 375px header must never overlap */}
        <div className="mx-auto flex max-w-3xl flex-wrap items-center justify-between gap-x-4 gap-y-1 px-4 py-3 sm:px-6">
          <BrandLink />
          <div className="flex flex-wrap items-center justify-end gap-0.5 sm:gap-1">
            <Nav />
            <HelpButton />
          </div>
        </div>
      </header>
      <Shell wide={onCards}>
        <main className="animate-fade-in">{children}</main>
        {/* M16.1: the app-wide credibility disclaimer left with the check
            retirement — the tracked-note honesty line lives on the surfaces */}
        <footer className="mt-12 space-y-3 border-t border-line pt-6">
          <FooterNav />
        </footer>
      </Shell>
    </>
  );
}
