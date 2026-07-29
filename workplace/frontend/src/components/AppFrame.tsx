"use client";

import type { ReactNode } from "react";
import { usePathname } from "next/navigation";

import { BrandLink } from "@/components/BrandLink";
import { FooterNav } from "@/components/FooterNav";
import { HelpButton } from "@/components/HelpButton";
import { Nav } from "@/components/Nav";
import { Shell } from "@/components/Shell";
import { SmoothScroll } from "@/components/SmoothScroll";

/** The app chrome (header + container + footer). The welcome page is a full-bleed
 * composition with its own scroll and nav, so it renders bare — wrapping it in the
 * app container would also put that container over its content. */
export function AppFrame({ children }: { children: ReactNode }) {
  const bare = usePathname() === "/welcome";
  if (bare) return <main>{children}</main>;
  return (
    <>
      <SmoothScroll />
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
      <Shell>
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
