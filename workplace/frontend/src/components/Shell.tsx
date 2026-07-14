import type { ReactNode } from "react";

/** Responsive page container — centered, max-width, mobile-first padding. */
export function Shell({ children }: { children: ReactNode }) {
  return <div className="mx-auto max-w-3xl px-4 py-6 sm:px-6">{children}</div>;
}
