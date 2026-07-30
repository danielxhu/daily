import type { ReactNode } from "react";

/** Responsive page container — centered, max-width, mobile-first padding. Sits
 * above the reading sheet, which AppFrame paints at the same width. */
export function Shell({ children }: { children: ReactNode }) {
  return <div className="relative z-10 mx-auto max-w-3xl px-4 py-6 sm:px-6">{children}</div>;
}
