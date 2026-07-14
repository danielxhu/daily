import type { Metadata } from "next";
import type { ReactNode } from "react";

import { BrandLink } from "@/components/BrandLink";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { FooterNav } from "@/components/FooterNav";
import { HelpButton } from "@/components/HelpButton";
import { LangToggle } from "@/components/LangToggle";
import { MockProvider } from "@/components/MockProvider";
import { Nav } from "@/components/Nav";
import { Onboarding } from "@/components/Onboarding";
import { Shell } from "@/components/Shell";
import { LocaleProvider } from "@/lib/i18n";

import "./globals.css";

export const metadata: Metadata = {
  title: "daily",
  description:
    "Keeps watch on the sources you choose, sorts today's changes, and flags what to check.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen">
        <MockProvider>
          <LocaleProvider>
            <ErrorBoundary>
              <header className="sticky top-0 z-20 border-b border-line bg-surface/80 backdrop-blur">
                {/* flex-wrap + compact paddings: the labeled Guide entry (M16.1) made
                    the control cluster wider — the 375px header must never overlap */}
                <div className="mx-auto flex max-w-3xl flex-wrap items-center justify-between gap-x-4 gap-y-1 px-4 py-3 sm:px-6">
                  <BrandLink />
                  <div className="flex flex-wrap items-center justify-end gap-0.5 sm:gap-1">
                    <Nav />
                    <LangToggle />
                    <HelpButton />
                  </div>
                </div>
              </header>
              <Shell>
                <Onboarding />
                <main className="animate-fade-in">{children}</main>
                {/* M16.1: the app-wide credibility disclaimer left with the check
                    retirement — the tracked-note honesty line lives on the surfaces */}
                <footer className="mt-12 space-y-3 border-t border-line pt-6">
                  <FooterNav />
                </footer>
              </Shell>
            </ErrorBoundary>
          </LocaleProvider>
        </MockProvider>
      </body>
    </html>
  );
}
