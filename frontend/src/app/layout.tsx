import type { Metadata } from "next";
import type { ReactNode } from "react";

import { AppFrame } from "@/components/AppFrame";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { MockProvider } from "@/components/MockProvider";
import { LocaleProvider } from "@/lib/i18n";

import "./globals.css";

export const metadata: Metadata = {
  title: "daily",
  description:
    "Keeps watch on the sources you choose, sorts today's changes, and flags what to check.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        {/* set the theme and sheet opacity before first paint, else the stored
            choices flash */}
        <script
          dangerouslySetInnerHTML={{
            __html:
              "try{var t=localStorage.getItem('daily.theme');" +
              "if(t!=='dark'&&t!=='light')t=matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light';" +
              "document.documentElement.dataset.theme=t;" +
              "var a=parseFloat(localStorage.getItem('daily.sheetAlpha'));" +
              "if(a>=0.55&&a<=1)document.documentElement.style.setProperty('--sheet-a',String(a))}catch(e){}",
          }}
        />
      </head>
      <body className="min-h-screen">
        <MockProvider>
          <LocaleProvider>
            <ErrorBoundary>
              <AppFrame>{children}</AppFrame>
            </ErrorBoundary>
          </LocaleProvider>
        </MockProvider>
      </body>
    </html>
  );
}
